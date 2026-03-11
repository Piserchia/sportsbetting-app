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

from backend.db.connection import get_connection

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
            SELECT AVG(points), AVG(rebounds), AVG(assists), AVG(minutes), COUNT(*)
            FROM player_game_logs
            WHERE player_id = CAST(? AS TEXT)
        """, [player_id]).fetchone()

        # L10
        l10 = conn.execute("""
            SELECT AVG(points), AVG(rebounds), AVG(assists)
            FROM (
                SELECT points, rebounds, assists FROM player_game_logs
                WHERE player_id = CAST(? AS TEXT)
                ORDER BY game_date DESC LIMIT 10
            )
        """, [player_id]).fetchone()

        # L5
        l5 = conn.execute("""
            SELECT AVG(points)
            FROM (
                SELECT points FROM player_game_logs
                WHERE player_id = CAST(? AS TEXT)
                ORDER BY game_date DESC LIMIT 5
            )
        """, [player_id]).fetchone()

        # Season high
        high = conn.execute("""
            SELECT MAX(points) FROM player_game_logs
            WHERE player_id = CAST(? AS TEXT)
        """, [player_id]).fetchone()

        # Projection
        proj = conn.execute("""
            SELECT minutes_projection, points_mean, rebounds_mean, assists_mean
            FROM player_projections
            WHERE player_id = CAST(? AS TEXT)
            ORDER BY game_id DESC LIMIT 1
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
            "l10_avg_pts":         safe(l10[0]),
            "l10_avg_reb":         safe(l10[1]),
            "l10_avg_ast":         safe(l10[2]),
            "l5_avg_pts":          safe(l5[0]) if l5 else None,
            "season_high_pts":     safe(high[0], 0) if high else None,
            "minutes_projection":  safe(proj[0]) if proj else None,
            "points_projection":   safe(proj[1]) if proj else None,
            "rebounds_projection": safe(proj[2]) if proj else None,
            "assists_projection":  safe(proj[3]) if proj else None,
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

        # Build distribution curve (normal approximation) for frontend chart
        curve = []
        for i in range(81):
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
