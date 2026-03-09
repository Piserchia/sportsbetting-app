"""
models/feature_builder.py
Builds all player features from game logs and writes to player_features.

Feature groups:
  - Rolling stat averages (pts/reb/ast L5, L10, season)
  - Improved minutes model (L5, L10, trend, blowout adjustment)
  - Team pace context (team_pace, opponent_pace, pace_adjustment_factor)
  - Opponent defensive strength (pts/reb/ast allowed, defense_adj factors)
  - Usage rate proxy (usage_proxy, usage_trend_last_5)

All feature groups are joined on (game_id, player_id) and written to
player_features as a single wide table. Missing context features
(pace, defense) default to 1.0 adjustment factors so the projection
model degrades gracefully when context data is unavailable.
"""

import logging
import pandas as pd
import numpy as np

from backend.db.connection import get_connection, init_model_schema
from backend.models.pace_features    import build_pace_features
from backend.models.defense_features import build_defense_features
from backend.models.minutes_model    import build_minutes_features
from backend.models.usage_features   import build_usage_features

logger = logging.getLogger(__name__)


def build_player_features(conn=None) -> int:
    """
    Compute all rolling + context features for every player/game combination
    and write to player_features. Clears and rebuilds the table each run.

    Returns number of rows written.
    """
    close = conn is None
    conn = conn or get_connection()
    init_model_schema(conn)

    # ── 1. Base game logs ────────────────────────────────────────────────────
    logger.info("Loading player_game_logs...")
    logs = conn.execute("""
        SELECT
            pgl.game_id,
            pgl.player_id,
            pgl.game_date,
            pgl.minutes,
            pgl.points,
            pgl.rebounds,
            pgl.assists,
            pgl.fg_attempts,
            pgl.free_throw_attempts,
            pgl.turnovers
        FROM player_game_logs pgl
        ORDER BY pgl.player_id, pgl.game_date ASC
    """).df()

    if logs.empty:
        logger.warning("No player_game_logs found. Run ingest_nba first.")
        if close:
            conn.close()
        return 0

    n_players = logs["player_id"].nunique()
    logger.info(f"Building features for {n_players} players across {len(logs)} game logs...")

    # ── 2. Rolling stat features ─────────────────────────────────────────────
    logger.info("  Computing rolling stat features...")
    stat_records = []

    for player_id, player_logs in logs.groupby("player_id"):
        player_logs = player_logs.sort_values("game_date").reset_index(drop=True)

        pts  = player_logs["points"]
        reb  = player_logs["rebounds"]
        ast  = player_logs["assists"]

        points_avg_last_5   = pts.rolling(5,  min_periods=1).mean()
        points_avg_last_10  = pts.rolling(10, min_periods=1).mean()
        rebounds_avg_last_5 = reb.rolling(5,  min_periods=1).mean()
        rebounds_avg_last_10 = reb.rolling(10, min_periods=1).mean()
        assists_avg_last_5  = ast.rolling(5,  min_periods=1).mean()
        assists_avg_last_10 = ast.rolling(10, min_periods=1).mean()
        season_avg_points   = pts.expanding().mean()
        season_avg_rebounds = reb.expanding().mean()
        season_avg_assists  = ast.expanding().mean()

        for i, row in player_logs.iterrows():
            stat_records.append({
                "game_id":               row["game_id"],
                "player_id":             str(player_id),
                "points_avg_last_5":     round(float(points_avg_last_5.iloc[i]),   4),
                "points_avg_last_10":    round(float(points_avg_last_10.iloc[i]),  4),
                "rebounds_avg_last_5":   round(float(rebounds_avg_last_5.iloc[i]), 4),
                "rebounds_avg_last_10":  round(float(rebounds_avg_last_10.iloc[i]),4),
                "assists_avg_last_5":    round(float(assists_avg_last_5.iloc[i]),  4),
                "assists_avg_last_10":   round(float(assists_avg_last_10.iloc[i]), 4),
                "season_avg_points":     round(float(season_avg_points.iloc[i]),   4),
                "season_avg_rebounds":   round(float(season_avg_rebounds.iloc[i]), 4),
                "season_avg_assists":    round(float(season_avg_assists.iloc[i]),  4),
            })

    base_df = pd.DataFrame(stat_records)
    logger.info(f"  → {len(base_df)} base stat feature rows")

    # ── 3. Improved minutes features ─────────────────────────────────────────
    logger.info("  Computing minutes features...")
    try:
        mins_df = build_minutes_features(logs, conn=conn)
        logger.info(f"  → {len(mins_df)} minutes feature rows")
    except Exception as e:
        logger.warning(f"  Minutes features failed: {e} — using fallback")
        mins_df = pd.DataFrame()

    # ── 4. Pace features ─────────────────────────────────────────────────────
    logger.info("  Computing pace features...")
    try:
        pace_df = build_pace_features(conn=conn)
        logger.info(f"  → {len(pace_df)} pace feature rows")
    except Exception as e:
        logger.warning(f"  Pace features failed: {e} — skipping")
        pace_df = pd.DataFrame()

    # ── 5. Defense features ──────────────────────────────────────────────────
    logger.info("  Computing defense features...")
    try:
        def_df = build_defense_features(conn=conn)
        logger.info(f"  → {len(def_df)} defense feature rows")
    except Exception as e:
        logger.warning(f"  Defense features failed: {e} — skipping")
        def_df = pd.DataFrame()

    # ── 6. Usage features ────────────────────────────────────────────────────
    logger.info("  Computing usage features...")
    try:
        usage_df = build_usage_features(conn=conn)
        logger.info(f"  → {len(usage_df)} usage feature rows")
    except Exception as e:
        logger.warning(f"  Usage features failed: {e} — skipping")
        usage_df = pd.DataFrame()

    # ── 7. Join all feature groups ───────────────────────────────────────────
    logger.info("  Joining all feature groups...")
    features = base_df

    key = ["game_id", "player_id"]

    if not mins_df.empty:
        features = features.merge(mins_df, on=key, how="left")
    else:
        # Fallback: use minutes_avg_last_10 from logs directly
        mins_fallback = []
        for player_id, group in logs.groupby("player_id"):
            group = group.sort_values("game_date").reset_index(drop=True)
            rolling = group["minutes"].rolling(10, min_periods=1).mean()
            for i, row in group.iterrows():
                mins_fallback.append({
                    "game_id":                   row["game_id"],
                    "player_id":                 str(player_id),
                    "minutes_avg_last_5":        round(float(group["minutes"].rolling(5, min_periods=1).mean().iloc[i]), 4),
                    "minutes_avg_last_10":       round(float(rolling.iloc[i]), 4),
                    "minutes_trend":             0.0,
                    "games_started_last_5":      0,
                    "minutes_projection":        round(float(rolling.iloc[i]), 4),
                    "blowout_risk":              "NONE",
                    "blowout_adjustment_factor": 1.0,
                })
        features = features.merge(pd.DataFrame(mins_fallback), on=key, how="left")

    if not pace_df.empty:
        features = features.merge(pace_df, on=key, how="left")
    # Defaults for missing pace context
    for col, default in [
        ("team_pace", 100.0), ("opponent_pace", 100.0),
        ("expected_game_pace", 100.0), ("pace_adjustment_factor", 1.0),
    ]:
        if col not in features.columns:
            features[col] = default
        else:
            features[col] = features[col].fillna(default)

    if not def_df.empty:
        features = features.merge(def_df, on=key, how="left")
    # Defaults for missing defense context
    league_avg_pts_allowed = 110.0
    league_avg_reb_allowed = 44.0
    league_avg_ast_allowed = 25.0
    for col, default in [
        ("opponent_points_allowed",  league_avg_pts_allowed),
        ("opponent_rebounds_allowed", league_avg_reb_allowed),
        ("opponent_assists_allowed", league_avg_ast_allowed),
        ("defense_adj_pts",          1.0),
        ("defense_adj_reb",          1.0),
        ("defense_adj_ast",          1.0),
    ]:
        if col not in features.columns:
            features[col] = default
        else:
            features[col] = features[col].fillna(default)

    if not usage_df.empty:
        features = features.merge(usage_df, on=key, how="left")
    for col, default in [("usage_proxy", 0.2), ("usage_trend_last_5", 0.0)]:
        if col not in features.columns:
            features[col] = default
        else:
            features[col] = features[col].fillna(default)

    # ── 8. Write to DB ───────────────────────────────────────────────────────
    # Drop any legacy columns that don't match the new schema
    expected_cols = [
        "game_id", "player_id",
        "points_avg_last_5",  "points_avg_last_10",
        "rebounds_avg_last_5", "rebounds_avg_last_10",
        "assists_avg_last_5",  "assists_avg_last_10",
        "season_avg_points", "season_avg_rebounds", "season_avg_assists",
        "minutes_avg_last_5", "minutes_avg_last_10", "minutes_trend",
        "games_started_last_5", "minutes_projection",
        "blowout_risk", "blowout_adjustment_factor",
        "team_pace", "opponent_pace", "expected_game_pace", "pace_adjustment_factor",
        "opponent_points_allowed", "opponent_rebounds_allowed", "opponent_assists_allowed",
        "defense_adj_pts", "defense_adj_reb", "defense_adj_ast",
        "usage_proxy", "usage_trend_last_5",
    ]
    features = features[[c for c in expected_cols if c in features.columns]]

    conn.execute("DELETE FROM player_features")
    conn.execute("INSERT INTO player_features SELECT * FROM features")

    n = len(features)
    logger.info(f"  → {n} feature rows written to player_features.")

    if close:
        conn.close()
    return n
