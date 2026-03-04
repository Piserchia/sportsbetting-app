"""
models/feature_builder.py
Builds rolling player features from player_game_logs for use in projections.

Populates: player_features
"""

import logging
import pandas as pd
import numpy as np

from backend.db.connection import get_connection, init_model_schema

logger = logging.getLogger(__name__)


def build_player_features(conn=None) -> int:
    """
    Compute rolling window features for all players and write to player_features.
    Clears and rebuilds the table each run so features stay current.
    """
    close = conn is None
    conn = conn or get_connection()
    init_model_schema(conn)

    logger.info("Loading player_game_logs...")
    logs = conn.execute("""
        SELECT
            pgl.game_id,
            pgl.player_id,
            pgl.game_date,
            pgl.minutes,
            pgl.points,
            pgl.rebounds,
            pgl.assists
        FROM player_game_logs pgl
        ORDER BY pgl.player_id, pgl.game_date ASC
    """).df()

    if logs.empty:
        logger.warning("No player_game_logs found. Run ingest_nba first.")
        if close:
            conn.close()
        return 0

    logger.info(f"Building features for {logs['player_id'].nunique()} players across {len(logs)} game logs...")

    records = []

    for player_id, player_logs in logs.groupby("player_id"):
        player_logs = player_logs.sort_values("game_date").reset_index(drop=True)
        n = len(player_logs)

        # Rolling windows (min_periods=1 so we always get a value even early in season)
        pts = player_logs["points"]
        reb = player_logs["rebounds"]
        ast = player_logs["assists"]
        mins = player_logs["minutes"]

        points_avg_last_5  = pts.rolling(5,  min_periods=1).mean()
        points_avg_last_10 = pts.rolling(10, min_periods=1).mean()
        rebounds_avg_last_10 = reb.rolling(10, min_periods=1).mean()
        assists_avg_last_10  = ast.rolling(10, min_periods=1).mean()
        minutes_avg_last_10  = mins.rolling(10, min_periods=1).mean()

        # Minutes trend: slope of last 10 games (positive = trending up)
        def rolling_slope(series, window=10):
            slopes = []
            for i in range(len(series)):
                start = max(0, i - window + 1)
                chunk = series.iloc[start:i + 1].values
                if len(chunk) < 2:
                    slopes.append(0.0)
                else:
                    x = np.arange(len(chunk))
                    slope = np.polyfit(x, chunk, 1)[0]
                    slopes.append(float(slope))
            return slopes

        minutes_trend = rolling_slope(mins)

        # Season average points (all games up to this point)
        season_avg_points = pts.expanding().mean()

        for i, row in player_logs.iterrows():
            records.append({
                "game_id":              row["game_id"],
                "player_id":            str(player_id),
                "points_avg_last_5":    round(float(points_avg_last_5.iloc[i]), 4),
                "points_avg_last_10":   round(float(points_avg_last_10.iloc[i]), 4),
                "rebounds_avg_last_10": round(float(rebounds_avg_last_10.iloc[i]), 4),
                "assists_avg_last_10":  round(float(assists_avg_last_10.iloc[i]), 4),
                "minutes_avg_last_10":  round(float(minutes_avg_last_10.iloc[i]), 4),
                "minutes_trend":        round(float(minutes_trend[i]), 4),
                "season_avg_points":    round(float(season_avg_points.iloc[i]), 4),
            })

    if not records:
        logger.warning("No feature records generated.")
        if close:
            conn.close()
        return 0

    features_df = pd.DataFrame(records)

    # Clear and rewrite
    conn.execute("DELETE FROM player_features")
    conn.execute("INSERT INTO player_features SELECT * FROM features_df")

    logger.info(f"  → {len(features_df)} feature rows written to player_features.")
    if close:
        conn.close()
    return len(features_df)
