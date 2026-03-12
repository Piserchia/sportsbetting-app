"""
models/projection_model.py
Generates stat projections using LightGBM ML models (via stat_models.py)
with heuristic fallback. Minutes come from the trained minutes model in
player_features.minutes_projection.

Populates: player_projections, player_distributions
"""

import uuid
import logging
import pandas as pd
import numpy as np

from backend.database.connection import get_connection, init_model_schema
from backend.models.stat_models.stat_models import generate_ml_projections

logger = logging.getLogger(__name__)

PACE_ADJ_MIN,  PACE_ADJ_MAX  = 0.85, 1.15
DEF_ADJ_MIN,   DEF_ADJ_MAX   = 0.80, 1.20
USAGE_ADJ_MIN, USAGE_ADJ_MAX = 0.85, 1.15


def generate_projections(conn=None) -> int:
    """
    Build player_projections.

    Tries LightGBM ML models (stat_models.py) first.
    Falls back to weighted-average heuristic if training data is insufficient.
    """
    close = conn is None
    conn = conn or get_connection()
    init_model_schema(conn)

    logger.info("Generating projections via ML models...")
    try:
        ml_projections = generate_ml_projections(conn=conn)
        if not ml_projections.empty:
            conn.execute("DELETE FROM player_projections")
            conn.execute("INSERT INTO player_projections SELECT * FROM ml_projections")
            n_ml = len(ml_projections)
            logger.info(f"  → {n_ml} rows written to player_projections (ML).")
            dist_count = build_distributions(conn)
            logger.info(f"  → {dist_count} rows written to player_distributions.")
            conn.execute(
                "INSERT OR REPLACE INTO ingestion_log VALUES (?,?,?,?,?,?,current_timestamp)",
                [str(uuid.uuid4()), "projection_model", "player_projections", n_ml, "success", "ML"]
            )
            if close:
                conn.close()
            return n_ml
    except Exception as e:
        logger.warning(f"  ML projections failed: {e} — falling back to heuristic")

    logger.info("Loading player_features for heuristic projections...")
    features = conn.execute("SELECT * FROM player_features").df()

    if features.empty:
        logger.warning("No player_features found. Run build_features first.")
        if close:
            conn.close()
        return 0

    logger.info(f"Generating heuristic projections for {features['player_id'].nunique()} players...")

    features["base_pts"] = (
        0.5 * features["points_avg_last_10"] +
        0.3 * features["points_avg_last_5"] +
        0.2 * features.get("season_avg_points", features["points_avg_last_10"])
    )
    features["base_reb"] = (
        0.5 * features["rebounds_avg_last_10"] +
        0.3 * features.get("rebounds_avg_last_5", features["rebounds_avg_last_10"]) +
        0.2 * features.get("season_avg_rebounds", features["rebounds_avg_last_10"])
    )
    features["base_ast"] = (
        0.5 * features["assists_avg_last_10"] +
        0.3 * features.get("assists_avg_last_5", features["assists_avg_last_10"]) +
        0.2 * features.get("season_avg_assists", features["assists_avg_last_10"])
    )

    pace_adj    = features.get("pace_adjustment_factor", pd.Series(1.0, index=features.index)).fillna(1.0).clip(PACE_ADJ_MIN, PACE_ADJ_MAX)
    def_adj_pts = features.get("defense_adj_pts", pd.Series(1.0, index=features.index)).fillna(1.0).clip(DEF_ADJ_MIN, DEF_ADJ_MAX)
    def_adj_reb = features.get("defense_adj_reb", pd.Series(1.0, index=features.index)).fillna(1.0).clip(DEF_ADJ_MIN, DEF_ADJ_MAX)
    def_adj_ast = features.get("defense_adj_ast", pd.Series(1.0, index=features.index)).fillna(1.0).clip(DEF_ADJ_MIN, DEF_ADJ_MAX)
    usage       = features.get("usage_proxy", pd.Series(0.2, index=features.index)).fillna(0.2)
    usage_adj   = (usage / 0.20).clip(USAGE_ADJ_MIN, USAGE_ADJ_MAX)

    def_adj_stl = features.get("defense_adj_stl", pd.Series(1.0, index=features.index)).fillna(1.0).clip(DEF_ADJ_MIN, DEF_ADJ_MAX)
    def_adj_blk = features.get("defense_adj_blk", pd.Series(1.0, index=features.index)).fillna(1.0).clip(DEF_ADJ_MIN, DEF_ADJ_MAX)

    base_stl = (
        0.5 * features.get("steals_avg_last_10", pd.Series(0.0, index=features.index)) +
        0.3 * features.get("steals_avg_last_5",  pd.Series(0.0, index=features.index)) +
        0.2 * features.get("season_avg_steals",  pd.Series(0.0, index=features.index))
    )
    base_blk = (
        0.5 * features.get("blocks_avg_last_10", pd.Series(0.0, index=features.index)) +
        0.3 * features.get("blocks_avg_last_5",  pd.Series(0.0, index=features.index)) +
        0.2 * features.get("season_avg_blocks",  pd.Series(0.0, index=features.index))
    )

    features["points_mean"]        = (features["base_pts"] * pace_adj * def_adj_pts * usage_adj).clip(lower=0).round(4)
    features["rebounds_mean"]      = (features["base_reb"] * pace_adj * def_adj_reb).clip(lower=0).round(4)
    features["assists_mean"]       = (features["base_ast"] * pace_adj * def_adj_ast).clip(lower=0).round(4)
    features["steals_mean"]        = (base_stl * pace_adj * def_adj_stl).clip(lower=0).round(4)
    features["blocks_mean"]        = (base_blk * pace_adj * def_adj_blk).clip(lower=0).round(4)
    features["minutes_projection"] = features.get("minutes_projection", features.get("minutes_avg_last_10", 0.0)).fillna(0.0).round(4)

    projections = features[["game_id", "player_id", "points_mean", "rebounds_mean",
                             "assists_mean", "steals_mean", "blocks_mean", "minutes_projection"]].copy()
    conn.execute("DELETE FROM player_projections")
    conn.execute("INSERT INTO player_projections SELECT * FROM projections")
    logger.info(f"  → {len(projections)} rows written to player_projections (heuristic).")

    dist_count = build_distributions(conn)
    logger.info(f"  → {dist_count} rows written to player_distributions.")
    n = len(projections)
    conn.execute(
        "INSERT OR REPLACE INTO ingestion_log VALUES (?,?,?,?,?,?,current_timestamp)",
        [str(uuid.uuid4()), "projection_model", "player_projections", n, "success", ""]
    )
    if close:
        conn.close()
    return n


def build_distributions(conn=None) -> int:
    """
    Compute per-player standard deviations from historical game logs.
    Uses recent-form std (last 20 games) weighted with full-season std
    to be more responsive to current variance patterns.
    """
    close = conn is None
    conn = conn or get_connection()

    logs = conn.execute("""
        SELECT player_id, game_id, game_date, points, rebounds, assists, steals, blocks
        FROM player_game_logs
        ORDER BY player_id, game_date ASC
    """).df()

    if logs.empty:
        if close:
            conn.close()
        return 0

    latest_games = conn.execute("""
        SELECT player_id, game_id
        FROM (
            SELECT player_id, game_id,
                   ROW_NUMBER() OVER (PARTITION BY player_id ORDER BY game_date DESC) AS rn
            FROM player_game_logs
        ) t WHERE rn = 1
    """).df()

    stats = ["points", "rebounds", "assists", "steals", "blocks"]
    records = []
    MIN_STD = 1.5

    for _, latest in latest_games.iterrows():
        player_id = str(latest["player_id"])
        game_id   = str(latest["game_id"])
        plogs = logs[logs["player_id"] == latest["player_id"]].sort_values("game_date")

        for stat in stats:
            values = plogs[stat].dropna()
            n = len(values)

            if n == 0:
                mean, std = 0.0, MIN_STD
            elif n == 1:
                mean = float(values.iloc[0])
                std = mean * 0.20
            else:
                mean = float(values.mean())
                full_std = float(values.std())

                # Weight recent variance more heavily if enough data
                if n >= 10:
                    recent = values.iloc[-20:]
                    recent_std = float(recent.std()) if len(recent) > 1 else full_std
                    # 60% recent, 40% full-season
                    std = 0.6 * recent_std + 0.4 * full_std
                else:
                    std = full_std

            std = max(std, MIN_STD)

            records.append({
                "game_id":   game_id,
                "player_id": player_id,
                "stat":      stat,
                "mean":      round(float(mean), 4),
                "std_dev":   round(float(std),  4),
            })

    dist_df = pd.DataFrame(records)
    conn.execute("DELETE FROM player_distributions")
    conn.execute("INSERT INTO player_distributions SELECT * FROM dist_df")

    if close:
        conn.close()
    return len(dist_df)
