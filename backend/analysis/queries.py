"""
analysis/queries.py
Reusable analytical queries for NBA betting research.
Returns pandas DataFrames for easy downstream use.
"""

import logging
import pandas as pd
from backend.db.connection import get_connection

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Team performance
# ---------------------------------------------------------------------------

def team_record(team_abbr: str, season: str, conn=None) -> dict:
    """Win/loss record for a team in a given season."""
    close = conn is None
    conn = conn or get_connection()

    df = conn.execute("""
        SELECT
            COUNT(*) AS games,
            SUM(CASE
                WHEN (home_team_abbr = ? AND home_score > away_score)
                  OR (away_team_abbr = ? AND away_score > home_score) THEN 1 ELSE 0
            END) AS wins,
            SUM(CASE
                WHEN (home_team_abbr = ? AND home_score < away_score)
                  OR (away_team_abbr = ? AND away_score < home_score) THEN 1 ELSE 0
            END) AS losses
        FROM games
        WHERE season = ?
        AND status = 'Final'
        AND (home_team_abbr = ? OR away_team_abbr = ?)
    """, [team_abbr]*2 + [team_abbr]*2 + [season, team_abbr, team_abbr]).df()

    if close:
        conn.close()
    return df.iloc[0].to_dict()


def team_avg_stats(team_abbr: str, season: str, last_n: int = None, conn=None) -> pd.DataFrame:
    """Average team box score stats, optionally limited to last N games."""
    close = conn is None
    conn = conn or get_connection()

    limit_clause = f"LIMIT {last_n}" if last_n else ""

    df = conn.execute(f"""
        SELECT
            AVG(tgs.pts) AS avg_pts,
            AVG(tgs.reb) AS avg_reb,
            AVG(tgs.ast) AS avg_ast,
            AVG(tgs.tov) AS avg_tov,
            AVG(tgs.fg_pct) AS avg_fg_pct,
            AVG(tgs.fg3_pct) AS avg_fg3_pct,
            AVG(tgs.ft_pct) AS avg_ft_pct,
            AVG(tgs.pts) - AVG(opp.pts) AS avg_point_diff
        FROM (
            SELECT tgs.*, g.game_date FROM team_game_stats tgs
            JOIN teams t ON tgs.team_id = t.team_id
            JOIN games g ON tgs.game_id = g.game_id
            WHERE t.abbreviation = ? AND tgs.season = ?
            ORDER BY g.game_date DESC
            {limit_clause}
        ) tgs
        JOIN team_game_stats opp ON tgs.game_id = opp.game_id AND opp.team_id != tgs.team_id
    """, [team_abbr, season]).df()

    if close:
        conn.close()
    return df


def home_away_splits(team_abbr: str, season: str, conn=None) -> pd.DataFrame:
    """Home vs away performance splits."""
    close = conn is None
    conn = conn or get_connection()

    df = conn.execute("""
        SELECT
            tgs.is_home,
            COUNT(*) AS games,
            AVG(tgs.pts) AS avg_pts,
            AVG(tgs.pts) - AVG(opp.pts) AS avg_margin,
            SUM(CASE WHEN tgs.pts > opp.pts THEN 1 ELSE 0 END) AS wins
        FROM team_game_stats tgs
        JOIN teams t ON tgs.team_id = t.team_id
        JOIN team_game_stats opp ON tgs.game_id = opp.game_id AND opp.team_id != tgs.team_id
        WHERE t.abbreviation = ? AND tgs.season = ?
        GROUP BY tgs.is_home
    """, [team_abbr, season]).df()

    if close:
        conn.close()
    return df


# ---------------------------------------------------------------------------
# Point totals / over-under
# ---------------------------------------------------------------------------

def game_totals(season: str, conn=None) -> pd.DataFrame:
    """All game totals (combined score) with over/under odds if available."""
    close = conn is None
    conn = conn or get_connection()

    df = conn.execute("""
        SELECT
            g.game_id,
            g.game_date,
            g.home_team_abbr,
            g.away_team_abbr,
            g.home_score,
            g.away_score,
            (g.home_score + g.away_score) AS total_pts,
            o.home_point AS ou_line,
            CASE
                WHEN o.home_point IS NOT NULL
                THEN (g.home_score + g.away_score) > o.home_point
            END AS went_over
        FROM games g
        LEFT JOIN odds o ON g.game_id = o.game_id AND o.market = 'totals'
            AND o.bookmaker = 'draftkings'
        WHERE g.season = ? AND g.status = 'Final'
        ORDER BY g.game_date DESC
    """, [season]).df()

    if close:
        conn.close()
    return df


def over_under_rate(team_abbr: str, season: str, conn=None) -> dict:
    """How often does a team's games go over the total line?"""
    close = conn is None
    conn = conn or get_connection()

    df = conn.execute("""
        SELECT
            COUNT(*) AS games_with_line,
            SUM(CASE WHEN (g.home_score + g.away_score) > o.home_point THEN 1 ELSE 0 END) AS overs,
            SUM(CASE WHEN (g.home_score + g.away_score) < o.home_point THEN 1 ELSE 0 END) AS unders,
            AVG(g.home_score + g.away_score) AS avg_total,
            AVG(o.home_point) AS avg_line
        FROM games g
        JOIN odds o ON g.game_id = o.game_id AND o.market = 'totals'
        WHERE g.season = ?
        AND g.status = 'Final'
        AND (g.home_team_abbr = ? OR g.away_team_abbr = ?)
    """, [season, team_abbr, team_abbr]).df()

    if close:
        conn.close()
    return df.iloc[0].to_dict()


# ---------------------------------------------------------------------------
# Player props research
# ---------------------------------------------------------------------------

def player_stat_averages(player_name: str, season: str, last_n: int = None, conn=None) -> pd.DataFrame:
    """Average stats for a player, optionally over last N games."""
    close = conn is None
    conn = conn or get_connection()

    limit_clause = f"LIMIT {last_n}" if last_n else ""

    df = conn.execute(f"""
        SELECT
            AVG(s.pts) AS avg_pts,
            AVG(s.reb) AS avg_reb,
            AVG(s.ast) AS avg_ast,
            AVG(s.stl) AS avg_stl,
            AVG(s.blk) AS avg_blk,
            AVG(s.fg3m) AS avg_3pm,
            AVG(s.tov) AS avg_tov,
            AVG(s.plus_minus) AS avg_plus_minus,
            COUNT(*) AS games_played
        FROM (
            SELECT s.* FROM player_game_stats s
            JOIN players p ON s.player_id = p.player_id
            JOIN games g ON s.game_id = g.game_id
            WHERE p.full_name ILIKE ? AND s.season = ?
            ORDER BY g.game_date DESC
            {limit_clause}
        ) s
    """, [f"%{player_name}%", season]).df()

    if close:
        conn.close()
    return df


def player_game_log(player_name: str, season: str, conn=None) -> pd.DataFrame:
    """Full game-by-game log for a player."""
    close = conn is None
    conn = conn or get_connection()

    df = conn.execute("""
        SELECT
            g.game_date,
            g.home_team_abbr,
            g.away_team_abbr,
            s.min,
            s.pts, s.reb, s.ast, s.stl, s.blk,
            s.fg3m, s.fgm, s.fga, s.fg_pct,
            s.ftm, s.fta, s.tov, s.plus_minus
        FROM player_game_stats s
        JOIN players p ON s.player_id = p.player_id
        JOIN games g ON s.game_id = g.game_id
        WHERE p.full_name ILIKE ? AND s.season = ?
        ORDER BY g.game_date DESC
    """, [f"%{player_name}%", season]).df()

    if close:
        conn.close()
    return df


# ---------------------------------------------------------------------------
# ATS (against the spread) analysis
# ---------------------------------------------------------------------------

def ats_record(team_abbr: str, season: str, conn=None) -> dict:
    """Calculate a team's against-the-spread record."""
    close = conn is None
    conn = conn or get_connection()

    df = conn.execute("""
        SELECT
            COUNT(*) AS games,
            SUM(CASE
                WHEN g.home_team_abbr = ? AND (g.home_score - g.away_score) > o.home_point THEN 1
                WHEN g.away_team_abbr = ? AND (g.away_score - g.home_score) > o.away_point THEN 1
                ELSE 0
            END) AS ats_wins,
            SUM(CASE
                WHEN g.home_team_abbr = ? AND (g.home_score - g.away_score) < o.home_point THEN 1
                WHEN g.away_team_abbr = ? AND (g.away_score - g.home_score) < o.away_point THEN 1
                ELSE 0
            END) AS ats_losses
        FROM games g
        JOIN odds o ON g.game_id = o.game_id AND o.market = 'spreads'
        WHERE g.season = ? AND g.status = 'Final'
        AND (g.home_team_abbr = ? OR g.away_team_abbr = ?)
    """, [team_abbr]*4 + [season, team_abbr, team_abbr]).df()

    if close:
        conn.close()
    return df.iloc[0].to_dict()
