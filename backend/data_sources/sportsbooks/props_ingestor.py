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
- Only fetches stats we model (pts/reb/ast/stl/blk)
- 60-min cooldown between API calls (configurable)
- Dev mode: draftkings only, once per day

Env vars:
    PROPS_BOOKS=draftkings,fanduel,betmgm
    PROPS_COOLDOWN_MINUTES=60
    PROPS_DEV_MODE=false

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SGO API v2 STRUCTURE (events endpoint)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GET /v2/events?leagueID=NBA&started=false&oddsPresent=true

Each event has:
  event.players  — dict of {playerID: {name, teamID, ...}}
  event.odds     — dict of {oddKey: oddObj}

oddKey format: {stat}-{PLAYER_ID}-{period}-{betType}-{side}
  e.g.  points-LEBRON_JAMES_1_NBA-game-ou-over

oddObj fields:
  statID, playerID, periodID, betTypeID, sideID
  bookOverUnder  — the line
  bookOdds       — consensus odds (American)
  byBookmaker    — {bookID: {odds, overUnder, available, lastUpdatedAt}}
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

from backend.database.connection import get_connection, init_model_schema

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

SGO_API_KEY  = os.getenv("SPORTSGAMEODDS_API_KEY", "")
SGO_BASE_URL = "https://api.sportsgameodds.com/v2"

LEAGUE_ID = "NBA"

# ── Free-tier settings ────────────────────────────────────────────────────────

PROPS_DEV_MODE = os.getenv("PROPS_DEV_MODE", "false").lower() == "true"
PROPS_COOLDOWN_MINUTES = int(os.getenv("PROPS_COOLDOWN_MINUTES", "1440" if PROPS_DEV_MODE else "60"))

DEFAULT_BOOKS = ["draftkings", "fanduel"]
if PROPS_DEV_MODE:
    BOOKS = ["draftkings"]
    logger.warning("PROPS_DEV_MODE active — draftkings only, 24hr cooldown")
else:
    BOOKS = [b.strip() for b in os.getenv("PROPS_BOOKS", ",".join(DEFAULT_BOOKS)).split(",")]

# Stats we model — only pull game-period over/under for these
MODELED_STATS = {"points", "rebounds", "assists", "steals", "blocks"}


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
    if not SGO_API_KEY or SGO_API_KEY == "your_key_here":
        logger.warning(
            "SPORTSGAMEODDS_API_KEY not set. "
            "Sign up at https://sportsgameodds.com and add your key to config/.env"
        )
        return False
    return True


def fetch_events_with_props(include_alternates: bool = True) -> list:
    """
    Fetch upcoming NBA events that have odds from SportsGameOdds /v2/events.
    Returns list of event dicts (each has .odds and .players).
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
    tomorrow = datetime.now(timezone.utc).strftime("%Y-%m-%dT23:59:59Z")

    url = f"{SGO_BASE_URL}/events"
    params = {
        "apiKey":          SGO_API_KEY,
        "leagueID":        LEAGUE_ID,
        "startsAfter":     today,
        "startsBefore":    tomorrow,
        "oddsPresent":     "true",
        "includeAltLines": "true" if include_alternates else "false",
    }

    logger.info("Fetching NBA events with props from SportsGameOdds...")
    resp = requests.get(url, params=params, timeout=20)
    resp.raise_for_status()

    remaining = resp.headers.get("x-credits-remaining", "?")
    used      = resp.headers.get("x-credits-used", "?")
    logger.info(f"  SGO quota — used: {used}, remaining: {remaining}")

    data = resp.json()
    return data.get("data", [])


# ── Player Matching ────────────────────────────────────────────────────────────

_SUFFIX_RE = re.compile(r'\s+(jr\.?|sr\.?|ii|iii|iv|v)$', re.IGNORECASE)


def _build_player_lookup(conn) -> dict:
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
    Three-tier: exact → strip suffix → last-name unique fallback.
    """
    if not player_name:
        return None

    normalized = player_name.lower().strip()
    if normalized in lookup:
        return lookup[normalized]

    stripped = _SUFFIX_RE.sub("", normalized).strip()
    if stripped != normalized and stripped in lookup:
        return lookup[stripped]

    for name, pid in lookup.items():
        if _SUFFIX_RE.sub("", name).strip() == stripped:
            return pid

    last_name = normalized.split()[-1]
    matches = [pid for name, pid in lookup.items() if name.endswith(last_name)]
    if len(matches) == 1:
        return matches[0]

    return None


def _get_today_game_ids(conn) -> list:
    rows = conn.execute("""
        SELECT game_id FROM games WHERE game_date = CURRENT_DATE
    """).fetchall()
    game_ids = [r[0] for r in rows]
    logger.info(f"  Today's games: {len(game_ids)}")
    return game_ids


# Map SGO teamID suffixes → our abbreviations
# Format: DETROIT_PISTONS_NBA → try to match home_team_abbr / away_team_abbr
_SGO_TEAM_ABBR: dict[str, str] = {
    "ATLANTA_HAWKS_NBA":           "ATL",
    "BOSTON_CELTICS_NBA":          "BOS",
    "BROOKLYN_NETS_NBA":           "BKN",
    "CHARLOTTE_HORNETS_NBA":       "CHA",
    "CHICAGO_BULLS_NBA":           "CHI",
    "CLEVELAND_CAVALIERS_NBA":     "CLE",
    "DALLAS_MAVERICKS_NBA":        "DAL",
    "DENVER_NUGGETS_NBA":          "DEN",
    "DETROIT_PISTONS_NBA":         "DET",
    "GOLDEN_STATE_WARRIORS_NBA":   "GSW",
    "HOUSTON_ROCKETS_NBA":         "HOU",
    "INDIANA_PACERS_NBA":          "IND",
    "LOS_ANGELES_CLIPPERS_NBA":    "LAC",
    "LOS_ANGELES_LAKERS_NBA":      "LAL",
    "MEMPHIS_GRIZZLIES_NBA":       "MEM",
    "MIAMI_HEAT_NBA":              "MIA",
    "MILWAUKEE_BUCKS_NBA":         "MIL",
    "MINNESOTA_TIMBERWOLVES_NBA":  "MIN",
    "NEW_ORLEANS_PELICANS_NBA":    "NOP",
    "NEW_YORK_KNICKS_NBA":         "NYK",
    "OKLAHOMA_CITY_THUNDER_NBA":   "OKC",
    "ORLANDO_MAGIC_NBA":           "ORL",
    "PHILADELPHIA_76ERS_NBA":      "PHI",
    "PHOENIX_SUNS_NBA":            "PHX",
    "PORTLAND_TRAIL_BLAZERS_NBA":  "POR",
    "SACRAMENTO_KINGS_NBA":        "SAC",
    "SAN_ANTONIO_SPURS_NBA":       "SAS",
    "TORONTO_RAPTORS_NBA":         "TOR",
    "UTAH_JAZZ_NBA":               "UTA",
    "WASHINGTON_WIZARDS_NBA":      "WAS",
}


def _match_game_id(conn, event_date: str, today_game_ids: list,
                   home_team_id: str = "", away_team_id: str = "") -> Optional[str]:
    """
    Match an SGO event to our internal game_id.
    Primary: match on team abbreviations (home + away).
    Fallback: first game on event_date (for cases where team mapping fails).
    """
    if not today_game_ids:
        return None

    home_abbr = _SGO_TEAM_ABBR.get(home_team_id, "")
    away_abbr = _SGO_TEAM_ABBR.get(away_team_id, "")

    if home_abbr and away_abbr:
        result = conn.execute("""
            SELECT game_id FROM games
            WHERE CAST(game_date AS VARCHAR) = ?
              AND home_team_abbr = ?
              AND away_team_abbr = ?
            LIMIT 1
        """, [event_date, home_abbr, away_abbr]).fetchone()
        if result:
            return result[0]

    # Fallback: date-only match within today's games
    placeholders = ",".join(["?"] * len(today_game_ids))
    result = conn.execute(f"""
        SELECT game_id FROM games
        WHERE game_id IN ({placeholders})
        AND CAST(game_date AS VARCHAR) = ?
        LIMIT 1
    """, today_game_ids + [event_date]).fetchone()
    return result[0] if result else None


# ── Snapshot Rebuild ──────────────────────────────────────────────────────────

def _rebuild_sportsbook_props(conn, today_game_ids: list):
    if not today_game_ids:
        return

    placeholders = ",".join(["?"] * len(today_game_ids))

    conn.execute(f"""
        DELETE FROM sportsbook_props
        WHERE game_id IN ({placeholders})
    """, today_game_ids)

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


# ── Prop Parsing ──────────────────────────────────────────────────────────────

def _parse_props_from_events(events: list, books: list, player_lookup: dict,
                              today_game_ids: list, conn,
                              include_alternates: bool = True) -> list:
    """
    Parse player prop records from SGO events.

    For each event, iterates over event.odds, filters to:
      - betTypeID == "ou"
      - sideID == "over"   (we pair over+under by matching opposingOddID)
      - periodID == "game"
      - statID in MODELED_STATS
      - playerID present

    Emits one record per (player, stat, line, book) for the standard line,
    plus one record per alt line in byBookmaker[book].altLines when
    include_alternates=True.

    Under odds for alt lines come from the opposing (under) odd's altLines,
    matched by overUnder value.

    Returns list of dicts ready for prop_line_history insert.
    """
    records = []

    for event in events:
        starts_at    = event.get("status", {}).get("startsAt", "")
        event_date   = starts_at[:10] if starts_at else ""
        odds_map     = event.get("odds", {})
        players_map  = event.get("players", {})
        teams        = event.get("teams", {})
        home_team_id = teams.get("home", {}).get("teamID", "")
        away_team_id = teams.get("away", {}).get("teamID", "")

        game_id = _match_game_id(conn, event_date, today_game_ids, home_team_id, away_team_id)
        if not game_id:
            continue

        now = datetime.now(timezone.utc).isoformat()

        for odd_key, odd in odds_map.items():
            if odd.get("betTypeID") != "ou":
                continue
            if odd.get("sideID") != "over":
                continue
            if odd.get("periodID") != "game":
                continue

            stat = odd.get("statID", "")
            if stat not in MODELED_STATS:
                continue

            sgo_player_id = odd.get("playerID", "")
            if not sgo_player_id:
                continue

            player_info = players_map.get(sgo_player_id, {})
            player_name = player_info.get("name", "")
            player_id   = _match_player(player_name, player_lookup)
            if not player_id:
                logger.debug(f"  Unmatched player: '{player_name}' ({sgo_player_id})")
                continue

            opposing_key   = odd.get("opposingOddID", "")
            under_odd      = odds_map.get(opposing_key, {})
            by_book        = odd.get("byBookmaker", {})
            under_by_book  = under_odd.get("byBookmaker", {})

            for book_id, book_data in by_book.items():
                if book_id not in books:
                    continue

                under_book = under_by_book.get(book_id, {})

                # ── Standard line ──────────────────────────────────────
                if book_data.get("available", False):
                    line = book_data.get("overUnder")
                    if line is not None:
                        under_odds_str = under_book.get("odds") if under_book.get("available") else None
                        records.append(_make_record(
                            now, book_id, player_id, player_name, game_id, stat,
                            float(line),
                            _american_to_float(book_data.get("odds")),
                            _american_to_float(under_odds_str),
                        ))

                # ── Alternate lines ────────────────────────────────────
                if not include_alternates:
                    continue

                under_alt_map = {
                    str(a["overUnder"]): a
                    for a in under_book.get("altLines", [])
                    if a.get("available", False)
                }

                for alt in book_data.get("altLines", []):
                    if not alt.get("available", False):
                        continue
                    alt_line = alt.get("overUnder")
                    if alt_line is None:
                        continue
                    matching_under = under_alt_map.get(str(alt_line), {})
                    records.append(_make_record(
                        now, book_id, player_id, player_name, game_id, stat,
                        float(alt_line),
                        _american_to_float(alt.get("odds")),
                        _american_to_float(matching_under.get("odds")),
                    ))

    return records


def _make_record(now, book_id, player_id, player_name, game_id, stat,
                 line, over_odds, under_odds) -> dict:
    history_id = md5(
        f"{now}_{book_id}_{player_id}_{stat}_{line}".encode()
    ).hexdigest()
    return {
        "history_id":  history_id,
        "fetched_at":  now,
        "book":        book_id,
        "player_id":   player_id,
        "player_name": player_name,
        "game_id":     game_id,
        "stat":        stat,
        "line":        line,
        "over_odds":   over_odds,
        "under_odds":  under_odds,
    }


def _american_to_float(odds_str) -> Optional[float]:
    """Convert American odds string ('+110', '-122') to float, or None."""
    if odds_str is None:
        return None
    try:
        return float(str(odds_str))
    except (ValueError, TypeError):
        return None


# ── Ingestion ─────────────────────────────────────────────────────────────────

def ingest_props(include_alternates: bool = True, conn=None) -> int:
    """
    Fetch player prop lines from SportsGameOdds and write to sportsbook_props.
    Optimized for free-tier: today's games only, configured books, cooldown guard.

    Args:
        include_alternates: Whether to ingest alternate line ladders (default True).

    Returns:
        Number of prop rows written to prop_line_history.
    """
    if not _check_api_key():
        return 0

    close = conn is None
    conn  = conn or get_connection()
    init_model_schema(conn)
    init_props_schema(conn)

    if _check_cooldown(conn):
        _log_ingestion(conn, "sportsgameodds", "props", 0, "skipped",
                       f"Within {PROPS_COOLDOWN_MINUTES}m cooldown")
        if close:
            conn.close()
        return 0

    today_game_ids = _get_today_game_ids(conn)
    if not today_game_ids:
        logger.info("No games today — skipping props fetch.")
        _log_ingestion(conn, "sportsgameodds", "props", 0, "skipped", "No games today")
        if close:
            conn.close()
        return 0

    player_lookup = _build_player_lookup(conn)
    logger.info(f"  Player lookup built — {len(player_lookup)} active players.")

    try:
        events = fetch_events_with_props(include_alternates=include_alternates)
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

    if not events:
        logger.warning("No events returned from SportsGameOdds.")
        _log_ingestion(conn, "sportsgameodds", "props", 0, "success",
                       f"0 events returned | books: {','.join(BOOKS)}")
        if close:
            conn.close()
        return 0

    logger.info(f"  Processing {len(events)} events...")

    prop_records = _parse_props_from_events(
        events, BOOKS, player_lookup, today_game_ids, conn,
        include_alternates=include_alternates,
    )

    written = 0
    written_game_ids = set()
    for rec in prop_records:
        try:
            conn.execute("""
                INSERT INTO prop_line_history (
                    history_id, fetched_at, book, player_id, player_name,
                    game_id, stat, line, over_odds, under_odds
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """, [
                rec["history_id"], rec["fetched_at"], rec["book"],
                rec["player_id"],  rec["player_name"], rec["game_id"],
                rec["stat"],       rec["line"], rec["over_odds"], rec["under_odds"],
            ])
            written += 1
            written_game_ids.add(rec["game_id"])
        except Exception as e:
            logger.debug(f"  History insert error: {e}")

    # Rebuild snapshot for today's games AND any other games that had props written
    all_game_ids = list(set(today_game_ids) | written_game_ids)
    _rebuild_sportsbook_props(conn, all_game_ids)

    unmatched_events = len(events)  # rough proxy; detailed count inside parser
    msg = (f"{written} rows appended to history | "
           f"{len(today_game_ids)} games | "
           f"books: {','.join(BOOKS)}")
    _log_ingestion(conn, "sportsgameodds", "props", written, "success", msg)
    logger.info(f"  → {written} prop rows written to prop_line_history.")

    if close:
        conn.close()
    return written


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
