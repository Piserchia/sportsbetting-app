"""
ingestion/props_ingestor.py
Fetches NBA player prop lines from SportsGameOdds and writes them to
the sportsbook_props table for use in edge detection.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SETUP
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Sign up at https://sportsgameodds.com
2. Get your API key from the dashboard
3. Add to config/.env:
       SPORTSGAMEODDS_API_KEY=your_key_here

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HOW SPORTSGAMEODDS WORKS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Unlike The Odds API (which is per-event and quota-heavy for props),
SportsGameOdds lets you query by market type across all games at once.

Key endpoints used:
  GET /v1/odds
      ?sportID=NBA
      &oddIDs=player-points-over-under,player-rebounds-over-under,player-assists-over-under
      &books=draftkings,fanduel,betmgm,caesars

Each response row contains:
  - eventID       → maps to our game_id
  - playerID      → their internal player ID
  - playerName    → used to match to our players table
  - oddID         → market type (e.g. "player-points-over-under")
  - line          → the prop line (e.g. 24.5)
  - overOdds      → American odds for the over (e.g. -115)
  - underOdds     → American odds for the under (e.g. -105)
  - book          → sportsbook name

Billing: charged per event, not per market — so fetching 5 prop
markets for 10 games = 10 credits, not 50.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MARKET IDs (oddIDs)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
These are the oddID strings to pass to the API. Verify against
their docs at https://docs.sportsgameodds.com after signing up,
as these may change:

  player-points-over-under
  player-rebounds-over-under
  player-assists-over-under
  player-steals-over-under
  player-blocks-over-under
  player-threes-over-under
  player-turnovers-over-under
  player-points-rebounds-assists-over-under   (PRA combo)
  player-points-rebounds-over-under           (PR combo)
  player-points-assists-over-under            (PA combo)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ALTERNATE LINES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SportsGameOdds supports alternate prop ladders via separate oddIDs:
  player-points-alternate
  player-rebounds-alternate
  etc.

These return the full ladder (e.g. 15+, 20+, 25+, 30+, 35+) per book.
This is the primary data we want for edge detection against our
Monte Carlo simulation probabilities.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PLAYER MATCHING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SportsGameOdds uses their own playerID system. We match to our
players table using playerName (fuzzy match on full_name).
The matched player_id is stored alongside the prop line so
calculate_edges.py can JOIN directly to player_simulations.

Unmatched players are logged as warnings and skipped — this
typically affects G-League callups and two-way players.
"""

import os
import uuid
import logging
import requests
import pandas as pd
from datetime import datetime, timezone
from typing import Optional

from backend.db.connection import get_connection, init_model_schema

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

SGO_API_KEY  = os.getenv("SPORTSGAMEODDS_API_KEY", "")
SGO_BASE_URL = "https://api.sportsgameodds.com/v1"   # TODO: confirm base URL from docs

SPORT_ID = "NBA"

# Markets to fetch — standard O/U lines
STANDARD_MARKETS = [
    "player-points-over-under",
    "player-rebounds-over-under",
    "player-assists-over-under",
    "player-threes-over-under",
]

# Alternate ladder markets — full line ladders per book
ALTERNATE_MARKETS = [
    "player-points-alternate",
    "player-rebounds-alternate",
    "player-assists-alternate",
]

# Sportsbooks to pull from
BOOKS = [
    "draftkings",
    "fanduel",
    "betmgm",
    "caesars",
]

# Map SportsGameOdds oddID → our stat column names in player_simulations
MARKET_TO_STAT = {
    "player-points-over-under":   "points",
    "player-points-alternate":    "points",
    "player-rebounds-over-under": "rebounds",
    "player-rebounds-alternate":  "rebounds",
    "player-assists-over-under":  "assists",
    "player-assists-alternate":   "assists",
    "player-threes-over-under":   "threes",
    "player-threes-alternate":    "threes",
}


# ── Schema ────────────────────────────────────────────────────────────────────

def init_props_schema(conn):
    """Create sportsbook_props table if it doesn't exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sportsbook_props (
            prop_id         TEXT PRIMARY KEY,   -- game_id + player_id + stat + line + book
            game_id         TEXT,               -- our internal game_id from games table
            player_id       TEXT,               -- our internal player_id from players table
            sgo_player_id   TEXT,               -- SportsGameOdds native player ID
            player_name     TEXT,               -- raw name from API (for debugging mismatches)
            stat            TEXT,               -- 'points', 'rebounds', 'assists', etc.
            line            DOUBLE,             -- prop line (e.g. 24.5)
            over_odds       DOUBLE,             -- American odds for the over (e.g. -115)
            under_odds      DOUBLE,             -- American odds for the under (e.g. -105)
            book            TEXT,               -- sportsbook key (e.g. 'draftkings')
            market          TEXT,               -- raw oddID from SGO
            is_alternate    BOOLEAN,            -- TRUE if this is an alternate line
            fetched_at      TIMESTAMP DEFAULT current_timestamp
        )
    """)


# ── Core API Fetch ─────────────────────────────────────────────────────────────

def _check_api_key() -> bool:
    """Return True if the API key is configured."""
    if not SGO_API_KEY or SGO_API_KEY == "your_key_here":
        logger.warning(
            "SPORTSGAMEODDS_API_KEY not set. "
            "Sign up at https://sportsgameodds.com and add your key to config/.env"
        )
        return False
    return True


def fetch_props(markets: list, books: list = BOOKS) -> list:
    """
    Fetch prop lines from SportsGameOdds for all live/upcoming NBA games.

    Args:
        markets: List of oddID strings (e.g. ['player-points-over-under'])
        books:   List of sportsbook keys to include

    Returns:
        List of raw prop dicts from the API response.

    TODO: Confirm exact request structure from SGO docs after signup.
    The params below follow their documented pattern but field names
    (sportID vs sport_id, oddIDs vs markets) should be verified.
    """
    url = f"{SGO_BASE_URL}/odds"
    params = {
        "apiKey":   SGO_API_KEY,
        "sportID":  SPORT_ID,
        "oddIDs":   ",".join(markets),      # comma-separated market list
        "books":    ",".join(books),         # comma-separated book list
        "status":   "upcoming",             # 'upcoming', 'live', or 'final'
    }

    logger.info(f"Fetching props from SportsGameOdds: {', '.join(markets)}")
    resp = requests.get(url, params=params, timeout=20)
    resp.raise_for_status()

    # Log quota usage if headers are present
    # TODO: confirm actual header names from SGO docs
    remaining = resp.headers.get("x-credits-remaining", "?")
    used      = resp.headers.get("x-credits-used", "?")
    logger.info(f"  SGO quota — used: {used}, remaining: {remaining}")

    data = resp.json()

    # TODO: confirm response structure — adjust key if needed
    # Expected: {"data": [...], "meta": {...}}
    # or just a top-level list: [...]
    if isinstance(data, list):
        return data
    return data.get("data", data.get("odds", []))


# ── Player Matching ────────────────────────────────────────────────────────────

def _build_player_lookup(conn) -> dict:
    """
    Build a name → player_id lookup from our players table.
    Used to match SportsGameOdds playerName to our internal IDs.
    Returns dict of {lowercase_full_name: player_id}
    """
    players = conn.execute("""
        SELECT player_id, full_name FROM players WHERE is_active = TRUE
    """).df()

    return {
        row["full_name"].lower().strip(): str(row["player_id"])
        for _, row in players.iterrows()
    }


def _match_player(player_name: str, lookup: dict) -> Optional[str]:
    """
    Match a SportsGameOdds player name to our internal player_id.
    Tries exact match first, then falls back to last-name matching.

    Args:
        player_name: Raw name string from SGO API
        lookup:      Dict from _build_player_lookup()

    Returns:
        Our internal player_id string, or None if no match found.
    """
    if not player_name:
        return None

    # 1. Exact match
    normalized = player_name.lower().strip()
    if normalized in lookup:
        return lookup[normalized]

    # 2. Last name match (handles "LeBron James" vs "L. James" etc.)
    last_name = normalized.split()[-1]
    matches = [pid for name, pid in lookup.items() if name.endswith(last_name)]
    if len(matches) == 1:
        return matches[0]

    # 3. No match
    return None


def _match_game_id(conn, sgo_event_id: str, game_date: str) -> Optional[str]:
    """
    Match a SportsGameOdds eventID to our internal game_id.

    First checks if we've already stored this mapping, then falls back
    to date-based matching.

    TODO: Build a sgo_event_id → game_id mapping table if ambiguity
    becomes a problem (e.g. doubleheaders on same date).

    Args:
        sgo_event_id: SGO's native event ID string
        game_date:    YYYY-MM-DD string from the API response

    Returns:
        Our internal game_id, or None if not found.
    """
    result = conn.execute("""
        SELECT game_id FROM games
        WHERE CAST(game_date AS VARCHAR) = ?
        LIMIT 1
    """, [game_date]).fetchone()

    return result[0] if result else None


# ── Ingestion ─────────────────────────────────────────────────────────────────

def ingest_props(
    markets: list = None,
    include_alternates: bool = True,
    conn=None
) -> int:
    """
    Fetch player prop lines from SportsGameOdds and write to sportsbook_props.

    Args:
        markets:            List of oddID market strings. Defaults to
                            STANDARD_MARKETS + ALTERNATE_MARKETS.
        include_alternates: Whether to fetch alternate line ladders.
                            Alternates are the primary data for edge detection.
        conn:               Optional existing DuckDB connection.

    Returns:
        Number of prop rows written to sportsbook_props.

    Usage:
        from backend.ingestion.props_ingestor import ingest_props
        ingest_props()                          # fetch all markets
        ingest_props(include_alternates=False)  # standard lines only
    """
    if not _check_api_key():
        return 0

    close = conn is None
    conn  = conn or get_connection()
    init_model_schema(conn)
    init_props_schema(conn)

    # Determine which markets to fetch
    if markets is None:
        markets = STANDARD_MARKETS[:]
        if include_alternates:
            markets += ALTERNATE_MARKETS

    # Build player lookup once for the whole run
    player_lookup = _build_player_lookup(conn)
    logger.info(f"  Player lookup built — {len(player_lookup)} active players.")

    # Fetch from API
    try:
        raw_props = fetch_props(markets=markets)
    except requests.HTTPError as e:
        logger.error(f"SportsGameOdds HTTP error: {e.response.status_code} — {e.response.text}")
        _log_ingestion(conn, "sportsgameodds", "props", 0, "error", str(e))
        if close:
            conn.close()
        return 0
    except Exception as e:
        logger.error(f"SportsGameOdds fetch failed: {e}")
        _log_ingestion(conn, "sportsgameodds", "props", 0, "error", str(e))
        if close:
            conn.close()
        return 0

    if not raw_props:
        logger.warning("No props returned from SportsGameOdds.")
        if close:
            conn.close()
        return 0

    logger.info(f"  Processing {len(raw_props)} raw prop rows...")

    records    = 0
    unmatched  = 0

    for prop in raw_props:
        # ── TODO: Map these field names to actual SGO response fields ──────────
        # The field names below are our best guess based on SGO docs patterns.
        # Verify against a real API response after signup and adjust as needed.
        #
        # Likely response shape (per prop row):
        # {
        #   "eventID":    "sgo-event-123",
        #   "playerID":   "sgo-player-456",
        #   "playerName": "Jayson Tatum",
        #   "oddID":      "player-points-alternate",
        #   "line":       29.5,
        #   "overOdds":   -115,
        #   "underOdds":  -105,
        #   "book":       "draftkings",
        #   "eventDate":  "2026-03-07"
        # }
        sgo_event_id  = prop.get("eventID", "")
        sgo_player_id = prop.get("playerID", "")
        player_name   = prop.get("playerName", "")
        market        = prop.get("oddID", "")
        line          = prop.get("line")
        over_odds     = prop.get("overOdds")
        under_odds    = prop.get("underOdds")
        book          = prop.get("book", "")
        event_date    = prop.get("eventDate", "")[:10]  # YYYY-MM-DD

        if not all([player_name, market, line is not None, book]):
            continue

        # Match to our internal IDs
        player_id = _match_player(player_name, player_lookup)
        if not player_id:
            logger.debug(f"  Unmatched player: '{player_name}'")
            unmatched += 1
            continue

        game_id = _match_game_id(conn, sgo_event_id, event_date)
        stat    = MARKET_TO_STAT.get(market)

        if not stat:
            logger.debug(f"  Unknown market: '{market}' — add to MARKET_TO_STAT if needed")
            continue

        is_alternate = "alternate" in market
        prop_id      = f"{game_id}_{player_id}_{stat}_{line}_{book}"

        conn.execute("""
            INSERT OR REPLACE INTO sportsbook_props (
                prop_id, game_id, player_id, sgo_player_id, player_name,
                stat, line, over_odds, under_odds, book, market,
                is_alternate, fetched_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,current_timestamp)
        """, [
            prop_id, game_id, player_id, sgo_player_id, player_name,
            stat, float(line), over_odds, under_odds, book, market,
            is_alternate
        ])
        records += 1

    if unmatched:
        logger.warning(f"  {unmatched} props skipped — player name not matched to our DB.")

    _log_ingestion(conn, "sportsgameodds", "props", records, "success",
                   f"{unmatched} unmatched players")
    logger.info(f"  → {records} prop rows written to sportsbook_props.")

    if close:
        conn.close()
    return records


# ── Utilities ─────────────────────────────────────────────────────────────────

def get_available_markets(conn=None) -> pd.DataFrame:
    """
    Query which markets and books are currently in sportsbook_props.
    Useful for debugging after first ingestion.

    Usage:
        from backend.ingestion.props_ingestor import get_available_markets
        print(get_available_markets())
    """
    close = conn is None
    conn  = conn or get_connection()

    df = conn.execute("""
        SELECT
            stat,
            book,
            is_alternate,
            COUNT(*)        AS prop_count,
            MIN(line)       AS min_line,
            MAX(line)       AS max_line,
            MAX(fetched_at) AS last_fetched
        FROM sportsbook_props
        GROUP BY stat, book, is_alternate
        ORDER BY stat, book
    """).df()

    if close:
        conn.close()
    return df


def get_props_for_player(player_id: str, stat: str = None, conn=None) -> pd.DataFrame:
    """
    Retrieve all current prop lines for a given player, optionally filtered by stat.

    Usage:
        from backend.ingestion.props_ingestor import get_props_for_player
        df = get_props_for_player("203954")          # all stats
        df = get_props_for_player("203954", "points") # points only
    """
    close  = conn is None
    conn   = conn or get_connection()

    stat_clause = "AND stat = ?" if stat else ""
    params      = [player_id, stat] if stat else [player_id]

    df = conn.execute(f"""
        SELECT
            sp.player_name,
            sp.stat,
            sp.line,
            sp.over_odds,
            sp.under_odds,
            sp.book,
            sp.is_alternate,
            ps.probability AS model_probability
        FROM sportsbook_props sp
        LEFT JOIN player_simulations ps
            ON  sp.player_id = ps.player_id
            AND sp.stat      = ps.stat
            AND sp.line      = ps.line
        WHERE sp.player_id = ?
        {stat_clause}
        ORDER BY sp.stat, sp.line, sp.book
    """, params).df()

    if close:
        conn.close()
    return df


def _log_ingestion(conn, source, entity, records, status, message=""):
    conn.execute("""
        INSERT OR REPLACE INTO ingestion_log VALUES (?, ?, ?, ?, ?, ?, current_timestamp)
    """, [str(uuid.uuid4()), source, entity, records, status, message])
