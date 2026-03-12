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
FREE-TIER OPTIMIZATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Only fetches props for today's games (billing is per-event)
- Default books: draftkings, fanduel, betmgm (caesars optional)
- Only fetches stats we model (pts/reb/ast/stl/blk + alternates)
- 60-min cooldown between API calls (configurable)
- Dev mode: draftkings only, once per day

Env vars:
    PROPS_BOOKS=draftkings,fanduel,betmgm
    PROPS_COOLDOWN_MINUTES=60
    PROPS_DEV_MODE=false
"""

import os
import re
import uuid
import logging
import requests
import pandas as pd
from datetime import datetime, timezone
from typing import Optional
from hashlib import md5

from backend.db.connection import get_connection, init_model_schema

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

SGO_API_KEY  = os.getenv("SPORTSGAMEODDS_API_KEY", "")
SGO_BASE_URL = "https://api.sportsgameodds.com/v1"

SPORT_ID = "NBA"

# ── Free-tier settings ────────────────────────────────────────────────────────

PROPS_DEV_MODE = os.getenv("PROPS_DEV_MODE", "false").lower() == "true"
PROPS_COOLDOWN_MINUTES = int(os.getenv("PROPS_COOLDOWN_MINUTES", "1440" if PROPS_DEV_MODE else "60"))

# Sportsbooks — 3 default, caesars opt-in
DEFAULT_BOOKS = ["draftkings", "fanduel", "betmgm"]
if PROPS_DEV_MODE:
    BOOKS = ["draftkings"]
    logger.warning("PROPS_DEV_MODE active — draftkings only, 24hr cooldown")
else:
    BOOKS = [b.strip() for b in os.getenv("PROPS_BOOKS", ",".join(DEFAULT_BOOKS)).split(",")]

# Markets — only stats we actually model (no threes/turnovers)
STANDARD_MARKETS = [
    "player-points-over-under",
    "player-rebounds-over-under",
    "player-assists-over-under",
    "player-steals-over-under",
    "player-blocks-over-under",
]

ALTERNATE_MARKETS = [
    "player-points-alternate",
    "player-rebounds-alternate",
    "player-assists-alternate",
]

# Map SportsGameOdds oddID → our stat column names in player_simulations
MARKET_TO_STAT = {
    "player-points-over-under":   "points",
    "player-points-alternate":    "points",
    "player-rebounds-over-under": "rebounds",
    "player-rebounds-alternate":  "rebounds",
    "player-assists-over-under":  "assists",
    "player-assists-alternate":   "assists",
    "player-steals-over-under":   "steals",
    "player-blocks-over-under":   "blocks",
}


# ── Schema ────────────────────────────────────────────────────────────────────

def init_props_schema(conn):
    """Create sportsbook_props table if it doesn't exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sportsbook_props (
            prop_id         TEXT PRIMARY KEY,   -- game_id + player_id + stat + line + book
            game_id         TEXT,
            player_id       TEXT,
            sgo_player_id   TEXT,
            player_name     TEXT,
            stat            TEXT,
            line            DOUBLE,
            over_odds       DOUBLE,
            under_odds      DOUBLE,
            book            TEXT,
            market          TEXT,
            is_alternate    BOOLEAN,
            fetched_at      TIMESTAMP DEFAULT current_timestamp
        )
    """)


# ── Cooldown Guard ────────────────────────────────────────────────────────────

def _check_cooldown(conn) -> bool:
    """Return True if we should skip fetching (within cooldown window)."""
    try:
        row = conn.execute("""
            SELECT ran_at FROM ingestion_log
            WHERE source = 'sportsgameodds' AND entity = 'props' AND status = 'success'
            ORDER BY ran_at DESC LIMIT 1
        """).fetchone()
    except Exception:
        return False

    if not row:
        return False

    last_fetch = row[0]
    if isinstance(last_fetch, str):
        last_fetch = datetime.fromisoformat(last_fetch.replace("Z", "+00:00"))
    if last_fetch.tzinfo is None:
        last_fetch = last_fetch.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    elapsed_min = (now - last_fetch).total_seconds() / 60.0

    if elapsed_min < PROPS_COOLDOWN_MINUTES:
        logger.info(
            f"Props fetched {elapsed_min:.0f}m ago, skipping "
            f"(cooldown={PROPS_COOLDOWN_MINUTES}m)"
        )
        return True
    return False


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


def fetch_props(markets: list, books: list = None, event_ids: list = None) -> list:
    """
    Fetch prop lines from SportsGameOdds.

    Args:
        markets:   List of oddID strings
        books:     List of sportsbook keys
        event_ids: Optional list of eventIDs to filter (today's games)

    Returns:
        List of raw prop dicts from the API response.
    """
    if books is None:
        books = BOOKS

    url = f"{SGO_BASE_URL}/odds"
    params = {
        "apiKey":   SGO_API_KEY,
        "sportID":  SPORT_ID,
        "oddIDs":   ",".join(markets),
        "books":    ",".join(books),
        "status":   "upcoming",
    }
    if event_ids:
        params["eventIDs"] = ",".join(str(eid) for eid in event_ids)

    logger.info(f"Fetching props from SportsGameOdds: {', '.join(markets)}")
    logger.info(f"  Books: {', '.join(books)} | Events: {len(event_ids) if event_ids else 'all'}")
    resp = requests.get(url, params=params, timeout=20)
    resp.raise_for_status()

    remaining = resp.headers.get("x-credits-remaining", "?")
    used      = resp.headers.get("x-credits-used", "?")
    logger.info(f"  SGO quota — used: {used}, remaining: {remaining}")

    data = resp.json()
    if isinstance(data, list):
        return data
    return data.get("data", data.get("odds", []))


# ── Player Matching ────────────────────────────────────────────────────────────

_SUFFIX_RE = re.compile(r'\s+(jr\.?|sr\.?|ii|iii|iv|v)$', re.IGNORECASE)


def _build_player_lookup(conn) -> dict:
    """
    Build a name → player_id lookup from our players table.
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
    Three-tier matching:
      1. Exact lowercase match
      2. Strip suffixes (Jr., Sr., III, etc.) and retry
      3. Last-name fallback (unique match only)
    """
    if not player_name:
        return None

    # 1. Exact match
    normalized = player_name.lower().strip()
    if normalized in lookup:
        return lookup[normalized]

    # 2. Strip suffix and retry
    stripped = _SUFFIX_RE.sub("", normalized).strip()
    if stripped != normalized and stripped in lookup:
        return lookup[stripped]

    # Also try stripping suffix from lookup names
    for name, pid in lookup.items():
        if _SUFFIX_RE.sub("", name).strip() == stripped:
            return pid

    # 3. Last name match (only if unique)
    last_name = normalized.split()[-1]
    matches = [pid for name, pid in lookup.items() if name.endswith(last_name)]
    if len(matches) == 1:
        return matches[0]

    return None


def _get_today_game_ids(conn) -> list:
    """Get game_ids for today's games."""
    rows = conn.execute("""
        SELECT game_id FROM games WHERE game_date = CURRENT_DATE
    """).fetchall()
    game_ids = [r[0] for r in rows]
    logger.info(f"  Today's games: {len(game_ids)}")
    return game_ids


def _match_game_id(conn, sgo_event_id: str, event_date: str,
                   today_game_ids: list = None) -> Optional[str]:
    """
    Match a SportsGameOdds eventID to our internal game_id.
    If today_game_ids provided, filter to only those games.
    """
    if today_game_ids:
        # Match by date within today's games
        placeholders = ",".join(["?"] * len(today_game_ids))
        result = conn.execute(f"""
            SELECT game_id FROM games
            WHERE game_id IN ({placeholders})
            AND CAST(game_date AS VARCHAR) = ?
            LIMIT 1
        """, today_game_ids + [event_date]).fetchone()
    else:
        result = conn.execute("""
            SELECT game_id FROM games
            WHERE CAST(game_date AS VARCHAR) = ?
            LIMIT 1
        """, [event_date]).fetchone()

    return result[0] if result else None


# ── Snapshot Rebuild ──────────────────────────────────────────────────────────

def _rebuild_sportsbook_props(conn, today_game_ids: list):
    """
    Rebuild sportsbook_props for today's games from prop_line_history,
    keeping only the latest snapshot per (game, player, stat, line, book).
    """
    if not today_game_ids:
        return

    placeholders = ",".join(["?"] * len(today_game_ids))

    # Delete today's rows
    conn.execute(f"""
        DELETE FROM sportsbook_props
        WHERE game_id IN ({placeholders})
    """, today_game_ids)

    # Insert latest snapshot from history
    conn.execute(f"""
        INSERT INTO sportsbook_props (
            prop_id, game_id, player_id, sgo_player_id, player_name,
            stat, line, over_odds, under_odds, book, market, is_alternate, fetched_at
        )
        SELECT
            game_id || '_' || player_id || '_' || stat || '_' || CAST(line AS VARCHAR) || '_' || book AS prop_id,
            game_id, player_id, '' AS sgo_player_id, player_name,
            stat, line, over_odds, under_odds, book,
            '' AS market,
            FALSE AS is_alternate,
            fetched_at
        FROM (
            SELECT *,
                ROW_NUMBER() OVER (
                    PARTITION BY game_id, player_id, stat, line, book
                    ORDER BY fetched_at DESC
                ) AS rn
            FROM prop_line_history
            WHERE game_id IN ({placeholders})
        ) ranked
        WHERE rn = 1
    """, today_game_ids)

    count = conn.execute(f"""
        SELECT COUNT(*) FROM sportsbook_props WHERE game_id IN ({placeholders})
    """, today_game_ids).fetchone()[0]
    logger.info(f"  → sportsbook_props rebuilt: {count} latest rows for today's games")


# ── Ingestion ─────────────────────────────────────────────────────────────────

def ingest_props(
    markets: list = None,
    include_alternates: bool = True,
    conn=None
) -> int:
    """
    Fetch player prop lines from SportsGameOdds and write to sportsbook_props.
    Optimized for free-tier: today's games only, 3 books, cooldown guard.

    Returns:
        Number of prop rows written to prop_line_history.
    """
    if not _check_api_key():
        return 0

    close = conn is None
    conn  = conn or get_connection()
    init_model_schema(conn)
    init_props_schema(conn)

    # Cooldown guard
    if _check_cooldown(conn):
        _log_ingestion(conn, "sportsgameodds", "props", 0, "skipped",
                       f"Within {PROPS_COOLDOWN_MINUTES}m cooldown")
        if close:
            conn.close()
        return 0

    # Today's games only
    today_game_ids = _get_today_game_ids(conn)
    if not today_game_ids:
        logger.info("No games today — skipping props fetch.")
        _log_ingestion(conn, "sportsgameodds", "props", 0, "skipped", "No games today")
        if close:
            conn.close()
        return 0

    # Determine markets
    if markets is None:
        markets = STANDARD_MARKETS[:]
        if include_alternates:
            markets += ALTERNATE_MARKETS

    # Build player lookup
    player_lookup = _build_player_lookup(conn)
    logger.info(f"  Player lookup built — {len(player_lookup)} active players.")

    # Fetch from API
    try:
        raw_props = fetch_props(markets=markets, event_ids=today_game_ids)
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
        _log_ingestion(conn, "sportsgameodds", "props", 0, "success",
                       f"0 props returned | {len(today_game_ids)} games | books: {','.join(BOOKS)}")
        if close:
            conn.close()
        return 0

    logger.info(f"  Processing {len(raw_props)} raw prop rows...")

    records   = 0
    unmatched = 0

    for prop in raw_props:
        sgo_event_id  = prop.get("eventID", "")
        sgo_player_id = prop.get("playerID", "")
        player_name   = prop.get("playerName", "")
        market        = prop.get("oddID", "")
        line          = prop.get("line")
        over_odds     = prop.get("overOdds")
        under_odds    = prop.get("underOdds")
        book          = prop.get("book", "")
        event_date    = prop.get("eventDate", "")[:10]

        if not all([player_name, market, line is not None, book]):
            continue

        # Match to our internal IDs
        player_id = _match_player(player_name, player_lookup)
        if not player_id:
            logger.debug(f"  Unmatched player: '{player_name}'")
            unmatched += 1
            continue

        game_id = _match_game_id(conn, sgo_event_id, event_date, today_game_ids)
        stat    = MARKET_TO_STAT.get(market)

        if not stat:
            logger.debug(f"  Unknown market: '{market}'")
            continue

        if not game_id:
            continue

        is_alternate = "alternate" in market

        # Append to prop_line_history (append-only)
        now = datetime.now(timezone.utc).isoformat()
        history_id = md5(f"{now}_{book}_{player_id}_{stat}_{line}".encode()).hexdigest()
        try:
            conn.execute("""
                INSERT INTO prop_line_history (
                    history_id, fetched_at, book, player_id, player_name,
                    game_id, stat, line, over_odds, under_odds
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """, [
                history_id, now, book, player_id, player_name,
                game_id, stat, float(line), over_odds, under_odds
            ])
            records += 1
        except Exception as e:
            logger.debug(f"  History insert error: {e}")

    # Rebuild sportsbook_props from latest history snapshots
    _rebuild_sportsbook_props(conn, today_game_ids)

    if unmatched:
        logger.warning(f"  {unmatched} props skipped — player name not matched.")

    msg = (f"{records} rows appended to history | "
           f"{len(today_game_ids)} games | "
           f"books: {','.join(BOOKS)} | "
           f"{unmatched} unmatched")
    _log_ingestion(conn, "sportsgameodds", "props", records, "success", msg)
    logger.info(f"  → {records} prop rows written to prop_line_history.")

    if close:
        conn.close()
    return records


# ── Utilities ─────────────────────────────────────────────────────────────────

def get_available_markets(conn=None) -> pd.DataFrame:
    """Query which markets and books are currently in sportsbook_props."""
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
    """Retrieve all current prop lines for a given player."""
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
