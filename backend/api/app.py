"""
backend/api/app.py
FastAPI server — bridges DuckDB to the React frontend.

Run with:
    uvicorn backend.api.app:app --reload --port 8000
"""

import os
import sys
import math
import logging
from datetime import date, timedelta
from typing import Optional
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from backend.database.connection import get_connection
from backend.models.edges_query import get_best_edges
import pandas as pd

logger = logging.getLogger(__name__)

app = FastAPI(title="Sports Betting Analytics API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174", "http://localhost:5175", "http://localhost:5176", "http://localhost:5177", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CURRENT_SEASON = os.getenv("CURRENT_SEASON", "2025-26")


# ── Helpers ────────────────────────────────────────────────────────────────

def prob_to_american(p: float) -> Optional[int]:
    if not p or p <= 0 or p >= 1:
        return None
    if p >= 0.5:
        return round(-(p / (1 - p)) * 100)
    return round(((1 - p) / p) * 100)


def american_to_implied(odds: float) -> float:
    if odds > 0:
        return 100 / (odds + 100)
    return abs(odds) / (abs(odds) + 100)


def calc_edge(model_prob: float, book_odds: float) -> Optional[float]:
    if model_prob is None or book_odds is None:
        return None
    return round((model_prob - american_to_implied(book_odds)) * 100, 2)


def safe(val, decimals=1):
    if val is None:
        return None
    try:
        return round(float(val), decimals)
    except Exception:
        return None


# ── Health ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    try:
        conn = get_connection()
        conn.execute("SELECT 1").fetchone()
        conn.close()
        return {"status": "ok", "db": "connected", "season": CURRENT_SEASON}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


# ── Players ────────────────────────────────────────────────────────────────

@app.get("/players")
def search_players(
    q: Optional[str] = Query(None, description="Name search"),
    active_only: bool = True,
    limit: int = 25,
):
    """Search/list players. Used for the player search box."""
    conn = get_connection()
    try:
        filters = []
        params = []

        if active_only:
            filters.append("p.is_active = TRUE")
        if q:
            filters.append("p.full_name ILIKE ?")
            params.append(f"%{q}%")

        where = f"WHERE {' AND '.join(filters)}" if filters else ""

        rows = conn.execute(f"""
            SELECT DISTINCT
                p.player_id,
                p.full_name,
                t.abbreviation AS team
            FROM players p
            LEFT JOIN (
                SELECT player_id, team_id,
                       ROW_NUMBER() OVER (PARTITION BY player_id ORDER BY game_id DESC) AS rn
                FROM player_game_stats
            ) latest ON p.player_id = latest.player_id AND latest.rn = 1
            LEFT JOIN teams t ON latest.team_id = t.team_id
            {where}
            ORDER BY p.full_name
            LIMIT ?
        """, params + [limit]).fetchall()

        return [{"player_id": r[0], "full_name": r[1], "team": r[2] or "—"} for r in rows]
    finally:
        conn.close()


@app.get("/players/{player_id}/profile")
def player_profile(player_id: int):
    """Player info, season averages, projections, and next game context."""
    conn = get_connection()
    try:
        player = conn.execute(
            "SELECT player_id, full_name, is_active FROM players WHERE player_id = ?",
            [player_id]
        ).fetchone()
        if not player:
            raise HTTPException(404, "Player not found")

        # Most recent team
        team_row = conn.execute("""
            SELECT t.abbreviation, t.full_name
            FROM player_game_stats pgs
            JOIN teams t ON pgs.team_id = t.team_id
            WHERE pgs.player_id = ?
            ORDER BY pgs.game_id DESC LIMIT 1
        """, [player_id]).fetchone()

        team_abbr = team_row[0] if team_row else "—"

        # Season averages
        avgs = conn.execute("""
            SELECT AVG(points), AVG(rebounds), AVG(assists), AVG(minutes), COUNT(*),
                   AVG(steals), AVG(blocks)
            FROM player_game_logs
            WHERE player_id = CAST(? AS TEXT)
        """, [player_id]).fetchone()

        # L10
        l10 = conn.execute("""
            SELECT AVG(points), AVG(rebounds), AVG(assists), AVG(steals), AVG(blocks)
            FROM (
                SELECT points, rebounds, assists, steals, blocks FROM player_game_logs
                WHERE player_id = CAST(? AS TEXT)
                ORDER BY game_date DESC LIMIT 10
            )
        """, [player_id]).fetchone()

        # L5
        l5 = conn.execute("""
            SELECT AVG(points), AVG(rebounds), AVG(assists), AVG(steals), AVG(blocks)
            FROM (
                SELECT points, rebounds, assists, steals, blocks FROM player_game_logs
                WHERE player_id = CAST(? AS TEXT)
                ORDER BY game_date DESC LIMIT 5
            )
        """, [player_id]).fetchone()

        # Season high
        high = conn.execute("""
            SELECT MAX(points) FROM player_game_logs
            WHERE player_id = CAST(? AS TEXT)
        """, [player_id]).fetchone()

        # Projection — only from upcoming games to avoid showing stale historical data
        proj = conn.execute("""
            SELECT pp.minutes_projection, pp.points_mean, pp.rebounds_mean, pp.assists_mean,
                   COALESCE(pp.steals_mean, 0.0), COALESCE(pp.blocks_mean, 0.0)
            FROM player_projections pp
            JOIN games g ON pp.game_id = g.game_id
            WHERE pp.player_id = CAST(? AS TEXT)
              AND g.game_date >= CURRENT_DATE
              AND g.status != 'Final'
            ORDER BY g.game_date ASC LIMIT 1
        """, [player_id]).fetchone()

        # Next upcoming game
        today = date.today()
        next_game = conn.execute("""
            SELECT g.game_id, g.game_date, g.home_team_abbr, g.away_team_abbr
            FROM games g
            JOIN player_game_stats pgs ON g.game_id = pgs.game_id
            WHERE pgs.player_id = ? AND g.game_date >= ? AND g.status != 'Final'
            ORDER BY g.game_date ASC LIMIT 1
        """, [player_id, today]).fetchone()

        opponent = None
        next_game_id = None
        if next_game:
            next_game_id = next_game[0]
            opponent = next_game[3] if next_game[2] == team_abbr else next_game[2]

        return {
            "player_id":           player[0],
            "full_name":           player[1],
            "team":                team_abbr,
            "is_active":           player[2],
            "season_avg_pts":      safe(avgs[0]),
            "season_avg_reb":      safe(avgs[1]),
            "season_avg_ast":      safe(avgs[2]),
            "season_avg_min":      safe(avgs[3]),
            "games_played":        int(avgs[4]) if avgs and avgs[4] else 0,
            "season_avg_stl":      safe(avgs[5]),
            "season_avg_blk":      safe(avgs[6]),
            "l10_avg_pts":         safe(l10[0]),
            "l10_avg_reb":         safe(l10[1]),
            "l10_avg_ast":         safe(l10[2]),
            "l10_avg_stl":         safe(l10[3]),
            "l10_avg_blk":         safe(l10[4]),
            "l5_avg_pts":          safe(l5[0]) if l5 else None,
            "l5_avg_reb":          safe(l5[1]) if l5 else None,
            "l5_avg_ast":          safe(l5[2]) if l5 else None,
            "l5_avg_stl":          safe(l5[3]) if l5 else None,
            "l5_avg_blk":          safe(l5[4]) if l5 else None,
            "season_high_pts":     safe(high[0], 0) if high else None,
            "minutes_projection":  safe(proj[0]) if proj else None,
            "points_projection":   safe(proj[1]) if proj else None,
            "rebounds_projection": safe(proj[2]) if proj else None,
            "assists_projection":  safe(proj[3]) if proj else None,
            "steals_projection":   safe(proj[4]) if proj else None,
            "blocks_projection":   safe(proj[5]) if proj else None,
            "opponent":            opponent,
            "next_game_id":        next_game_id,
            "next_game_date":      str(next_game[1]) if next_game else None,
        }
    finally:
        conn.close()


@app.get("/players/{player_id}/game-log")
def player_game_log(player_id: int, limit: int = 10):
    """Last N games. Falls back to player_game_stats if player_game_logs not yet populated."""
    conn = get_connection()
    try:
        # Check if player_game_logs has data for this player
        log_count = conn.execute(
            "SELECT COUNT(*) FROM player_game_logs WHERE player_id = CAST(? AS TEXT)",
            [player_id]
        ).fetchone()[0]

        if log_count > 0:
            # Use normalized game log table (populated after build_features.py)
            rows = conn.execute("""
                SELECT
                    pgl.game_id, pgl.game_date, pgl.team,
                    pgl.minutes, pgl.points, pgl.rebounds, pgl.assists,
                    pgl.steals, pgl.blocks, pgl.turnovers,
                    g.home_team_abbr, g.away_team_abbr
                FROM player_game_logs pgl
                JOIN games g ON pgl.game_id = g.game_id
                WHERE pgl.player_id = CAST(? AS TEXT)
                ORDER BY pgl.game_date DESC LIMIT ?
            """, [player_id, limit]).fetchall()

            result = []
            for r in rows:
                home_abbr = r[10]
                away_abbr = r[11]
                team      = r[2]
                is_home   = (team == home_abbr)
                opponent  = away_abbr if is_home else home_abbr
                matchup   = f"vs {opponent}" if is_home else f"@ {opponent}"
                result.append({
                    "game_id":   r[0],
                    "date":      str(r[1]),
                    "matchup":   matchup,
                    "opponent":  opponent,
                    "minutes":   safe(r[3]),
                    "points":    safe(r[4], 0),
                    "rebounds":  safe(r[5], 0),
                    "assists":   safe(r[6], 0),
                    "steals":    safe(r[7], 0),
                    "blocks":    safe(r[8], 0),
                    "turnovers": safe(r[9], 0),
                })
            return result

        # Fallback: read directly from player_game_stats (raw ingestion table)
        rows = conn.execute("""
            SELECT
                pgs.game_id,
                g.game_date,
                t.abbreviation      AS team,
                pgs.min,
                pgs.pts, pgs.reb, pgs.ast,
                pgs.stl, pgs.blk, pgs.tov,
                g.home_team_abbr,
                g.away_team_abbr
            FROM player_game_stats pgs
            JOIN games g  ON pgs.game_id  = g.game_id
            JOIN teams t  ON pgs.team_id  = t.team_id
            WHERE pgs.player_id = ?
            ORDER BY g.game_date DESC
            LIMIT ?
        """, [player_id, limit]).fetchall()

        result = []
        for r in rows:
            home_abbr = r[10]
            away_abbr = r[11]
            team      = r[2]
            is_home   = (team == home_abbr)
            opponent  = away_abbr if is_home else home_abbr
            matchup   = f"vs {opponent}" if is_home else f"@ {opponent}"

            # Parse "MM:SS" minutes string to float
            min_str = r[3] or "0:00"
            try:
                parts = str(min_str).split(":")
                minutes = float(parts[0]) + float(parts[1]) / 60 if len(parts) == 2 else float(parts[0])
            except Exception:
                minutes = None

            result.append({
                "game_id":   r[0],
                "date":      str(r[1]),
                "matchup":   matchup,
                "opponent":  opponent,
                "minutes":   safe(minutes),
                "points":    safe(r[4], 0),
                "rebounds":  safe(r[5], 0),
                "assists":   safe(r[6], 0),
                "steals":    safe(r[7], 0),
                "blocks":    safe(r[8], 0),
                "turnovers": safe(r[9], 0),
            })

        return result
    finally:
        conn.close()


@app.get("/players/{player_id}/simulations")
def player_simulations(player_id: int, stat: str = "points"):
    """
    Monte Carlo probability ladder for a player + stat.
    Also returns the distribution curve for charting.
    """
    conn = get_connection()
    try:
        # Probability ladder
        lines = conn.execute("""
            SELECT line, probability
            FROM player_simulations
            WHERE player_id = CAST(? AS TEXT) AND stat = ?
            ORDER BY line ASC
        """, [player_id, stat]).fetchall()

        if not lines:
            raise HTTPException(404, f"No simulations found for player {player_id} stat={stat}")

        # Distribution params from player_distributions
        dist = conn.execute("""
            SELECT mean, std_dev
            FROM player_distributions
            WHERE player_id = CAST(? AS TEXT) AND stat = ?
            ORDER BY game_id DESC LIMIT 1
        """, [player_id, stat]).fetchone()

        mean   = float(dist[0]) if dist else 0
        std    = float(dist[1]) if dist else 5

        # Build distribution curve — range depends on stat
        CURVE_MAX = {
            "steals": 10, "blocks": 10, "rebounds": 20, "assists": 20,
        }.get(stat, 80)
        curve = []
        for i in range(CURVE_MAX + 1):
            x = float(i)
            if std > 0:
                y = (1 / (std * math.sqrt(2 * math.pi))) * math.exp(-0.5 * ((x - mean) / std) ** 2)
            else:
                y = 0
            curve.append({"x": x, "y": round(y * 100, 5)})

        ladder = []
        for line, prob in lines:
            ladder.append({
                "line":       float(line),
                "probability": round(float(prob), 4),
                "fair_odds":  prob_to_american(float(prob)),
            })

        return {
            "player_id": player_id,
            "stat":      stat,
            "mean":      round(mean, 2),
            "std_dev":   round(std, 2),
            "curve":     curve,
            "ladder":    ladder,
        }
    finally:
        conn.close()


@app.get("/players/{player_id}/props")
def player_props(player_id: int, stat: str = "points"):
    """
    Sportsbook prop lines joined with model probabilities.
    Returns edge % per book per line.
    Falls back to model-only if no sportsbook props are loaded yet.
    """
    conn = get_connection()
    try:
        # Check if sportsbook_props table exists and has data
        try:
            props_count = conn.execute(
                "SELECT COUNT(*) FROM sportsbook_props WHERE player_id = CAST(? AS TEXT) AND stat = ?",
                [player_id, stat]
            ).fetchone()[0]
        except Exception:
            props_count = 0

        if props_count > 0:
            # Real sportsbook data
            rows = conn.execute("""
                SELECT
                    sp.line,
                    sp.over_odds,
                    sp.under_odds,
                    sp.book,
                    ps.probability AS model_prob
                FROM sportsbook_props sp
                LEFT JOIN player_simulations ps
                    ON  sp.player_id = ps.player_id
                    AND sp.stat      = ps.stat
                    AND sp.line      = ps.line
                WHERE sp.player_id = CAST(? AS TEXT) AND sp.stat = ?
                ORDER BY sp.line ASC, sp.book
            """, [player_id, stat]).fetchall()

            result = {}
            for line, over_odds, under_odds, book, model_prob in rows:
                line = float(line)
                if line not in result:
                    result[line] = {
                        "line":         line,
                        "model_prob":   round(float(model_prob), 4) if model_prob else None,
                        "fair_odds":    prob_to_american(float(model_prob)) if model_prob else None,
                        "books":        {},
                    }
                result[line]["books"][book] = {
                    "over_odds":  over_odds,
                    "under_odds": under_odds,
                    "edge":       calc_edge(model_prob, over_odds) if model_prob else None,
                }

            return {"source": "sportsbook", "stat": stat, "lines": list(result.values())}

        else:
            # Model-only fallback — return simulations with fair odds only
            rows = conn.execute("""
                SELECT line, probability
                FROM player_simulations
                WHERE player_id = CAST(? AS TEXT) AND stat = ?
                ORDER BY line ASC
            """, [player_id, stat]).fetchall()

            lines = []
            for line, prob in rows:
                lines.append({
                    "line":       float(line),
                    "model_prob": round(float(prob), 4),
                    "fair_odds":  prob_to_american(float(prob)),
                    "books":      {},
                })

            return {"source": "model_only", "stat": stat, "lines": lines}
    finally:
        conn.close()


@app.get("/games/today")
def games_today():
    """Today's NBA slate with home/away teams."""
    conn = get_connection()
    try:
        today = date.today()
        rows = conn.execute("""
            SELECT
                g.game_id,
                g.game_date,
                g.home_team_abbr,
                g.away_team_abbr,
                ht.full_name AS home_name,
                at.full_name AS away_name,
                g.status
            FROM games g
            JOIN teams ht ON g.home_team_id = ht.team_id
            JOIN teams at ON g.away_team_id = at.team_id
            WHERE g.game_date = ?
            ORDER BY g.game_id
        """, [today]).fetchall()

        return [{
            "game_id":       r[0],
            "date":          str(r[1]),
            "home_abbr":     r[2],
            "away_abbr":     r[3],
            "home_name":     r[4],
            "away_name":     r[5],
            "status":        r[6],
            "matchup_label": f"{r[3]} @ {r[2]}",
        } for r in rows]
    finally:
        conn.close()


@app.get("/edges/today")
def edges_today(min_probability: float = 0.6, stat: Optional[str] = None):
    """
    Best prop edges for today's games only.
    Limited to top 3 lines per player, sorted by edge_percent (or model_probability
    when no sportsbook data is available).

    Returns empty if no edges exist for today — never falls back to previous dates.
    """
    conn = get_connection()
    try:
        target_date = date.today()

        stat_filter = "AND pe.stat = ?" if stat else ""
        params = [str(target_date), min_probability]
        if stat:
            params.insert(1, stat)

        PROJ_COL = {
            "points": "pp.points_mean", "rebounds": "pp.rebounds_mean",
            "assists": "pp.assists_mean", "steals": "pp.steals_mean",
            "blocks": "pp.blocks_mean",
        }

        def _edge_query(extra_where: str) -> str:
            return f"""
                SELECT
                    pe.game_id,
                    pe.player_id,
                    p.full_name,
                    t.abbreviation AS team,
                    g.home_team_abbr,
                    g.away_team_abbr,
                    pe.stat,
                    pe.line,
                    pe.model_probability,
                    pe.fair_odds,
                    pe.sportsbook_odds,
                    pe.edge_percent,
                    pe.book,
                    pe.expected_value,
                    pp.points_mean,
                    pp.rebounds_mean,
                    pp.assists_mean,
                    pp.steals_mean,
                    pp.blocks_mean,
                    ROW_NUMBER() OVER (
                        PARTITION BY pe.player_id, pe.stat
                        ORDER BY COALESCE(pe.edge_percent, pe.model_probability) DESC
                    ) AS rn
                FROM prop_edges pe
                JOIN games g ON pe.game_id = g.game_id
                JOIN players p ON CAST(pe.player_id AS INTEGER) = p.player_id
                LEFT JOIN (
                    SELECT player_id, team_id,
                           ROW_NUMBER() OVER (PARTITION BY player_id ORDER BY game_id DESC) AS team_rn
                    FROM player_game_stats
                ) latest ON CAST(pe.player_id AS INTEGER) = latest.player_id AND latest.team_rn = 1
                LEFT JOIN teams t ON latest.team_id = t.team_id
                LEFT JOIN player_projections pp
                    ON pe.player_id = pp.player_id
                    AND pe.game_id  = pp.game_id
                WHERE g.game_date = ?
                {stat_filter}
                AND pe.model_probability >= ?
                AND (pe.fair_odds IS NULL OR pe.fair_odds > -1000)
                {extra_where}
                QUALIFY rn <= 3
                ORDER BY COALESCE(pe.edge_percent, 0) DESC, pe.model_probability DESC
            """

        rows = conn.execute(_edge_query("AND pe.book != 'model_only'"), params).fetchall()

        # If no sportsbook rows, fall back to model_only
        if not rows:
            params_mo = [str(target_date), min_probability]
            if stat:
                params_mo.insert(1, stat)
            rows = conn.execute(_edge_query(""), params_mo).fetchall()

        STAT_MEAN_IDX = {"points": 14, "rebounds": 15, "assists": 16, "steals": 17, "blocks": 18}

        edges = []
        for r in rows:
            home, away = r[4], r[5]
            team = r[3] or "—"
            matchup = f"{away} @ {home}" if home and away else "—"
            stat_name = r[6]
            mean_idx = STAT_MEAN_IDX.get(stat_name)
            model_mean = round(float(r[mean_idx]), 1) if mean_idx and r[mean_idx] else None
            edges.append({
                "game_id":           r[0],
                "player_id":         r[1],
                "player_name":       r[2],
                "team":              team,
                "matchup":           matchup,
                "stat":              stat_name,
                "line":              float(r[7]),
                "model_mean":        model_mean,
                "model_probability": round(float(r[8]), 4) if r[8] else None,
                "fair_odds":         int(r[9]) if r[9] else None,
                "sportsbook_odds":   r[10],
                "edge_percent":      round(float(r[11]), 2) if r[11] else None,
                "book":              r[12],
                "expected_value":    round(float(r[13]), 4) if r[13] else None,
            })

        has_book_data = any(e["edge_percent"] is not None for e in edges)

        # Pipeline readiness context for the frontend
        today_str = str(target_date)
        games_today = conn.execute(
            "SELECT COUNT(*) FROM games WHERE game_date = ?", [today_str]
        ).fetchone()[0]
        upcoming_games = conn.execute(
            "SELECT COUNT(*) FROM games WHERE game_date = ? AND status = 'Upcoming'", [today_str]
        ).fetchone()[0]
        has_props = conn.execute(
            "SELECT COUNT(*) FROM sportsbook_props sp JOIN games g ON sp.game_id = g.game_id WHERE g.game_date = ?", [today_str]
        ).fetchone()[0] > 0
        has_sims = conn.execute(
            "SELECT COUNT(*) FROM player_simulations ps JOIN games g ON ps.game_id = g.game_id WHERE g.game_date = ?", [today_str]
        ).fetchone()[0] > 0

        return {
            "date":          today_str,
            "source":        "sportsbook" if has_book_data else "model_only",
            "edges":         edges,
            "games_today":   games_today,
            "upcoming_games": upcoming_games,
            "has_props":     has_props,
            "has_sims":      has_sims,
        }
    finally:
        conn.close()


@app.get("/pipeline/status")
def pipeline_status():
    """
    Returns last-run timestamps and record counts for each pipeline stage.
    Used by the frontend Pipeline Status page.
    """
    conn = get_connection()
    try:
        # Last run per source/entity from ingestion_log.
        # Strip season suffixes (e.g. "games:2024-25" → "games") for grouping.
        log_rows = conn.execute("""
            SELECT source, entity, status, records_written, message, ran_at
            FROM (
                SELECT *,
                    REGEXP_REPLACE(entity, ':.*$', '') AS entity_base,
                    ROW_NUMBER() OVER (
                        PARTITION BY source, REGEXP_REPLACE(entity, ':.*$', '')
                        ORDER BY ran_at DESC
                    ) AS rn
                FROM ingestion_log
            ) WHERE rn = 1
            ORDER BY source, entity_base
        """).fetchall()

        ingestion = [
            {
                "source":   r[0],
                "entity":   r[1].split(":")[0],  # strip season suffix for key matching
                "status":   r[2],
                "records":  r[3],
                "message":  r[4],
                "ran_at":   str(r[5]),
            }
            for r in log_rows
        ]

        # DB record counts for key tables
        def count(table):
            try:
                return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            except Exception:
                return 0

        def latest(table, col="game_id"):
            try:
                row = conn.execute(f"SELECT MAX({col}) FROM {table}").fetchone()
                return str(row[0]) if row and row[0] else None
            except Exception:
                return None

        counts = {
            "teams":              count("teams"),
            "players":            count("players"),
            "games":              count("games"),
            "player_game_stats":  count("player_game_stats"),
            "player_game_logs":   count("player_game_logs"),
            "player_features":    count("player_features"),
            "player_projections": count("player_projections"),
            "player_simulations": count("player_simulations"),
            "sportsbook_props":   count("sportsbook_props"),
            "prop_line_history":  count("prop_line_history"),
            "prop_edges":         count("prop_edges"),
        }

        # Most recent game date in the DB
        latest_game = conn.execute(
            "SELECT MAX(game_date) FROM games WHERE status = 'Final'"
        ).fetchone()
        latest_game_date = str(latest_game[0]) if latest_game and latest_game[0] else None

        # Most recent feature build
        latest_feature = conn.execute(
            "SELECT g.game_date FROM player_features pf "
            "JOIN games g ON pf.game_id = g.game_id "
            "ORDER BY g.game_date DESC LIMIT 1"
        ).fetchone()
        latest_feature_date = str(latest_feature[0]) if latest_feature and latest_feature[0] else None

        return {
            "ingestion":           ingestion,
            "counts":              counts,
            "latest_game_date":    latest_game_date,
            "latest_feature_date": latest_feature_date,
        }
    finally:
        conn.close()


@app.get("/games/{game_id}/matchup-flags")
def matchup_flags(game_id: str, player_id: int = Query(...)):
    """
    Contextual matchup intelligence flags for a player in a specific game.
    Surfaces pace, defensive rating, rest days, and recent H2H performance.
    """
    conn = get_connection()
    try:
        # Get game info
        game = conn.execute("""
            SELECT home_team_abbr, away_team_abbr, game_date
            FROM games WHERE game_id = ?
        """, [game_id]).fetchone()
        if not game:
            raise HTTPException(404, "Game not found")

        # Get player's team
        team_row = conn.execute("""
            SELECT t.abbreviation FROM player_game_stats pgs
            JOIN teams t ON pgs.team_id = t.team_id
            WHERE pgs.player_id = ?
            ORDER BY pgs.game_id DESC LIMIT 1
        """, [player_id]).fetchone()

        player_team = team_row[0] if team_row else None
        opponent    = game[1] if game[0] == player_team else game[0]
        game_date   = game[2]

        flags = []

        # ── Rest days ──
        last_game = conn.execute("""
            SELECT g.game_date FROM games g
            JOIN player_game_stats pgs ON g.game_id = pgs.game_id
            WHERE pgs.player_id = ? AND g.game_date < ?
            ORDER BY g.game_date DESC LIMIT 1
        """, [player_id, game_date]).fetchone()

        if last_game:
            rest_days = (game_date - last_game[0]).days
            if rest_days >= 2:
                flags.append({
                    "type":     "REST",
                    "severity": "GOOD",
                    "label":    f"{rest_days} days rest — higher mins likely",
                    "icon":     "✓",
                })
            elif rest_days == 1:
                flags.append({
                    "type":     "REST",
                    "severity": "CAUTION",
                    "label":    "Back-to-back — minutes may be managed",
                    "icon":     "⚠",
                })

        # ── Opponent avg points allowed (proxy for defensive strength) ──
        opp_def = conn.execute("""
            SELECT AVG(CASE WHEN home_team_abbr = ? THEN away_score ELSE home_score END)
            FROM games
            WHERE (home_team_abbr = ? OR away_team_abbr = ?)
            AND status = 'Final'
            AND season = ?
        """, [opponent, opponent, opponent, CURRENT_SEASON]).fetchone()

        if opp_def and opp_def[0]:
            pts_allowed = round(float(opp_def[0]), 1)
            if pts_allowed > 115:
                flags.append({
                    "type":     "DEF",
                    "severity": "GOOD",
                    "label":    f"{opponent} allowing {pts_allowed} pts/game — weak defense",
                    "icon":     "🔥",
                })
            elif pts_allowed < 108:
                flags.append({
                    "type":     "DEF",
                    "severity": "CAUTION",
                    "label":    f"{opponent} allowing only {pts_allowed} pts/game — tough defense",
                    "icon":     "🛡",
                })
            else:
                flags.append({
                    "type":     "DEF",
                    "severity": "NEUTRAL",
                    "label":    f"{opponent} allowing {pts_allowed} pts/game — average defense",
                    "icon":     "○",
                })

        # ── Opponent pace (total points as proxy) ──
        opp_pace = conn.execute("""
            SELECT AVG(COALESCE(home_score,0) + COALESCE(away_score,0))
            FROM games
            WHERE (home_team_abbr = ? OR away_team_abbr = ?)
            AND status = 'Final'
            AND season = ?
        """, [opponent, opponent, CURRENT_SEASON]).fetchone()

        if opp_pace and opp_pace[0]:
            avg_total = round(float(opp_pace[0]), 1)
            if avg_total > 228:
                flags.append({
                    "type":     "PACE",
                    "severity": "HIGH",
                    "label":    f"{opponent} games averaging {avg_total} total pts — fast pace",
                    "icon":     "⚡",
                })
            elif avg_total < 215:
                flags.append({
                    "type":     "PACE",
                    "severity": "CAUTION",
                    "label":    f"{opponent} games averaging {avg_total} total pts — slow pace",
                    "icon":     "🐢",
                })

        # ── Historical H2H vs this opponent ──
        h2h = conn.execute("""
            SELECT AVG(pgl.points), COUNT(*)
            FROM player_game_logs pgl
            JOIN games g ON pgl.game_id = g.game_id
            WHERE pgl.player_id = CAST(? AS TEXT)
            AND (g.home_team_abbr = ? OR g.away_team_abbr = ?)
            AND g.status = 'Final'
        """, [player_id, opponent, opponent]).fetchone()

        if h2h and h2h[1] and int(h2h[1]) >= 2:
            avg_vs = round(float(h2h[0]), 1)
            games_vs = int(h2h[1])

            # Compare to season avg
            season_avg = conn.execute("""
                SELECT AVG(points) FROM player_game_logs
                WHERE player_id = CAST(? AS TEXT)
            """, [player_id]).fetchone()

            if season_avg and season_avg[0]:
                diff = avg_vs - float(season_avg[0])
                if diff >= 3:
                    flags.append({
                        "type":     "H2H",
                        "severity": "GOOD",
                        "label":    f"Averaging {avg_vs} pts vs {opponent} last {games_vs} games (+{round(diff,1)} vs season avg)",
                        "icon":     "🔥",
                    })
                elif diff <= -3:
                    flags.append({
                        "type":     "H2H",
                        "severity": "CAUTION",
                        "label":    f"Averaging {avg_vs} pts vs {opponent} last {games_vs} games ({round(diff,1)} vs season avg)",
                        "icon":     "📉",
                    })

        return {"game_id": game_id, "opponent": opponent, "flags": flags}
    finally:
        conn.close()


@app.get("/edges/best")
def edges_best(
    limit: int = 100,
    min_edge: float = 0.0,
    min_line: Optional[float] = None,
    max_line: Optional[float] = None,
):
    """
    All sportsbook lines per prop for today, grouped by (player, stat, line).
    Each edge includes a nested books list with per-book odds and edge %.
    Ranked by bet_score = (edge_percent * 0.6) + (model_probability * 25).
    Supports optional min_line / max_line filtering.
    """
    conn = get_connection()
    try:
        df = get_best_edges(conn, limit=limit, min_edge=min_edge, min_line=min_line, max_line=max_line)

        if df.empty:
            # Pipeline readiness context
            today_str = str(date.today())
            games_today = conn.execute(
                "SELECT COUNT(*) FROM games WHERE game_date = ?", [today_str]
            ).fetchone()[0]
            upcoming_games = conn.execute(
                "SELECT COUNT(*) FROM games WHERE game_date = ? AND status = 'Upcoming'", [today_str]
            ).fetchone()[0]
            has_props = conn.execute(
                "SELECT COUNT(*) FROM sportsbook_props sp JOIN games g ON sp.game_id = g.game_id WHERE g.game_date = ?", [today_str]
            ).fetchone()[0] > 0
            has_sims = conn.execute(
                "SELECT COUNT(*) FROM player_simulations ps JOIN games g ON ps.game_id = g.game_id WHERE g.game_date = ?", [today_str]
            ).fetchone()[0] > 0
            return {
                "edges": [],
                "games_today": games_today,
                "upcoming_games": upcoming_games,
                "has_props": has_props,
                "has_sims": has_sims,
            }

        stat_mean_col = {
            "points":   "points_mean",
            "rebounds": "rebounds_mean",
            "assists":  "assists_mean",
            "steals":   "steals_mean",
            "blocks":   "blocks_mean",
        }

        # Group all book rows by (game_id, player_id, stat, line)
        prop_map: dict = {}
        for _, row in df.iterrows():
            stat = row["stat"]
            key = (row["game_id"], row["player_id"], stat, float(row["line"]))

            if key not in prop_map:
                mean_col = stat_mean_col.get(stat)
                projection = float(row[mean_col]) if mean_col and row[mean_col] is not None and not (isinstance(row[mean_col], float) and math.isnan(row[mean_col])) else None
                line_val = float(row["line"])
                line_diff = round(projection - line_val, 2) if projection is not None else None
                matchup = f"{row['away_team_abbr']} @ {row['home_team_abbr']}"

                prop_map[key] = {
                    "game_id":      row["game_id"],
                    "player_id":    row["player_id"],
                    "player":       row["player_name"],
                    "matchup":      matchup,
                    "home_team":    row["home_team_abbr"],
                    "away_team":    row["away_team_abbr"],
                    "game_status":  row["game_status"],
                    "game_time_et": row["game_time_et"] if row["game_time_et"] is not None and not (isinstance(row["game_time_et"], float) and math.isnan(row["game_time_et"])) else None,
                    "stat":         stat,
                    "line":         line_val,
                    "projection":   projection,
                    "line_diff":    line_diff,
                    "probability":  round(float(row["model_probability"]), 4),
                    "fair_odds":    int(row["fair_odds"]) if row["fair_odds"] is not None else None,
                    "books":        [],
                    "best_edge":    round(float(row["edge_percent"]), 2),
                    "score":        round(float(row["bet_score"]), 2),
                }

            prop_map[key]["books"].append({
                "book":         row["book"],
                "odds":         int(row["sportsbook_odds"]) if row["sportsbook_odds"] is not None else None,
                "edge_percent": round(float(row["edge_percent"]), 2),
            })

        # Sort books within each prop by edge desc; ensure prop list ordered by score desc
        edges = []
        for entry in prop_map.values():
            entry["books"].sort(key=lambda b: b["edge_percent"], reverse=True)
            edges.append(entry)

        edges.sort(key=lambda e: e["score"], reverse=True)
        return {"edges": edges}
    finally:
        conn.close()


@app.get("/players/{player_id}/projection_explanation")
def get_projection_explanation(player_id: int, stat: str = Query(default="points")):
    """
    Return SHAP feature contributions explaining why the model produced
    a specific projection for a player/stat.
    """
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT feature, contribution
            FROM projection_explanations
            WHERE player_id = ?
              AND stat = ?
            ORDER BY ABS(contribution) DESC
        """, [player_id, stat]).fetchall()

        if not rows:
            return {"player_id": player_id, "stat": stat, "contributions": [], "source": "no_data"}

        contributions = [
            {"feature": r[0], "contribution": round(r[1], 4)}
            for r in rows
        ]

        positive = [c for c in contributions if c["contribution"] > 0][:5]
        negative = [c for c in contributions if c["contribution"] < 0][:5]

        return {
            "player_id": player_id,
            "stat": stat,
            "contributions": contributions,
            "top_positive": positive,
            "top_negative": negative,
            "source": "shap",
        }
    finally:
        conn.close()


@app.get("/debug/shap/{player_id}")
def debug_shap(player_id: int, stat: str = Query(default="points")):
    """
    Recompute SHAP on-demand for a player/stat and return full diagnostics:
    feature contributions, model baseline, prediction, and input feature values.
    """
    conn = get_connection()
    try:
        from backend.models.stat_models.stat_models import (
            _MODEL_CACHE, STAT_FEATURES, compute_shap_contributions,
            _enrich_with_game_context,
        )

        if not _MODEL_CACHE:
            raise HTTPException(
                status_code=503,
                detail="Model cache is empty — run the projection pipeline first."
            )

        # Load this player's feature row
        rows = conn.execute("""
            SELECT pf.*
            FROM player_features pf
            JOIN games g ON pf.game_id = g.game_id
            WHERE pf.player_id = CAST(? AS TEXT)
              AND g.game_date = CURRENT_DATE
            LIMIT 1
        """, [player_id]).df()

        if rows.empty:
            # Fallback: most recent feature row
            rows = conn.execute("""
                SELECT * FROM player_features
                WHERE player_id = CAST(? AS TEXT)
                ORDER BY game_id DESC
                LIMIT 1
            """, [player_id]).df()

        if rows.empty:
            raise HTTPException(status_code=404, detail="No feature row found for player.")

        # Enrich with game context
        rows = _enrich_with_game_context(rows, conn)

        row = rows.iloc[0]
        pos_group = row.get("position_group", "Forward")

        # Find model
        cache_key = (stat, pos_group)
        if cache_key not in _MODEL_CACHE:
            cache_key = (stat, "all")
        if cache_key not in _MODEL_CACHE:
            raise HTTPException(
                status_code=404,
                detail=f"No trained model for stat={stat} position={pos_group}. "
                       f"Available: {list(_MODEL_CACHE.keys())}"
            )

        model = _MODEL_CACHE[cache_key]
        feat_cols = STAT_FEATURES.get(stat, [])
        available = [c for c in feat_cols if c in rows.columns]
        X_row = pd.DataFrame([row[available].fillna(0.0).values], columns=available)

        shap_result = compute_shap_contributions(
            model, X_row, available,
            player_id=player_id, stat=stat, position_group=pos_group,
        )

        # Build feature values dict
        feature_values = {col: float(X_row[col].iloc[0]) for col in available if col in X_row.columns}

        contributions_sorted = sorted(
            shap_result["contributions"].items(),
            key=lambda x: abs(x[1]),
            reverse=True,
        )

        return {
            "player_id": player_id,
            "stat": stat,
            "position_group": pos_group,
            "model_key": list(cache_key),
            "base_value": round(shap_result["base_value"], 4),
            "prediction": round(shap_result["prediction"], 4),
            "shap_sum": round(sum(shap_result["contributions"].values()) + shap_result["base_value"], 4),
            "feature_count": len(available),
            "model_feature_count": len(model.feature_name()),
            "contributions": [
                {"feature": f, "shap_value": round(v, 4), "feature_value": feature_values.get(f)}
                for f, v in contributions_sorted
            ],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Debug SHAP failed for player %s stat %s: %s", player_id, stat, e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ── Model Health ──────────────────────────────────────────────────────────

@app.get("/model/backtests")
def model_backtests():
    """Aggregated backtest metrics by stat from model_backtests table."""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT stat,
                   SUM(n_predictions)   AS total_predictions,
                   ROUND(AVG(hit_rate), 4)    AS avg_hit_rate,
                   ROUND(AVG(brier_score), 4) AS avg_brier,
                   ROUND(AVG(log_loss), 4)    AS avg_log_loss,
                   ROUND(AVG(roi), 2)         AS avg_roi,
                   ROUND(AVG(avg_edge), 4)    AS avg_edge,
                   MAX(run_date)        AS last_run
            FROM model_backtests
            GROUP BY stat
            ORDER BY stat
        """).fetchall()

        return {
            "stats": [
                {
                    "stat":              r[0],
                    "total_predictions": int(r[1]),
                    "avg_hit_rate":      float(r[2]),
                    "avg_brier":         float(r[3]),
                    "avg_log_loss":      float(r[4]),
                    "avg_roi":           float(r[5]),
                    "avg_edge":          float(r[6]),
                    "last_run":          r[7],
                }
                for r in rows
            ]
        }
    except Exception:
        return {"stats": []}
    finally:
        conn.close()


@app.get("/model/performance")
def model_performance():
    """Live betting performance from bet_results (CLV tracker)."""
    try:
        from backend.models.clv_tracker import get_performance_summary
        summary = get_performance_summary()
        return summary
    except Exception as e:
        logger.warning("Performance summary unavailable: %s", e)
        return {
            "total_bets": 0, "wins": 0, "losses": 0, "pushes": 0,
            "roi": 0.0, "avg_clv": 0.0, "brier_score": None, "log_loss": None,
        }


@app.get("/model/feature-importance")
def model_feature_importance(stat: str = Query(default="points")):
    """Global LightGBM feature importance (gain-based) for a stat, from DB."""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT feature, importance, position_group
            FROM model_feature_importance
            WHERE stat = ?
            ORDER BY importance DESC
            LIMIT 15
        """, [stat]).fetchall()
        if not rows:
            return {"stat": stat, "features": [], "message": "No feature importance data. Run the projection pipeline to train models."}
        return {
            "stat": stat,
            "features": [{"feature": r[0], "importance": round(float(r[1]), 2)} for r in rows],
        }
    finally:
        conn.close()


@app.get("/model/projection-accuracy")
def model_projection_accuracy():
    """MAE and RMSE of projections vs actuals for completed games."""
    conn = get_connection()
    try:
        # player_projections has columns: points_mean, rebounds_mean, etc.
        # player_game_logs has: points, rebounds, assists, steals, blocks
        stats_config = [
            ("points",   "points_mean",   "points"),
            ("rebounds", "rebounds_mean",  "rebounds"),
            ("assists",  "assists_mean",   "assists"),
            ("steals",   "steals_mean",    "steals"),
            ("blocks",   "blocks_mean",    "blocks"),
        ]
        results = []
        for stat_name, proj_col, actual_col in stats_config:
            row = conn.execute(f"""
                SELECT
                    ROUND(AVG(ABS(pp.{proj_col} - pgl.{actual_col})), 2) AS mae,
                    ROUND(SQRT(AVG(POW(pp.{proj_col} - pgl.{actual_col}, 2))), 2) AS rmse,
                    COUNT(*) AS n
                FROM player_projections pp
                JOIN player_game_logs pgl
                    ON pp.game_id = pgl.game_id AND pp.player_id = pgl.player_id
                JOIN games g ON pp.game_id = g.game_id
                WHERE g.status = 'Final'
                  AND pp.{proj_col} IS NOT NULL
                  AND pgl.{actual_col} IS NOT NULL
            """).fetchone()
            if row and row[2] > 0:
                results.append({
                    "stat": stat_name,
                    "mae":  float(row[0]),
                    "rmse": float(row[1]),
                    "n":    int(row[2]),
                })
        return {"accuracy": results}
    except Exception as e:
        logger.warning("Projection accuracy unavailable: %s", e)
        return {"accuracy": []}
    finally:
        conn.close()


@app.get("/model/calibration")
def model_calibration(stat: str = Query(default="points")):
    """
    Calibration curve: predicted probability bins vs actual hit rates.
    Computed from player_simulations vs player_game_logs actuals.
    """
    conn = get_connection()
    try:
        df = conn.execute(f"""
            SELECT ps.probability,
                   CASE WHEN pgl.{stat} >= ps.line THEN 1.0 ELSE 0.0 END AS hit
            FROM player_simulations ps
            JOIN player_game_logs pgl
                ON ps.game_id = pgl.game_id AND ps.player_id = pgl.player_id
            JOIN games g ON ps.game_id = g.game_id
            WHERE ps.stat = ?
              AND g.status = 'Final'
              AND pgl.{stat} IS NOT NULL
        """, [stat]).df()

        if df.empty:
            return {"stat": stat, "bins": [], "ece": None}

        import numpy as np
        n_bins = 10
        edges = np.linspace(0, 1, n_bins + 1)
        bins = []
        ece = 0.0
        n_total = len(df)

        for i in range(n_bins):
            mask = (df["probability"] >= edges[i]) & (df["probability"] < edges[i + 1])
            count = int(mask.sum())
            if count == 0:
                continue
            pred_avg = float(df.loc[mask, "probability"].mean())
            actual_avg = float(df.loc[mask, "hit"].mean())
            ece += (count / n_total) * abs(pred_avg - actual_avg)
            bins.append({
                "bin_center": round((edges[i] + edges[i + 1]) / 2, 2),
                "predicted":  round(pred_avg, 4),
                "actual":     round(actual_avg, 4),
                "count":      count,
            })

        return {"stat": stat, "bins": bins, "ece": round(ece, 4)}
    except Exception as e:
        logger.warning("Calibration unavailable: %s", e)
        return {"stat": stat, "bins": [], "ece": None}
    finally:
        conn.close()


@app.get("/model/drift")
def model_drift(stat: str = Query(default="points")):
    """Projection error (actual - predicted) over time, grouped by game date."""
    conn = get_connection()
    try:
        col_map = {"points": "points_mean", "rebounds": "rebounds_mean",
                    "assists": "assists_mean", "steals": "steals_mean", "blocks": "blocks_mean"}
        proj_col = col_map.get(stat, "points_mean")
        rows = conn.execute(f"""
            SELECT DATE(g.game_date) AS game_date,
                   ROUND(AVG(pgl.{stat} - pp.{proj_col}), 2) AS error,
                   COUNT(*) AS n
            FROM player_projections pp
            JOIN player_game_logs pgl ON pp.game_id = pgl.game_id AND pp.player_id = pgl.player_id
            JOIN games g ON g.game_id = pp.game_id
            WHERE g.status = 'Final' AND pp.{proj_col} IS NOT NULL
            GROUP BY DATE(g.game_date)
            ORDER BY game_date
        """).fetchall()
        return {"stat": stat, "drift": [{"date": str(r[0]), "error": float(r[1]), "n": int(r[2])} for r in rows]}
    except Exception as e:
        logger.warning("Drift unavailable: %s", e)
        return {"stat": stat, "drift": []}
    finally:
        conn.close()


@app.get("/model/edge-realization")
def model_edge_realization():
    """ROI bucketed by model probability bands from bet_results."""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT
                CASE
                    WHEN model_probability < 0.55 THEN '50-55%'
                    WHEN model_probability < 0.60 THEN '55-60%'
                    WHEN model_probability < 0.65 THEN '60-65%'
                    WHEN model_probability < 0.70 THEN '65-70%'
                    ELSE '70%+'
                END AS bucket,
                COUNT(*) AS count,
                ROUND(AVG(CASE WHEN result='win' THEN profit ELSE -stake END), 2) AS avg_profit
            FROM bet_results
            WHERE model_probability >= 0.50
            GROUP BY bucket
            ORDER BY bucket
        """).fetchall()
        return {"buckets": [{"range": r[0], "count": int(r[1]), "roi": float(r[2])} for r in rows]}
    except Exception:
        return {"buckets": []}
    finally:
        conn.close()


@app.get("/model/projection-distribution")
def model_projection_distribution(stat: str = Query(default="points")):
    """Histogram of projected stat means across all players."""
    conn = get_connection()
    try:
        col_map = {"points": "points_mean", "rebounds": "rebounds_mean",
                    "assists": "assists_mean", "steals": "steals_mean", "blocks": "blocks_mean"}
        col = col_map.get(stat, "points_mean")
        rows = conn.execute(f"""
            SELECT
                CASE
                    WHEN {col} < 5 THEN '0-5'
                    WHEN {col} < 10 THEN '5-10'
                    WHEN {col} < 15 THEN '10-15'
                    WHEN {col} < 20 THEN '15-20'
                    WHEN {col} < 25 THEN '20-25'
                    WHEN {col} < 30 THEN '25-30'
                    WHEN {col} < 35 THEN '30-35'
                    ELSE '35+'
                END AS range,
                COUNT(*) AS count
            FROM player_projections
            WHERE {col} IS NOT NULL
            GROUP BY range
            ORDER BY range
        """).fetchall()
        return {"stat": stat, "bins": [{"range": r[0], "count": int(r[1])} for r in rows]}
    except Exception as e:
        logger.warning("Projection distribution unavailable: %s", e)
        return {"stat": stat, "bins": []}
    finally:
        conn.close()


@app.get("/model/global-drivers")
def model_global_drivers(stat: str = Query(default="points")):
    """Top features by average absolute SHAP contribution across all players."""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT feature, ROUND(AVG(ABS(contribution)), 4) AS avg_shap
            FROM projection_explanations
            WHERE stat = ?
            GROUP BY feature
            ORDER BY avg_shap DESC
            LIMIT 15
        """, [stat]).fetchall()
        return {
            "stat": stat,
            "drivers": [{"feature": r[0], "avg_shap": float(r[1])} for r in rows],
        }
    except Exception as e:
        logger.warning("Global drivers unavailable: %s", e)
        return {"stat": stat, "drivers": []}
    finally:
        conn.close()


@app.get("/model/shrinkage-diagnostics")
def model_shrinkage_diagnostics(stat: str = Query(default="points"), limit: int = 25):
    """Players with the largest Bayesian shrinkage adjustments."""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT psp.player_id, p.full_name, psp.stat,
                   psp.player_mean, psp.posterior_mean, psp.prior_mean,
                   psp.n_games, psp.position_group,
                   ROUND(ABS(psp.posterior_mean - psp.player_mean), 4) AS shrinkage_delta
            FROM player_stat_posteriors psp
            LEFT JOIN players p ON CAST(psp.player_id AS INTEGER) = p.player_id
            WHERE psp.stat = ?
            ORDER BY shrinkage_delta DESC
            LIMIT ?
        """, [stat, limit]).fetchall()
        return {
            "stat": stat,
            "players": [
                {
                    "player_id": r[0],
                    "player_name": r[1] or f"Player {r[0]}",
                    "stat": r[2],
                    "player_mean": float(r[3]),
                    "posterior_mean": float(r[4]),
                    "prior_mean": float(r[5]),
                    "n_games": int(r[6]),
                    "position_group": r[7],
                    "shrinkage_delta": float(r[8]),
                }
                for r in rows
            ],
        }
    except Exception as e:
        logger.warning("Shrinkage diagnostics unavailable: %s", e)
        return {"stat": stat, "players": []}
    finally:
        conn.close()


# ── Bet Tracking Endpoints ────────────────────────────────────────────────────

@app.get("/bets/recent")
def bets_recent(limit: int = 200, stat: Optional[str] = None, position: Optional[str] = None):
    """Return recent tracked bets from model_recommendations with optional filters."""
    conn = get_connection()
    try:
        where_clauses = []
        params = []
        if stat:
            where_clauses.append("mr.stat = ?")
            params.append(stat)
        if position:
            where_clauses.append("mr.player_position = ?")
            params.append(position)
        where_sql = (" AND " + " AND ".join(where_clauses)) if where_clauses else ""
        params.append(limit)

        rows = conn.execute(f"""
            SELECT
                mr.timestamp_generated,
                mr.player_name,
                mr.team,
                mr.stat,
                mr.line,
                mr.sportsbook,
                mr.odds,
                mr.model_probability,
                mr.edge_percent,
                mr.confidence_score,
                mr.actual_stat,
                mr.result,
                mr.closing_line,
                mr.closing_odds,
                mr.model_version,
                g.game_date,
                g.home_team_abbr,
                g.away_team_abbr,
                mr.game_id,
                mr.player_id,
                mr.player_position,
                mr.opponent_team
            FROM model_recommendations mr
            LEFT JOIN games g ON mr.game_id = g.game_id
            WHERE 1=1{where_sql}
            ORDER BY mr.timestamp_generated DESC
            LIMIT ?
        """, params).fetchall()

        bets = []
        for r in rows:
            bets.append({
                "timestamp": str(r[0]) if r[0] else None,
                "player": r[1],
                "team": r[2],
                "stat": r[3],
                "line": float(r[4]) if r[4] is not None else None,
                "sportsbook": r[5],
                "odds": int(r[6]) if r[6] is not None else None,
                "probability": round(float(r[7]), 4) if r[7] is not None else None,
                "edge": round(float(r[8]), 2) if r[8] is not None else None,
                "confidence": round(float(r[9]), 2) if r[9] is not None else None,
                "actual": float(r[10]) if r[10] is not None else None,
                "result": r[11],
                "closing_line": float(r[12]) if r[12] is not None else None,
                "closing_odds": int(r[13]) if r[13] is not None else None,
                "model_version": r[14],
                "date": str(r[15]) if r[15] else None,
                "matchup": f"{r[17]} @ {r[16]}" if r[16] and r[17] else None,
                "game_id": r[18],
                "player_id": r[19],
                "position": r[20],
                "opponent": r[21],
            })
        return {"bets": bets, "count": len(bets)}
    finally:
        conn.close()


@app.get("/bets/performance")
def bets_performance():
    """Return aggregate performance metrics for tracked bets."""
    conn = get_connection()
    try:
        total = conn.execute("SELECT COUNT(*) FROM model_recommendations").fetchone()[0]
        wins = conn.execute("SELECT COUNT(*) FROM model_recommendations WHERE result = 'win'").fetchone()[0]
        losses = conn.execute("SELECT COUNT(*) FROM model_recommendations WHERE result = 'loss'").fetchone()[0]
        pushes = conn.execute("SELECT COUNT(*) FROM model_recommendations WHERE result = 'push'").fetchone()[0]
        pending = conn.execute("SELECT COUNT(*) FROM model_recommendations WHERE result IS NULL").fetchone()[0]

        resolved = wins + losses + pushes
        win_rate = round(wins / resolved * 100, 1) if resolved > 0 else 0.0

        # ROI: assume $100 per bet, standard -110 juice
        # Win pays profit based on actual odds; loss costs $100
        roi_row = conn.execute("""
            SELECT
                SUM(CASE
                    WHEN result = 'win' AND odds > 0 THEN odds
                    WHEN result = 'win' AND odds < 0 THEN CAST(10000.0 / ABS(odds) AS DOUBLE)
                    WHEN result = 'loss' THEN -100
                    ELSE 0
                END) AS net_profit,
                SUM(CASE WHEN result IN ('win', 'loss') THEN 100 ELSE 0 END) AS total_risked
            FROM model_recommendations
            WHERE result IS NOT NULL AND result != 'push'
        """).fetchone()
        net_profit = float(roi_row[0]) if roi_row[0] else 0.0
        total_risked = float(roi_row[1]) if roi_row[1] else 0.0
        roi = round(net_profit / total_risked * 100, 1) if total_risked > 0 else 0.0

        # Average CLV
        clv_row = conn.execute("""
            SELECT AVG(closing_line - line)
            FROM model_recommendations
            WHERE closing_line IS NOT NULL AND result IS NOT NULL
        """).fetchone()
        avg_clv = round(float(clv_row[0]), 2) if clv_row[0] is not None else None

        return {
            "total_bets": total,
            "wins": wins,
            "losses": losses,
            "pushes": pushes,
            "pending": pending,
            "win_rate": win_rate,
            "roi": roi,
            "avg_clv": avg_clv,
        }
    finally:
        conn.close()


@app.get("/bets/by-model")
def bets_by_model():
    """Return performance metrics grouped by model version."""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT
                model_version,
                COUNT(*) AS total,
                SUM(CASE WHEN result = 'win' THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN result = 'loss' THEN 1 ELSE 0 END) AS losses,
                SUM(CASE WHEN result = 'push' THEN 1 ELSE 0 END) AS pushes,
                SUM(CASE
                    WHEN result = 'win' AND odds > 0 THEN odds
                    WHEN result = 'win' AND odds < 0 THEN CAST(10000.0 / ABS(odds) AS DOUBLE)
                    WHEN result = 'loss' THEN -100
                    ELSE 0
                END) AS net_profit,
                SUM(CASE WHEN result IN ('win', 'loss') THEN 100 ELSE 0 END) AS total_risked,
                AVG(CASE WHEN closing_line IS NOT NULL AND result IS NOT NULL
                    THEN closing_line - line ELSE NULL END) AS avg_clv
            FROM model_recommendations
            GROUP BY model_version
            ORDER BY model_version DESC
        """).fetchall()

        models = []
        for r in rows:
            resolved = (r[2] or 0) + (r[3] or 0) + (r[4] or 0)
            win_rate = round(r[2] / resolved * 100, 1) if resolved > 0 else 0.0
            roi = round(float(r[5]) / float(r[6]) * 100, 1) if r[6] and float(r[6]) > 0 else 0.0
            models.append({
                "model_version": r[0],
                "bets": r[1],
                "wins": r[2] or 0,
                "losses": r[3] or 0,
                "pushes": r[4] or 0,
                "win_rate": win_rate,
                "roi": roi,
                "avg_clv": round(float(r[7]), 2) if r[7] is not None else None,
            })
        return {"models": models}
    finally:
        conn.close()


@app.get("/bets/by-type")
def bets_by_type():
    """Return performance metrics grouped by stat type."""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT
                stat,
                COUNT(*) AS total,
                SUM(CASE WHEN result = 'win' THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN result = 'loss' THEN 1 ELSE 0 END) AS losses,
                SUM(CASE
                    WHEN result = 'win' AND odds > 0 THEN odds
                    WHEN result = 'win' AND odds < 0 THEN CAST(10000.0 / ABS(odds) AS DOUBLE)
                    WHEN result = 'loss' THEN -100
                    ELSE 0
                END) AS net_profit,
                SUM(CASE WHEN result IN ('win', 'loss') THEN 100 ELSE 0 END) AS total_risked
            FROM model_recommendations
            GROUP BY stat
            ORDER BY stat
        """).fetchall()

        result = []
        for r in rows:
            resolved = (r[2] or 0) + (r[3] or 0)
            win_rate = round(r[2] / resolved * 100, 1) if resolved > 0 else 0.0
            roi = round(float(r[4]) / float(r[5]) * 100, 1) if r[5] and float(r[5]) > 0 else 0.0
            result.append({
                "stat": r[0],
                "bets": r[1],
                "wins": r[2] or 0,
                "losses": r[3] or 0,
                "win_rate": win_rate,
                "roi": roi,
            })
        return {"types": result}
    finally:
        conn.close()


@app.get("/bets/by-position")
def bets_by_position():
    """Return performance metrics grouped by player position."""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT
                player_position,
                COUNT(*) AS total,
                SUM(CASE WHEN result = 'win' THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN result = 'loss' THEN 1 ELSE 0 END) AS losses,
                SUM(CASE
                    WHEN result = 'win' AND odds > 0 THEN odds
                    WHEN result = 'win' AND odds < 0 THEN CAST(10000.0 / ABS(odds) AS DOUBLE)
                    WHEN result = 'loss' THEN -100
                    ELSE 0
                END) AS net_profit,
                SUM(CASE WHEN result IN ('win', 'loss') THEN 100 ELSE 0 END) AS total_risked
            FROM model_recommendations
            WHERE player_position IS NOT NULL
            GROUP BY player_position
            ORDER BY player_position
        """).fetchall()

        result = []
        for r in rows:
            resolved = (r[2] or 0) + (r[3] or 0)
            win_rate = round(r[2] / resolved * 100, 1) if resolved > 0 else 0.0
            roi = round(float(r[4]) / float(r[5]) * 100, 1) if r[5] and float(r[5]) > 0 else 0.0
            result.append({
                "position": r[0],
                "bets": r[1],
                "wins": r[2] or 0,
                "losses": r[3] or 0,
                "win_rate": win_rate,
                "roi": roi,
            })
        return {"positions": result}
    finally:
        conn.close()


@app.get("/bets/type-position-matrix")
def bets_type_position_matrix():
    """Return win rates by stat type AND player position."""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT
                stat,
                player_position,
                COUNT(*) AS total,
                SUM(CASE WHEN result = 'win' THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN result = 'loss' THEN 1 ELSE 0 END) AS losses
            FROM model_recommendations
            WHERE player_position IS NOT NULL
              AND result IS NOT NULL
            GROUP BY stat, player_position
            ORDER BY stat, player_position
        """).fetchall()

        result = []
        for r in rows:
            resolved = (r[3] or 0) + (r[4] or 0)
            win_rate = round(r[3] / resolved * 100, 1) if resolved > 0 else 0.0
            result.append({
                "stat": r[0],
                "position": r[1],
                "bets": r[2],
                "win_rate": win_rate,
            })
        return {"matrix": result}
    finally:
        conn.close()


@app.post("/bets/reset")
def bets_reset():
    """Delete all tracked bet history."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM model_recommendations")
        return {"status": "tracking reset"}
    finally:
        conn.close()
