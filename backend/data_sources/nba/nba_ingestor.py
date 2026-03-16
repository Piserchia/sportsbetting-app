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
    boxscoretraditionalv3,
    teamgamelog,
    scheduleleaguev2,
)

from backend.database.connection import get_connection

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
# Full schedule (past + upcoming) via ScheduleLeagueV2
# ---------------------------------------------------------------------------

def ingest_schedule(seasons: Optional[list] = None, conn=None) -> int:
    """
    Upserts the full season schedule (past AND upcoming games) using
    ScheduleLeagueV2. Complements ingest_games() which only returns
    completed games via LeagueGameLog.

    Sets status to:
      'Final'    — gameStatus == 3
      'Live'     — gameStatus == 2
      'Upcoming' — gameStatus == 1
    """
    close = conn is None
    conn = conn or get_connection()
    seasons = seasons or NBA_SEASONS
    total = 0

    # Build team_id lookup from teams table
    team_rows = conn.execute("SELECT team_id, abbreviation FROM teams").fetchall()
    abbr_to_id = {row[1]: row[0] for row in team_rows}

    for season in seasons:
        logger.info(f"Ingesting full schedule for season {season}...")
        try:
            _sleep()
            sched = _fetch_with_retry(
                scheduleleaguev2.ScheduleLeagueV2,
                season=season,
                league_id="00",
            )
            df = sched.get_data_frames()[0]

            # Filter to regular season only (gameId prefix 002 = regular season)
            df = df[df["gameId"].astype(str).str.startswith("002")]

            STATUS_MAP = {1: "Upcoming", 2: "Live", 3: "Final"}
            records = 0

            for _, row in df.iterrows():
                game_id      = str(row["gameId"])
                raw_date     = str(row["gameDate"])  # "MM/DD/YYYY HH:MM:SS"
                game_date    = pd.to_datetime(raw_date).date()
                game_status  = int(row.get("gameStatus", 1))
                status_str   = STATUS_MAP.get(game_status, "Upcoming")

                home_abbr    = str(row.get("homeTeam_teamTricode", "")).strip()
                away_abbr    = str(row.get("awayTeam_teamTricode", "")).strip()
                home_team_id = int(row.get("homeTeam_teamId", 0)) or abbr_to_id.get(home_abbr)
                away_team_id = int(row.get("awayTeam_teamId", 0)) or abbr_to_id.get(away_abbr)

                # Extract game time in ET from the datetime string
                game_time_et = None
                try:
                    game_dt = pd.to_datetime(raw_date)
                    if game_dt.hour != 0 or game_dt.minute != 0:
                        game_time_et = game_dt.strftime("%-I:%M %p ET")
                except Exception:
                    pass

                home_score_raw = row.get("homeTeam_score")
                away_score_raw = row.get("awayTeam_score")
                home_score = int(home_score_raw) if pd.notna(home_score_raw) and home_score_raw else None
                away_score = int(away_score_raw) if pd.notna(away_score_raw) and away_score_raw else None

                conn.execute("""
                    INSERT INTO games
                        (game_id, season, game_date, home_team_id, away_team_id,
                         home_team_abbr, away_team_abbr, home_score, away_score,
                         status, game_time_et, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, current_timestamp)
                    ON CONFLICT (game_id) DO UPDATE SET
                        status       = excluded.status,
                        home_score   = excluded.home_score,
                        away_score   = excluded.away_score,
                        game_time_et = COALESCE(excluded.game_time_et, games.game_time_et),
                        updated_at   = now()
                """, [
                    game_id, season, game_date,
                    home_team_id, away_team_id,
                    home_abbr, away_abbr,
                    home_score, away_score,
                    status_str, game_time_et,
                ])
                records += 1

            _log_ingestion(conn, "nba_api", f"schedule:{season}", records, "success")
            logger.info(f"  → {records} schedule rows upserted for {season}.")
            total += records

        except Exception as e:
            logger.error(f"  Error ingesting schedule for {season}: {e}")
            _log_ingestion(conn, "nba_api", f"schedule:{season}", 0, "error", str(e))

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

    Only ingests box scores for games that are:
      - status = 'Final'
      - game_date < today  (prevents ingesting live or same-day games)

    Args:
        force: If True, re-fetches ALL eligible Final games ignoring what's
               already in player_game_stats. Use when box scores are missing
               despite the game appearing as already ingested.
    """
    close = conn is None
    conn = conn or get_connection()
    today = date.today()

    if force:
        logger.info(f"  FORCE mode — fetching ALL Final games for {season} regardless of existing data.")
        games_df = conn.execute("""
            SELECT game_id, game_date FROM games
            WHERE season = ? AND status = 'Final' AND game_date < ?
        """, [season, today]).df()
    else:
        games_df = conn.execute("""
            SELECT game_id, game_date FROM games
            WHERE season = ? AND status = 'Final' AND game_date < ?
            AND game_id NOT IN (
                SELECT DISTINCT game_id FROM player_game_stats
                WHERE season = ?
            )
        """, [season, today, season]).df()

    # Log counts of games skipped at the query level for visibility
    skipped_today = conn.execute("""
        SELECT COUNT(*) FROM games
        WHERE season = ? AND status = 'Final' AND game_date >= ?
    """, [season, today]).fetchone()[0]
    skipped_not_final = conn.execute("""
        SELECT COUNT(*) FROM games
        WHERE season = ? AND status != 'Final'
    """, [season]).fetchone()[0]
    if not force:
        already_ingested = conn.execute("""
            SELECT COUNT(DISTINCT game_id) FROM player_game_stats WHERE season = ?
        """, [season]).fetchone()[0]
    else:
        already_ingested = 0

    if skipped_today > 0:
        logger.info(f"Skipping {skipped_today} game(s) for {season}: reason=game_today (game_date >= {today})")
    if skipped_not_final > 0:
        logger.info(f"Skipping {skipped_not_final} game(s) for {season}: reason=game_not_final")
    if already_ingested > 0 and not force:
        logger.info(f"Skipping {already_ingested} game(s) for {season}: reason=already_ingested")

    if limit:
        games_df = games_df.head(limit)

    total_games   = len(games_df)
    logger.info(f"  Games selected to fetch: {games_df['game_id'].tolist()[:10]} ...")  # show first 10
    player_records = 0
    team_records   = 0
    skipped        = 0
    errors         = []

    if total_games == 0:
        logger.info(f"  No new games to fetch for {season} — already up to date.")
        if close:
            conn.close()
        return 0

    secs_per_game = NBA_API_DELAY + 1.0   # conservative estimate incl. response time
    eta_total_min = (total_games * secs_per_game) / 60
    logger.info(
        f"Fetching box scores for {total_games} games in {season}  "
        f"(~{eta_total_min:.0f} min at {secs_per_game:.0f}s/game)"
    )

    t_start = time.time()
    LOG_EVERY = 10   # print a progress line every N games

    for i, (_, row) in enumerate(games_df.iterrows(), start=1):
        game_id = row["game_id"]
        logger.info(f"  [{i}/{total_games}] Fetching game {game_id}...")
        try:
            _sleep()
            box = _fetch_with_retry(
                boxscoretraditionalv3.BoxScoreTraditionalV3,
                game_id=game_id,
                timeout=60
            )
            player_df = box.data_sets[0].get_data_frame()  # Dataset 0 = player rows
            team_df   = box.data_sets[2].get_data_frame()  # Dataset 2 = team totals
            logger.info(f"  [{i}] game {game_id}: {len(player_df)} player rows, {len(team_df)} team rows")

            for _, p in player_df.iterrows():
                stat_id = f"{game_id}_{p['personId']}"
                conn.execute("""
                    INSERT OR REPLACE INTO player_game_stats
                        (stat_id, game_id, player_id, team_id, season,
                         min, pts, reb, ast, stl, blk, tov,
                         fgm, fga, fg_pct, fg3m, fg3a, fg3_pct,
                         ftm, fta, ft_pct, plus_minus, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,current_timestamp)
                """, [
                    stat_id, game_id, int(p["personId"]), int(p["teamId"]), season,
                    str(p.get("minutes", "0:00")),
                    _safe_int(p, "points"), _safe_int(p, "reboundsTotal"),
                    _safe_int(p, "assists"), _safe_int(p, "steals"),
                    _safe_int(p, "blocks"), _safe_int(p, "turnovers"),
                    _safe_int(p, "fieldGoalsMade"), _safe_int(p, "fieldGoalsAttempted"),
                    _safe_float(p, "fieldGoalsPercentage"),
                    _safe_int(p, "threePointersMade"), _safe_int(p, "threePointersAttempted"),
                    _safe_float(p, "threePointersPercentage"),
                    _safe_int(p, "freeThrowsMade"), _safe_int(p, "freeThrowsAttempted"),
                    _safe_float(p, "freeThrowsPercentage"),
                    _safe_float(p, "plusMinusPoints"),
                ])
                player_records += 1

            for _, t in team_df.iterrows():
                stat_id = f"{game_id}_{t['teamId']}"
                home_row = conn.execute(
                    "SELECT home_team_id FROM games WHERE game_id=?", [game_id]
                ).fetchone()
                is_home = home_row and int(t["teamId"]) == home_row[0]

                conn.execute("""
                    INSERT OR REPLACE INTO team_game_stats
                        (stat_id, game_id, team_id, season, is_home,
                         min, pts, reb, ast, stl, blk, tov,
                         fgm, fga, fg_pct, fg3m, fg3a, fg3_pct,
                         ftm, fta, ft_pct, plus_minus, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,current_timestamp)
                """, [
                    stat_id, game_id, int(t["teamId"]), season, is_home,
                    str(t.get("minutes", "240:00")),
                    _safe_int(t, "points"), _safe_int(t, "reboundsTotal"),
                    _safe_int(t, "assists"), _safe_int(t, "steals"),
                    _safe_int(t, "blocks"), _safe_int(t, "turnovers"),
                    _safe_int(t, "fieldGoalsMade"), _safe_int(t, "fieldGoalsAttempted"),
                    _safe_float(t, "fieldGoalsPercentage"),
                    _safe_int(t, "threePointersMade"), _safe_int(t, "threePointersAttempted"),
                    _safe_float(t, "threePointersPercentage"),
                    _safe_int(t, "freeThrowsMade"), _safe_int(t, "freeThrowsAttempted"),
                    _safe_float(t, "freeThrowsPercentage"),
                    _safe_float(t, "plusMinusPoints"),
                ])
                team_records += 1

        except Exception as e:
            skipped += 1
            errors.append(game_id)
            logger.warning(f"  [{i}/{total_games}] SKIP {game_id}: {e}")
            continue

        # ── Progress logging ──────────────────────────────────────────────
        if i % LOG_EVERY == 0 or i == total_games:
            elapsed      = time.time() - t_start
            avg_per_game = elapsed / i
            remaining    = total_games - i
            eta_secs     = remaining * avg_per_game
            pct          = i / total_games * 100

            if eta_secs >= 3600:
                eta_str = f"{eta_secs/3600:.1f}h"
            elif eta_secs >= 60:
                eta_str = f"{eta_secs/60:.0f}m"
            else:
                eta_str = f"{eta_secs:.0f}s"

            elapsed_str = f"{elapsed/60:.1f}m" if elapsed >= 60 else f"{elapsed:.0f}s"

            logger.info(
                f"  [{i:>{len(str(total_games))}}/{total_games}]  "
                f"{pct:5.1f}%  |  "
                f"elapsed: {elapsed_str}  |  "
                f"eta: {eta_str}  |  "
                f"speed: {avg_per_game:.1f}s/game  |  "
                f"skipped: {skipped}"
            )

    elapsed_total = time.time() - t_start
    logger.info(
        f"  ✓ Done — {i} games in {elapsed_total/60:.1f}m  |  "
        f"{player_records} player rows  |  {team_records} team rows  |  {skipped} skipped"
    )
    if errors:
        logger.warning(f"  Failed game IDs: {', '.join(errors[:20])}"
                       + (" ..." if len(errors) > 20 else ""))

    _log_ingestion(conn, "nba_api", f"box_scores:{season}", player_records + team_records, "success")
    logger.info(f"  → {player_records} player stat rows, {team_records} team stat rows.")

    # Safety check: verify no non-Final game stats were written
    non_final_count = conn.execute("""
        SELECT COUNT(*)
        FROM player_game_stats p
        JOIN games g ON p.game_id = g.game_id
        WHERE g.status != 'Final'
    """).fetchone()[0]
    if non_final_count > 0:
        logger.warning(
            f"  DATA INTEGRITY WARNING: {non_final_count} player_game_stats row(s) exist for non-Final games. "
            "These may corrupt model training data."
        )

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
