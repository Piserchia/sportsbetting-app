"""
ingestion/injury_lineup_ingestor.py
Ingests injury reports and starting lineup information.

Data sources:
  1. ESPN public injury feed (no auth required)
  2. NBA.com injury report (public PDF/JSON)
  3. Rotowire / CBSSports as fallback (web scrape)

This module provides best-effort data. If all sources fail, it logs
a warning and the pipeline continues with no injury context.

Injury context is used by feature_builder to:
  - Flag injured starters (suppresses their projections)
  - Increase usage projections for remaining players when
    a key teammate is out

Tables populated:
  player_injuries, starting_lineups
"""

from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime
from typing import Optional

import pandas as pd
import requests

from backend.database.connection import get_connection, init_model_schema

logger = logging.getLogger(__name__)

ESPN_INJURIES_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"
ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
REQUEST_TIMEOUT = 15


def _injury_id(player_id: str, report_date: str) -> str:
    return hashlib.md5(f"{player_id}_{report_date}".encode()).hexdigest()[:16]


def _lineup_id(game_id: str, player_id: str) -> str:
    return hashlib.md5(f"{game_id}_{player_id}".encode()).hexdigest()[:16]


def fetch_espn_injuries() -> list[dict]:
    """
    Fetch current injury report from ESPN's public API.
    Returns list of injury dicts or empty list on failure.
    """
    try:
        resp = requests.get(ESPN_INJURIES_URL, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"ESPN injuries fetch failed: {e}")
        return []

    injuries = []
    today = date.today().isoformat()

    for team in data.get("injuries", []):
        team_abbr = team.get("team", {}).get("abbreviation", "")
        for item in team.get("injuries", []):
            athlete  = item.get("athlete", {})
            player_id = str(athlete.get("id", ""))
            name     = athlete.get("displayName", "")
            status   = item.get("status", "")
            detail   = item.get("details", {})
            inj_type = detail.get("fantasyStatus", {}).get("description", "") or detail.get("type", "")

            if not player_id:
                continue

            injuries.append({
                "injury_id":   _injury_id(player_id, today),
                "player_id":   player_id,
                "player_name": name,
                "team_abbr":   team_abbr,
                "status":      _normalize_status(status),
                "injury_type": inj_type,
                "report_date": today,
                "game_id":     None,
                "source":      "espn",
            })

    logger.info(f"ESPN injuries: {len(injuries)} records fetched")
    return injuries


def _normalize_status(raw: str) -> str:
    """Normalise injury status to: Out, Doubtful, Questionable, Probable, Available."""
    raw = raw.strip().lower()
    if raw in ("out", "injured reserve", "ir", "suspension"):
        return "Out"
    if raw in ("doubtful",):
        return "Doubtful"
    if raw in ("questionable",):
        return "Questionable"
    if raw in ("probable", "day-to-day"):
        return "Probable"
    return "Available"


def fetch_espn_lineups() -> list[dict]:
    """
    Fetch today's starting lineups from ESPN scoreboard API.
    Returns list of lineup dicts or empty list.
    """
    try:
        resp = requests.get(ESPN_SCOREBOARD_URL, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"ESPN scoreboard fetch failed: {e}")
        return []

    lineups = []
    today   = date.today().isoformat()

    for event in data.get("events", []):
        game_id = str(event.get("id", ""))
        for comp in event.get("competitions", []):
            for side in comp.get("competitors", []):
                team_id = str(side.get("id", ""))
                lineup  = side.get("lineup", [])
                for player in lineup:
                    athlete  = player.get("athlete", {})
                    pid      = str(athlete.get("id", ""))
                    pos      = player.get("position", {}).get("abbreviation", "")
                    starter  = player.get("starter", False)

                    if not pid:
                        continue
                    lineups.append({
                        "lineup_id":   _lineup_id(game_id, pid),
                        "game_id":     game_id,
                        "team_id":     int(team_id) if team_id.isdigit() else None,
                        "player_id":   pid,
                        "is_starter":  bool(starter),
                        "position":    pos,
                        "report_date": today,
                        "source":      "espn",
                    })

    logger.info(f"ESPN lineups: {len(lineups)} records fetched")
    return lineups


def ingest_injuries_and_lineups(conn=None) -> dict[str, int]:
    """
    Fetch and store latest injury reports and lineup data.

    Returns dict with keys 'injuries' and 'lineups' containing
    the number of records written.
    """
    close = conn is None
    conn  = conn or get_connection()
    init_model_schema(conn)

    written = {"injuries": 0, "lineups": 0}

    # ── Injuries ──────────────────────────────────────────────────────────
    injuries = fetch_espn_injuries()
    if injuries:
        inj_df = pd.DataFrame(injuries)
        try:
            conn.execute("INSERT OR REPLACE INTO player_injuries SELECT * FROM inj_df")
            written["injuries"] = len(inj_df)
            logger.info(f"  → {len(inj_df)} injury records written.")
        except Exception as e:
            logger.warning(f"  Failed to write injuries: {e}")

    # ── Lineups ───────────────────────────────────────────────────────────
    lineups = fetch_espn_lineups()
    if lineups:
        lu_df = pd.DataFrame(lineups)
        try:
            conn.execute("INSERT OR REPLACE INTO starting_lineups SELECT * FROM lu_df")
            written["lineups"] = len(lu_df)
            logger.info(f"  → {len(lu_df)} lineup records written.")
        except Exception as e:
            logger.warning(f"  Failed to write lineups: {e}")

    if close:
        conn.close()
    return written


def get_injury_context(conn=None) -> dict[str, str]:
    """
    Returns a dict of {player_id: status} for all players with
    current injury designations (fetched within last 24h).
    """
    close = conn is None
    conn  = conn or get_connection()
    try:
        df = conn.execute("""
            SELECT player_id, status
            FROM player_injuries
            WHERE report_date >= current_date - INTERVAL '1 day'
              AND status IN ('Out', 'Doubtful', 'Questionable')
            ORDER BY fetched_at DESC
        """).df()
        if df.empty:
            return {}
        # deduplicate: keep most recent per player
        df = df.drop_duplicates(subset=["player_id"], keep="first")
        return dict(zip(df["player_id"].astype(str), df["status"]))
    except Exception as e:
        logger.warning(f"Could not load injury context: {e}")
        return {}
    finally:
        if close:
            conn.close()


def get_teammate_injury_multipliers(conn=None) -> dict[str, float]:
    """
    Compute per-player usage multipliers based on injured teammates.

    Logic:
      - For each team with a key player Out/Doubtful:
          remaining players on the team get a usage boost
          proportional to the injured player's usage proxy

    Returns {player_id: multiplier} where multiplier > 1.0 means
    increased usage due to teammate absence.
    """
    close = conn is None
    conn  = conn or get_connection()
    try:
        # Get injured players (Out or Doubtful today)
        injured = conn.execute("""
            SELECT pi.player_id, pi.team_abbr, pi.status
            FROM player_injuries pi
            WHERE pi.report_date >= current_date - INTERVAL '1 day'
              AND pi.status IN ('Out', 'Doubtful')
        """).df()

        if injured.empty:
            return {}

        # Get usage proxy for injured players
        usage = conn.execute("""
            SELECT pf.player_id, pf.usage_proxy,
                   pgl.team
            FROM player_features pf
            JOIN player_game_logs pgl ON pf.player_id = pgl.player_id
                AND pf.game_id = pgl.game_id
            QUALIFY ROW_NUMBER() OVER (PARTITION BY pf.player_id ORDER BY pf.game_id DESC) = 1
        """).df()

        if usage.empty:
            return {}

        # Match injured players to their team abbr
        injured["player_id"] = injured["player_id"].astype(str)
        usage["player_id"]   = usage["player_id"].astype(str)
        merged = injured.merge(usage[["player_id", "usage_proxy", "team"]],
                               on="player_id", how="left")
        merged = merged.dropna(subset=["usage_proxy"])

        # Sum of usage being redistributed per team
        team_lost_usage = (
            merged.groupby("team")["usage_proxy"].sum().to_dict()
        )

        if not team_lost_usage:
            return {}

        # Get all active players with their team
        all_players = conn.execute("""
            SELECT DISTINCT pgl.player_id, pgl.team
            FROM player_game_logs pgl
            QUALIFY ROW_NUMBER() OVER (PARTITION BY pgl.player_id ORDER BY pgl.game_id DESC) = 1
        """).df()

        # Active players not in the injured set
        injured_ids = set(injured["player_id"].astype(str))
        all_players["player_id"] = all_players["player_id"].astype(str)
        active = all_players[~all_players["player_id"].isin(injured_ids)]

        # Team sizes (active players per team)
        team_sizes = active.groupby("team")["player_id"].count().to_dict()

        multipliers: dict[str, float] = {}
        for _, row in active.iterrows():
            pid  = str(row["player_id"])
            team = row["team"]
            lost = team_lost_usage.get(team, 0.0)
            size = team_sizes.get(team, 10)
            if lost > 0 and size > 0:
                # Distribute lost usage equally among active teammates
                bonus = lost / size
                # Convert usage bonus to a multiplier (cap at +20%)
                mult = min(1.0 + bonus / 0.20, 1.20)
                multipliers[pid] = round(mult, 4)

        logger.info(
            f"  Injury usage multipliers computed for {len(multipliers)} players "
            f"({len(injured)} injured players across "
            f"{injured['team_abbr'].nunique()} teams)"
        )
        return multipliers

    except Exception as e:
        logger.warning(f"Could not compute injury multipliers: {e}")
        return {}
    finally:
        if close:
            conn.close()
