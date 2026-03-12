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
from backend.db.connection import get_connection, init_model_schema
from backend.models.simulation_engine import (
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

    if close:
        conn.close()
    return len(result)


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
