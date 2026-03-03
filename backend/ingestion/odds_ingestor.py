"""
ingestion/odds_ingestor.py
Pulls NBA odds from The Odds API and writes them into DuckDB.
Supports: moneylines (h2h), spreads, totals.

Sign up for a free API key at https://the-odds-api.com
"""

import os
import uuid
import logging
import requests
from datetime import datetime
from typing import Optional

from backend.db.connection import get_connection

logger = logging.getLogger(__name__)

ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
SPORT = "basketball_nba"
REGIONS = "us"
MARKETS = "h2h,spreads,totals"
ODDS_FORMAT = "american"


# ---------------------------------------------------------------------------
# Core fetch
# ---------------------------------------------------------------------------

def fetch_odds(markets: str = MARKETS) -> list:
    """Fetch current NBA odds from The Odds API."""
    if not ODDS_API_KEY or ODDS_API_KEY == "your_odds_api_key_here":
        logger.warning("ODDS_API_KEY not set. Skipping odds ingestion.")
        return []

    url = f"{ODDS_API_BASE}/sports/{SPORT}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": REGIONS,
        "markets": markets,
        "oddsFormat": ODDS_FORMAT,
    }

    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()

    remaining = resp.headers.get("x-requests-remaining", "?")
    used = resp.headers.get("x-requests-used", "?")
    logger.info(f"  Odds API quota — used: {used}, remaining: {remaining}")

    return resp.json()


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------

def ingest_odds(conn=None) -> int:
    """Fetch odds and write to DuckDB, matching games by team names."""
    close = conn is None
    conn = conn or get_connection()

    try:
        games = fetch_odds()
    except Exception as e:
        logger.error(f"Failed to fetch odds: {e}")
        _log_ingestion(conn, "odds_api", "odds", 0, "error", str(e))
        if close:
            conn.close()
        return 0

    if not games:
        if close:
            conn.close()
        return 0

    records = 0
    for game in games:
        game_id = _match_game_id(conn, game)

        for bookmaker in game.get("bookmakers", []):
            bk_key = bookmaker["key"]
            for market in bookmaker.get("markets", []):
                market_key = market["key"]
                outcomes = {o["name"]: o for o in market.get("outcomes", [])}

                home_name = game.get("home_team", "")
                away_name = game.get("away_team", "")

                home_outcome = outcomes.get(home_name, {})
                away_outcome = outcomes.get(away_name, {})

                odds_id = f"{game['id']}_{bk_key}_{market_key}"

                conn.execute("""
                    INSERT OR REPLACE INTO odds VALUES (?,?,?,?,?,?,?,?,current_timestamp)
                """, [
                    odds_id,
                    game_id or game["id"],
                    bk_key,
                    market_key,
                    home_outcome.get("price"),
                    away_outcome.get("price"),
                    home_outcome.get("point"),
                    away_outcome.get("point"),
                ])
                records += 1

    _log_ingestion(conn, "odds_api", "odds", records, "success")
    logger.info(f"  → {records} odds records written.")

    if close:
        conn.close()
    return records


def _match_game_id(conn, game: dict) -> Optional[str]:
    """
    Try to find a matching game_id in our games table by team abbreviation
    and approximate date. Returns None if no match found.
    """
    try:
        home_team = game.get("home_team", "")
        away_team = game.get("away_team", "")
        game_date = game.get("commence_time", "")[:10]  # YYYY-MM-DD

        result = conn.execute("""
            SELECT g.game_id FROM games g
            JOIN teams ht ON g.home_team_id = ht.team_id
            JOIN teams at ON g.away_team_id = at.team_id
            WHERE CAST(g.game_date AS VARCHAR) = ?
            AND (ht.full_name ILIKE ? OR ht.nickname ILIKE ?)
            AND (at.full_name ILIKE ? OR at.nickname ILIKE ?)
            LIMIT 1
        """, [
            game_date,
            f"%{home_team.split()[-1]}%", f"%{home_team.split()[-1]}%",
            f"%{away_team.split()[-1]}%", f"%{away_team.split()[-1]}%",
        ]).fetchone()

        return result[0] if result else None
    except Exception:
        return None


def _log_ingestion(conn, source, entity, records, status, message=""):
    conn.execute("""
        INSERT OR REPLACE INTO ingestion_log VALUES (?, ?, ?, ?, ?, ?, current_timestamp)
    """, [str(uuid.uuid4()), source, entity, records, status, message])
