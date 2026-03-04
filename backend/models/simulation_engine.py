"""
models/simulation_engine.py
Monte Carlo simulation engine for NBA player prop probability estimation.

For each player and stat, simulates N games drawn from a normal distribution
parameterized by mean/std from player_distributions, then computes the
probability of exceeding each line on the prop ladder.

Populates: player_simulations

Performance: ~500 players × 10,000 sims completes in < 5s using vectorized NumPy.
"""

import logging
import time
import numpy as np
import pandas as pd

from backend.db.connection import get_connection, init_model_schema

logger = logging.getLogger(__name__)

SIMULATION_COUNT = 10_000

# Alternate prop ladders per stat
PROP_LINES = {
    "points":   [10, 15, 20, 25, 30, 35, 40, 45, 50],
    "rebounds": [2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 15],
    "assists":  [2, 3, 4, 5, 6, 7, 8, 9, 10, 12],
}


def simulate_player_props(conn=None) -> int:
    """
    Run Monte Carlo simulations for all players and write probability
    ladders to player_simulations.

    Uses projections as the mean (if available) and std_dev from
    player_distributions for variance.

    Returns the number of simulation rows written.
    """
    close = conn is None
    conn = conn or get_connection()
    init_model_schema(conn)

    logger.info("Loading projections and distributions...")

    projections = conn.execute("""
        SELECT player_id, game_id, points_mean, rebounds_mean, assists_mean
        FROM player_projections
    """).df()

    distributions = conn.execute("""
        SELECT player_id, game_id, stat, mean, std_dev
        FROM player_distributions
    """).df()

    if distributions.empty:
        logger.warning("No player_distributions found. Run run_projections first.")
        if close:
            conn.close()
        return 0

    # Build a fast lookup: (player_id, stat) -> (mean, std_dev)
    # Prefer projection mean over distribution mean when available
    proj_means = {}
    for _, row in projections.iterrows():
        pid = str(row["player_id"])
        proj_means[(pid, "points")]   = row["points_mean"]
        proj_means[(pid, "rebounds")] = row["rebounds_mean"]
        proj_means[(pid, "assists")]  = row["assists_mean"]

    # dist lookup: (player_id, stat) -> (mean, std_dev, game_id)
    dist_lookup = {}
    for _, row in distributions.iterrows():
        key = (str(row["player_id"]), row["stat"])
        dist_lookup[key] = {
            "mean":    row["mean"],
            "std_dev": row["std_dev"],
            "game_id": row["game_id"],
        }

    players = distributions["player_id"].astype(str).unique()
    stats   = list(PROP_LINES.keys())

    logger.info(f"Simulating {SIMULATION_COUNT:,} games for {len(players)} players "
                f"across {len(stats)} stats...")

    t0 = time.time()
    records = []

    rng = np.random.default_rng(seed=42)  # reproducible

    for player_id in players:
        for stat in stats:
            key = (player_id, stat)
            if key not in dist_lookup:
                continue

            dist   = dist_lookup[key]
            game_id = dist["game_id"]
            std_dev = max(float(dist["std_dev"]), 1.5)

            # Use projection mean if available, otherwise fall back to dist mean
            mean = proj_means.get(key, float(dist["mean"]))
            mean = max(mean, 0.0)

            # Vectorized simulation — all N draws at once
            simulated = rng.normal(loc=mean, scale=std_dev, size=SIMULATION_COUNT)
            simulated = np.clip(simulated, 0, None)  # stats can't be negative

            for line in PROP_LINES[stat]:
                prob = float(np.mean(simulated >= line))
                records.append({
                    "game_id":     game_id,
                    "player_id":   player_id,
                    "stat":        stat,
                    "line":        float(line),
                    "probability": round(prob, 6),
                })

    elapsed = time.time() - t0
    logger.info(f"  Simulations complete in {elapsed:.2f}s — {len(records):,} probability rows generated.")

    sim_df = pd.DataFrame(records)
    conn.execute("DELETE FROM player_simulations")
    conn.execute("INSERT INTO player_simulations SELECT * FROM sim_df")
    logger.info(f"  → {len(sim_df):,} rows written to player_simulations.")

    if close:
        conn.close()
    return len(sim_df)


def probability_to_american_odds(probability: float) -> int:
    """Convert a decimal probability to American odds format."""
    if probability <= 0 or probability >= 1:
        return 0
    if probability >= 0.5:
        return int(-(probability / (1 - probability)) * 100)
    else:
        return int(((1 - probability) / probability) * 100)


def american_odds_to_probability(american_odds: float) -> float:
    """Convert American odds to implied probability."""
    if american_odds > 0:
        return 100 / (american_odds + 100)
    else:
        return abs(american_odds) / (abs(american_odds) + 100)
