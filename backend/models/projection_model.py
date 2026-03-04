"""
models/projection_model.py
Generates per-player stat projections and distributions using weighted averages.

Populates: player_projections, player_distributions
"""

import logging
import pandas as pd
import numpy as np

from backend.db.connection import get_connection, init_model_schema

logger = logging.getLogger(__name__)


def generate_projections(conn=None) -> int:
    """
    Build player_projections from player_features using a weighted average formula:
        points_mean = 0.5 * last_10 + 0.3 * last_5 + 0.2 * season_avg

    Returns the number of projection rows written.
    """
    close = conn is None
    conn = conn or get_connection()
    init_model_schema(conn)

    logger.info("Loading player_features for projections...")
    features = conn.execute("""
        SELECT * FROM player_features
    """).df()

    if features.empty:
        logger.warning("No player_features found. Run build_features first.")
        if close:
            conn.close()
        return 0

    logger.info(f"Generating projections for {features['player_id'].nunique()} players...")

    # Weighted average projection
    features["points_mean"] = (
        0.5 * features["points_avg_last_10"] +
        0.3 * features["points_avg_last_5"] +
        0.2 * features["season_avg_points"]
    ).round(4)

    # Rebounds and assists use last_10 only (no last_5 features yet — easy to extend)
    features["rebounds_mean"]      = features["rebounds_avg_last_10"].round(4)
    features["assists_mean"]       = features["assists_avg_last_10"].round(4)
    features["minutes_projection"] = features["minutes_avg_last_10"].round(4)

    projections = features[[
        "game_id", "player_id",
        "points_mean", "rebounds_mean", "assists_mean", "minutes_projection"
    ]].copy()

    conn.execute("DELETE FROM player_projections")
    conn.execute("INSERT INTO player_projections SELECT * FROM projections")
    logger.info(f"  → {len(projections)} rows written to player_projections.")

    # Build distributions alongside projections
    dist_count = build_distributions(conn)
    logger.info(f"  → {dist_count} rows written to player_distributions.")

    if close:
        conn.close()
    return len(projections)


def build_distributions(conn=None) -> int:
    """
    Compute per-player standard deviations from historical game logs.
    Uses all available games per player for robust std estimates.

    Populates: player_distributions
    """
    close = conn is None
    conn = conn or get_connection()

    logger.info("Building player distributions from game logs...")

    logs = conn.execute("""
        SELECT player_id, game_id, points, rebounds, assists
        FROM player_game_logs
    """).df()

    if logs.empty:
        logger.warning("No game logs found for distribution building.")
        if close:
            conn.close()
        return 0

    # Get the latest game_id per player to anchor distributions to
    latest_games = conn.execute("""
        SELECT player_id, game_id
        FROM (
            SELECT player_id, game_id,
                   ROW_NUMBER() OVER (PARTITION BY player_id ORDER BY game_date DESC) AS rn
            FROM player_game_logs
        ) t WHERE rn = 1
    """).df()

    stats = ["points", "rebounds", "assists"]
    records = []

    for _, latest in latest_games.iterrows():
        player_id = str(latest["player_id"])
        game_id   = str(latest["game_id"])
        player_logs = logs[logs["player_id"] == latest["player_id"]]

        for stat in stats:
            values = player_logs[stat].dropna()
            mean   = float(values.mean()) if len(values) > 0 else 0.0
            # Use at least 2 games for std; fall back to 20% of mean as a floor
            if len(values) >= 2:
                std = float(values.std())
            else:
                std = mean * 0.20

            # Enforce a minimum std so simulations don't collapse to a spike
            std = max(std, 1.5)

            records.append({
                "game_id":   game_id,
                "player_id": player_id,
                "stat":      stat,
                "mean":      round(mean, 4),
                "std_dev":   round(std, 4),
            })

    dist_df = pd.DataFrame(records)
    conn.execute("DELETE FROM player_distributions")
    conn.execute("INSERT INTO player_distributions SELECT * FROM dist_df")

    if close:
        conn.close()
    return len(dist_df)
