#!/usr/bin/env python3
"""
scripts/calculate_edges.py
Step 5 of the modeling pipeline.
Compares model probabilities against sportsbook odds to identify +EV bets.

Requires: player_simulations + odds table populated with prop lines.
Currently scaffolded — will be fully activated once SportsGameOdds
props ingestion is added.

Usage:
    python scripts/calculate_edges.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
import logging
import pandas as pd
from config.logging_config import setup_logging
from backend.database.connection import get_connection, init_model_schema
from backend.pipeline.simulations.simulation_engine import (
    probability_to_american_odds,
    american_odds_to_probability,
)

setup_logging()
logger = logging.getLogger(__name__)


def calculate_edges(conn=None) -> int:
    """
    Join player_simulations with sportsbook_odds (when available) to compute:
        - fair_odds: what the line SHOULD pay based on our model
        - expected_value: profit per $1 wagered
        - edge_percent: model prob vs implied book prob

    Returns number of edge rows written.
    """
    close = conn is None
    conn = conn or get_connection()
    init_model_schema(conn)

    # Check if sportsbook_props is populated
    try:
        props_count = conn.execute(
            "SELECT COUNT(*) FROM sportsbook_props"
        ).fetchone()[0]
    except Exception:
        props_count = 0

    if props_count == 0:
        logger.warning(
            "No prop lines found in sportsbook_props. "
            "Run: python scripts/ingest_props.py (requires SPORTSGAMEODDS_API_KEY). "
            "Generating model-only edges for now."
        )
        count = _write_model_only_edges(conn)
        if close:
            conn.close()
        return count

    # Full edge calculation against sportsbook props
    logger.info(f"Calculating edges against {props_count:,} sportsbook prop lines...")

    edges = conn.execute("""
        SELECT
            sp.game_id,
            s.player_id,
            s.stat,
            s.line,
            s.probability               AS model_probability,
            sp.over_odds                AS sportsbook_odds,
            sp.book
        FROM player_simulations s
        JOIN sportsbook_props sp
            ON  s.player_id = sp.player_id
            AND s.stat      = sp.stat
            AND s.line      = sp.line
        WHERE s.probability > 0
          AND sp.over_odds IS NOT NULL
    """).df()

    if edges.empty:
        logger.warning("No matching simulation/odds rows found.")
        if close:
            conn.close()
        return 0

    def compute_ev(row):
        prob  = row["model_probability"]
        odds  = row["sportsbook_odds"]
        # Convert American odds to decimal payout
        if odds > 0:
            payout = odds / 100
        else:
            payout = 100 / abs(odds)
        ev = (prob * payout) - (1 - prob)
        return round(ev, 6)

    edges["fair_odds"]       = edges["model_probability"].apply(
        lambda p: probability_to_american_odds(p)
    )
    edges["expected_value"]  = edges.apply(compute_ev, axis=1)
    edges["implied_prob"]    = edges["sportsbook_odds"].apply(american_odds_to_probability)
    edges["edge_percent"]    = (
        (edges["model_probability"] - edges["implied_prob"]) * 100
    ).round(2)

    result = edges[[
        "game_id", "player_id", "stat", "line",
        "sportsbook_odds", "model_probability",
        "fair_odds", "expected_value", "edge_percent", "book"
    ]]

    conn.execute("DELETE FROM prop_edges")
    conn.execute("INSERT INTO prop_edges SELECT * FROM result")
    logger.info(f"  → {len(result):,} edge rows written to prop_edges.")

    # Log top edges
    top = result[result["edge_percent"] > 0].sort_values("edge_percent", ascending=False).head(10)
    if not top.empty:
        logger.info("Top +EV edges found:")
        for _, row in top.iterrows():
            logger.info(
                f"    {row['player_id']} | {row['stat']} {row['line']}+ | "
                f"Model: {row['model_probability']:.1%} | "
                f"Book: {row['sportsbook_odds']:+.0f} | "
                f"Edge: +{row['edge_percent']:.1f}%"
            )

    # Log qualifying bets to model_recommendations
    _log_recommendations(conn, edges)

    if close:
        conn.close()
    return len(result)


def _get_model_version() -> str:
    """Return a model version string based on the current date."""
    from datetime import datetime
    return datetime.now().strftime("v%Y%m%d")


def _log_recommendations(conn, edges_df: pd.DataFrame):
    """
    Insert qualifying bets into model_recommendations.
    Criteria: edge_percent >= 3 and model_probability >= 0.55.
    Skips duplicates by checking existing (player_id, game_id, stat, line, book).
    """
    qualified = edges_df[
        (edges_df["edge_percent"] >= 3.0) &
        (edges_df["model_probability"] >= 0.55)
    ].copy()

    if qualified.empty:
        logger.info("  No qualifying bets to log.")
        return

    # Look up player names, teams, and positions
    try:
        player_info = conn.execute("""
            SELECT p.player_id, p.full_name,
                   t.abbreviation AS team
            FROM players p
            LEFT JOIN (
                SELECT player_id, team_id,
                       ROW_NUMBER() OVER (PARTITION BY player_id ORDER BY game_id DESC) AS rn
                FROM player_game_stats
            ) pgs ON p.player_id = pgs.player_id AND pgs.rn = 1
            LEFT JOIN teams t ON pgs.team_id = t.team_id
        """).df()
        name_lookup = dict(zip(player_info["player_id"].astype(str), player_info["full_name"]))
        team_lookup = dict(zip(player_info["player_id"].astype(str), player_info["team"]))
    except Exception:
        name_lookup = {}
        team_lookup = {}

    # Look up player positions from player_features
    try:
        pos_info = conn.execute("""
            SELECT player_id, player_position
            FROM player_features
            WHERE player_position IS NOT NULL
            QUALIFY ROW_NUMBER() OVER (PARTITION BY player_id ORDER BY game_id DESC) = 1
        """).df()
        position_lookup = dict(zip(pos_info["player_id"].astype(str), pos_info["player_position"]))
    except Exception:
        position_lookup = {}

    # Look up game info for opponent resolution
    try:
        game_info = conn.execute("""
            SELECT game_id, home_team_abbr, away_team_abbr
            FROM games
        """).df()
        game_home = dict(zip(game_info["game_id"].astype(str), game_info["home_team_abbr"]))
        game_away = dict(zip(game_info["game_id"].astype(str), game_info["away_team_abbr"]))
    except Exception:
        game_home = {}
        game_away = {}

    # Get existing bets to avoid duplicates
    try:
        existing = conn.execute("""
            SELECT CAST(player_id AS TEXT) || '_' || game_id || '_' || stat || '_' ||
                   CAST(line AS VARCHAR) || '_' || sportsbook AS key
            FROM model_recommendations
        """).df()
        existing_keys = set(existing["key"].values) if not existing.empty else set()
    except Exception:
        existing_keys = set()

    model_version = _get_model_version()
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    inserted = 0

    for _, row in qualified.iterrows():
        pid = str(row["player_id"])
        gid = str(row["game_id"])
        key = f"{pid}_{gid}_{row['stat']}_{row['line']}_{row['book']}"
        if key in existing_keys:
            continue

        confidence = round(
            (row["edge_percent"] * 0.6) + (row["model_probability"] * 25), 2
        )
        player_team = team_lookup.get(pid, "")
        home = game_home.get(gid, "")
        away = game_away.get(gid, "")
        if player_team and home and away:
            opponent = away if player_team == home else home
        else:
            opponent = None
        position = position_lookup.get(pid)
        try:
            conn.execute("""
                INSERT INTO model_recommendations (
                    bet_id, timestamp_generated, model_version,
                    game_id, player_id, player_name, team,
                    stat, line, sportsbook, odds,
                    model_probability, edge_percent, confidence_score,
                    player_position, opponent_team
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, [
                str(uuid.uuid4()), now, model_version,
                gid, int(pid) if pid.isdigit() else 0,
                name_lookup.get(pid, "Unknown"),
                player_team,
                row["stat"], float(row["line"]),
                row["book"], int(row["sportsbook_odds"]) if pd.notna(row["sportsbook_odds"]) else None,
                round(float(row["model_probability"]), 6),
                round(float(row["edge_percent"]), 2),
                confidence,
                position,
                opponent,
            ])
            inserted += 1
        except Exception as e:
            logger.debug(f"  Recommendation insert error: {e}")

    logger.info(f"  → {inserted} qualifying bets logged to model_recommendations.")


def _write_model_only_edges(conn) -> int:
    """
    When no sportsbook odds exist yet, write model probabilities + fair odds
    to prop_edges so the table is still queryable for analysis.
    """
    sims = conn.execute("""
        SELECT game_id, player_id, stat, line, probability AS model_probability
        FROM player_simulations
        WHERE probability > 0
    """).df()

    if sims.empty:
        logger.warning("No simulations found. Run simulate_props first.")
        return 0

    sims["fair_odds"]      = sims["model_probability"].apply(probability_to_american_odds)
    sims["sportsbook_odds"] = None
    sims["expected_value"] = None
    sims["edge_percent"]   = None
    sims["book"]           = "model_only"

    result = sims[[
        "game_id", "player_id", "stat", "line",
        "sportsbook_odds", "model_probability",
        "fair_odds", "expected_value", "edge_percent", "book"
    ]]

    conn.execute("DELETE FROM prop_edges")
    conn.execute("INSERT INTO prop_edges SELECT * FROM result")
    n_edges = len(result)
    logger.info(f"  → {n_edges:,} model-only rows written to prop_edges.")
    conn.execute(
        "INSERT OR REPLACE INTO ingestion_log VALUES (?,?,?,?,?,?,current_timestamp)",
        [str(uuid.uuid4()), "edge_calculator", "prop_edges", n_edges, "success", ""]
    )
    return n_edges


if __name__ == "__main__":
    conn = get_connection()
    count = calculate_edges(conn=conn)
    conn.close()
    print(f"✅ Edge calculation complete — {count:,} rows written to prop_edges.")
