"""
models/projection_model.py
Generates context-aware stat projections using weighted averages
adjusted for pace, opponent defense, and usage rate.

Projection formula:
    base_pts = 0.5 * pts_last_10 + 0.3 * pts_last_5 + 0.2 * season_avg_pts
    adjusted = base_pts * pace_adjustment_factor * defense_adj_pts

Minutes projection comes from minutes_model.py (already written into
player_features.minutes_projection with blowout adjustment baked in).

Populates: player_projections, player_distributions
"""

import logging
import pandas as pd
import numpy as np

from backend.db.connection import get_connection, init_model_schema

logger = logging.getLogger(__name__)

# Caps on adjustment factors to prevent extreme outliers
PACE_ADJ_MIN,  PACE_ADJ_MAX  = 0.85, 1.15
DEF_ADJ_MIN,   DEF_ADJ_MAX   = 0.80, 1.20
USAGE_ADJ_MIN, USAGE_ADJ_MAX = 0.85, 1.15


def _clamp(val, lo, hi):
    return max(lo, min(hi, val))


def generate_projections(conn=None) -> int:
    """
    Build player_projections from player_features.

    Base projection:
        pts  = 0.5 * L10 + 0.3 * L5 + 0.2 * season_avg
        reb  = 0.5 * L10 + 0.3 * L5 + 0.2 * season_avg
        ast  = 0.5 * L10 + 0.3 * L5 + 0.2 * season_avg

    Context adjustments (multiplicative):
        adjusted_pts = base_pts * pace_adj * defense_adj_pts * usage_adj
        adjusted_reb = base_reb * pace_adj * defense_adj_reb
        adjusted_ast = base_ast * pace_adj * defense_adj_ast

    Minutes come directly from player_features.minutes_projection
    (already blowout-adjusted by minutes_model.py).
    """
    close = conn is None
    conn = conn or get_connection()
    init_model_schema(conn)

    logger.info("Loading player_features for projections...")
    features = conn.execute("SELECT * FROM player_features").df()

    if features.empty:
        logger.warning("No player_features found. Run build_features first.")
        if close:
            conn.close()
        return 0

    logger.info(f"Generating projections for {features['player_id'].nunique()} players...")

    # ── Base weighted average projections ─────────────────────────────────
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

    # ── Context adjustments ────────────────────────────────────────────────
    # Pace adjustment (clamped)
    pace_adj = features.get("pace_adjustment_factor", pd.Series(1.0, index=features.index))
    pace_adj = pace_adj.fillna(1.0).clip(PACE_ADJ_MIN, PACE_ADJ_MAX)

    # Defense adjustments per stat (clamped)
    def_adj_pts = features.get("defense_adj_pts", pd.Series(1.0, index=features.index))
    def_adj_reb = features.get("defense_adj_reb", pd.Series(1.0, index=features.index))
    def_adj_ast = features.get("defense_adj_ast", pd.Series(1.0, index=features.index))
    def_adj_pts = def_adj_pts.fillna(1.0).clip(DEF_ADJ_MIN, DEF_ADJ_MAX)
    def_adj_reb = def_adj_reb.fillna(1.0).clip(DEF_ADJ_MIN, DEF_ADJ_MAX)
    def_adj_ast = def_adj_ast.fillna(1.0).clip(DEF_ADJ_MIN, DEF_ADJ_MAX)

    # Usage adjustment for points only (clamped)
    usage = features.get("usage_proxy", pd.Series(0.2, index=features.index)).fillna(0.2)
    # Normalise usage relative to a league-average proxy of 0.20
    usage_adj = (usage / 0.20).clip(USAGE_ADJ_MIN, USAGE_ADJ_MAX)

    # ── Final projections ──────────────────────────────────────────────────
    features["points_mean"] = (
        features["base_pts"] * pace_adj * def_adj_pts * usage_adj
    ).clip(lower=0).round(4)

    features["rebounds_mean"] = (
        features["base_reb"] * pace_adj * def_adj_reb
    ).clip(lower=0).round(4)

    features["assists_mean"] = (
        features["base_ast"] * pace_adj * def_adj_ast
    ).clip(lower=0).round(4)

    # Minutes come from the improved minutes model in player_features
    features["minutes_projection"] = features.get(
        "minutes_projection",
        features.get("minutes_avg_last_10", 0.0)
    ).fillna(0.0).round(4)

    projections = features[[
        "game_id", "player_id",
        "points_mean", "rebounds_mean", "assists_mean", "minutes_projection"
    ]].copy()

    conn.execute("DELETE FROM player_projections")
    conn.execute("INSERT INTO player_projections SELECT * FROM projections")
    logger.info(f"  → {len(projections)} rows written to player_projections.")

    dist_count = build_distributions(conn)
    logger.info(f"  → {dist_count} rows written to player_distributions.")

    if close:
        conn.close()
    return len(projections)


def build_distributions(conn=None) -> int:
    """
    Compute per-player standard deviations from historical game logs.
    Std dev is computed from raw game-by-game variance — not adjusted by
    context factors, since context shifts the mean but not the spread.
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
        player_id   = str(latest["player_id"])
        game_id     = str(latest["game_id"])
        player_logs = logs[logs["player_id"] == latest["player_id"]]

        for stat in stats:
            values = player_logs[stat].dropna()
            mean   = float(values.mean()) if len(values) > 0 else 0.0
            if len(values) >= 2:
                std = float(values.std())
            else:
                std = mean * 0.20
            std = max(std, 1.5)  # minimum floor

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
