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

    # Check if we have any prop odds yet
    try:
        odds_count = conn.execute("""
            SELECT COUNT(*) FROM odds WHERE market NOT IN ('h2h', 'spreads', 'totals')
        """).fetchone()[0]
    except Exception:
        odds_count = 0

    if odds_count == 0:
        logger.warning(
            "No prop odds found in the odds table yet. "
            "Add SportsGameOdds ingestion to populate prop lines. "
            "Generating edges from simulations only (no book comparison)."
        )
        count = _write_model_only_edges(conn)
        if close:
            conn.close()
        return count

    # Full edge calculation once odds are available
    logger.info("Calculating edges against sportsbook odds...")

    edges = conn.execute("""
        SELECT
            s.game_id,
            s.player_id,
            s.stat,
            s.line,
            s.probability                                   AS model_probability,
            o.home_price                                    AS sportsbook_odds,
            o.bookmaker                                     AS book
        FROM player_simulations s
        JOIN odds o
            ON s.game_id = o.game_id
            AND s.line = o.home_point
            AND o.market = s.stat
        WHERE s.probability > 0
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
    logger.info(f"  → {len(result):,} model-only rows written to prop_edges.")
    return len(result)


if __name__ == "__main__":
    conn = get_connection()
    count = calculate_edges(conn=conn)
    conn.close()
    print(f"✅ Edge calculation complete — {count:,} rows written to prop_edges.")
