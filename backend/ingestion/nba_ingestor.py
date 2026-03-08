"""
ingestion/nba_ingestor.py
Pulls NBA data from nba_api and writes it into DuckDB.
Covers: teams, players, games (schedule), player box scores, team box scores.
"""

import os
import time
import uuid
import logging
import pandas as pd
from datetime import datetime, date
from typing import Optional

from nba_api.stats.static import teams as nba_teams_static
from nba_api.stats.static import players as nba_players_static
from nba_api.stats.endpoints import (
    leaguegamelog,
    boxscoretraditionalv2,
    teamgamelog,
)

from backend.db.connection import get_connection

logger = logging.getLogger(__name__)

NBA_API_DELAY = float(os.getenv("NBA_API_DELAY", "3.0"))
NBA_SEASONS = os.getenv("NBA_SEASONS", "2024-25").split(",")
NBA_API_MAX_RETRIES = int(os.getenv("NBA_API_MAX_RETRIES", "5"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log_ingestion(conn, source: str, entity: str, records: int, status: str, message: str = ""):
    conn.execute("""
        INSERT OR REPLACE INTO ingestion_log VALUES (?, ?, ?, ?, ?, ?, current_timestamp)
    """, [str(uuid.uuid4()), source, entity, records, status, message])


def _sleep():
    time.sleep(NBA_API_DELAY)


def _fetch_with_retry(fn, *args, **kwargs):
    """Call an nba_api endpoint with exponential backoff on timeout/error."""
    for attempt in range(1, NBA_API_MAX_RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            is_last = attempt == NBA_API_MAX_RETRIES
            wait = NBA_API_DELAY * (2 ** attempt)  # 6s, 12s, 24s, 48s, 96s
            if is_last:
                raise
            logger.warning(f"  Attempt {attempt}/{NBA_API_MAX_RETRIES} failed: {e}. Retrying in {wait:.0f}s...")
            time.sleep(wait)


# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------

def ingest_teams(conn=None) -> int:
    close = conn is None
    conn = conn or get_connection()
    logger.info("Ingesting teams...")

    all_teams = nba_teams_static.get_teams()
    df = pd.DataFrame(all_teams)

    # nba_api returns: id, full_name, abbreviation, nickname, city, state, year_founded
    records = 0
    for _, row in df.iterrows():
        conn.execute("""
            INSERT OR REPLACE INTO teams
                (team_id, full_name, abbreviation, nickname, city, state, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, current_timestamp)
        """, [
            int(row["id"]), row["full_name"], row["abbreviation"],
            row["nickname"], row["city"], row["state"]
        ])
        records += 1

    _log_ingestion(conn, "nba_api", "teams", records, "success")
    logger.info(f"  → {records} teams written.")
    if close:
        conn.close()
    return records


# ---------------------------------------------------------------------------
# Players
# ---------------------------------------------------------------------------

def ingest_players(conn=None) -> int:
    close = conn is None
    conn = conn or get_connection()
    logger.info("Ingesting players...")

    all_players = nba_players_static.get_players()
    df = pd.DataFrame(all_players)

    records = 0
    for _, row in df.iterrows():
        conn.execute("""
            INSERT OR REPLACE INTO players
                (player_id, full_name, first_name, last_name, is_active, updated_at)
            VALUES (?, ?, ?, ?, ?, current_timestamp)
        """, [
            int(row["id"]), row["full_name"], row["first_name"],
            row["last_name"], bool(row["is_active"])
        ])
        records += 1

    _log_ingestion(conn, "nba_api", "players", records, "success")
    logger.info(f"  → {records} players written.")
    if close:
        conn.close()
    return records


# ---------------------------------------------------------------------------
# Games (schedule + scores)
# ---------------------------------------------------------------------------

def ingest_games(seasons: Optional[list] = None, conn=None) -> int:
    close = conn is None
    conn = conn or get_connection()
    seasons = seasons or NBA_SEASONS
    total = 0

    for season in seasons:
        logger.info(f"Ingesting games for season {season}...")
        try:
            _sleep()
            gamelog = _fetch_with_retry(leaguegamelog.LeagueGameLog,
                season=season,
                season_type_all_star="Regular Season",
                league_id="00"
            )
            df = gamelog.get_data_frames()[0]

            records = 0
            for _, row in df.iterrows():
                game_id = str(row["GAME_ID"])
                game_date = pd.to_datetime(row["GAME_DATE"]).date()

                # Determine home/away from MATCHUP (e.g. "BOS vs. MIA" = home, "BOS @ MIA" = away)
                is_home = "vs." in row["MATCHUP"]
                team_id = int(row["TEAM_ID"])
                team_abbr = row["TEAM_ABBREVIATION"]

                # We upsert individual team rows; the games table gets merged below
                wl = row.get("WL", None)
                pts = int(row["PTS"]) if pd.notna(row.get("PTS")) else None

                # Build a minimal game record (we'll get both sides via separate rows)
                if is_home:
                    opp_abbr = row["MATCHUP"].split("vs. ")[-1].strip()
                    conn.execute("""
                        INSERT OR IGNORE INTO games
                            (game_id, season, game_date, home_team_id, away_team_id,
                             home_team_abbr, away_team_abbr, home_score, status, updated_at)
                        VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, current_timestamp)
                    """, [game_id, season, game_date, team_id, team_abbr, opp_abbr, pts,
                          "Final" if wl else "Upcoming"])
                    # Update home score
                    conn.execute("""
                        UPDATE games SET home_team_id=?, home_team_abbr=?, home_score=?
                        WHERE game_id=?
                    """, [team_id, team_abbr, pts, game_id])
                else:
                    opp_abbr = row["MATCHUP"].split("@ ")[-1].strip()
                    conn.execute("""
                        INSERT OR IGNORE INTO games
                            (game_id, season, game_date, home_team_id, away_team_id,
                             home_team_abbr, away_team_abbr, away_score, status, updated_at)
                        VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, current_timestamp)
                    """, [game_id, season, game_date, team_id, opp_abbr, team_abbr, pts,
                          "Final" if wl else "Upcoming"])
                    conn.execute("""
                        UPDATE games SET away_team_id=?, away_team_abbr=?, away_score=?
                        WHERE game_id=?
                    """, [team_id, team_abbr, pts, game_id])

                records += 1

            _log_ingestion(conn, "nba_api", f"games:{season}", records, "success")
            logger.info(f"  → {records} game rows for {season}.")
            total += records

        except Exception as e:
            logger.error(f"  Error ingesting games for {season}: {e}")
            _log_ingestion(conn, "nba_api", f"games:{season}", 0, "error", str(e))

    if close:
        conn.close()
    return total


# ---------------------------------------------------------------------------
# Box Scores (player + team level) — run after games are loaded
# ---------------------------------------------------------------------------

def ingest_box_scores(season: str, limit: Optional[int] = None, conn=None, force: bool = False) -> int:
    """
    Fetches traditional box scores for all Final games in a given season.
    This is slow (1 API call per game) — use limit for testing.

    Args:
        force: If True, re-fetches ALL games in the season ignoring what's
               already in player_game_stats. Use when box scores are missing
               despite the game appearing as already ingested.
    """
    close = conn is None
    conn = conn or get_connection()

    if force:
        logger.info(f"  FORCE mode — fetching ALL Final games for {season} regardless of existing data.")
        games_df = conn.execute("""
            SELECT game_id FROM games
            WHERE season = ? AND status = 'Final'
        """, [season]).df()
    else:
        games_df = conn.execute("""
            SELECT game_id FROM games
            WHERE season = ? AND status = 'Final'
            AND game_id NOT IN (SELECT DISTINCT game_id FROM player_game_stats)
        """, [season]).df()

    if limit:
        games_df = games_df.head(limit)

    logger.info(f"Fetching box scores for {len(games_df)} games in {season}...")
    player_records = 0
    team_records = 0

    for _, row in games_df.iterrows():
        game_id = row["game_id"]
        try:
            _sleep()
            box = _fetch_with_retry(
                boxscoretraditionalv2.BoxScoreTraditionalV2,
                game_id=game_id,
                timeout=60
            )
            player_df = box.player_stats.get_data_frame()
            team_df = box.team_stats.get_data_frame()

            for _, p in player_df.iterrows():
                stat_id = f"{game_id}_{p['PLAYER_ID']}"
                conn.execute("""
                    INSERT OR REPLACE INTO player_game_stats
                        (stat_id, game_id, player_id, team_id, season,
                         min, pts, reb, ast, stl, blk, tov,
                         fgm, fga, fg_pct, fg3m, fg3a, fg3_pct,
                         ftm, fta, ft_pct, plus_minus, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,current_timestamp)
                """, [
                    stat_id, game_id, int(p["PLAYER_ID"]), int(p["TEAM_ID"]), season,
                    p.get("MIN"), _safe_int(p, "PTS"), _safe_int(p, "REB"),
                    _safe_int(p, "AST"), _safe_int(p, "STL"), _safe_int(p, "BLK"),
                    _safe_int(p, "TO"), _safe_int(p, "FGM"), _safe_int(p, "FGA"),
                    _safe_float(p, "FG_PCT"), _safe_int(p, "FG3M"), _safe_int(p, "FG3A"),
                    _safe_float(p, "FG3_PCT"), _safe_int(p, "FTM"), _safe_int(p, "FTA"),
                    _safe_float(p, "FT_PCT"), _safe_int(p, "PLUS_MINUS")
                ])
                player_records += 1

            for _, t in team_df.iterrows():
                stat_id = f"{game_id}_{t['TEAM_ID']}"
                # Determine home/away
                home_row = conn.execute(
                    "SELECT home_team_id FROM games WHERE game_id=?", [game_id]
                ).fetchone()
                is_home = home_row and int(t["TEAM_ID"]) == home_row[0]

                conn.execute("""
                    INSERT OR REPLACE INTO team_game_stats
                        (stat_id, game_id, team_id, season, is_home,
                         min, pts, reb, ast, stl, blk, tov,
                         fgm, fga, fg_pct, fg3m, fg3a, fg3_pct,
                         ftm, fta, ft_pct, plus_minus, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,current_timestamp)
                """, [
                    stat_id, game_id, int(t["TEAM_ID"]), season, is_home,
                    t.get("MIN"), _safe_int(t, "PTS"), _safe_int(t, "REB"),
                    _safe_int(t, "AST"), _safe_int(t, "STL"), _safe_int(t, "BLK"),
                    _safe_int(t, "TO"), _safe_int(t, "FGM"), _safe_int(t, "FGA"),
                    _safe_float(t, "FG_PCT"), _safe_int(t, "FG3M"), _safe_int(t, "FG3A"),
                    _safe_float(t, "FG3_PCT"), _safe_int(t, "FTM"), _safe_int(t, "FTA"),
                    _safe_float(t, "FT_PCT"), _safe_int(t, "PLUS_MINUS")
                ])
                team_records += 1

        except Exception as e:
            logger.warning(f"  Skipping box score for {game_id}: {e}")

    _log_ingestion(conn, "nba_api", f"box_scores:{season}", player_records + team_records, "success")
    logger.info(f"  → {player_records} player stat rows, {team_records} team stat rows.")

    if close:
        conn.close()
    return player_records + team_records


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _safe_int(row, col):
    val = row.get(col)
    return int(val) if pd.notna(val) else None


def _safe_float(row, col):
    val = row.get(col)
    return float(val) if pd.notna(val) else None
