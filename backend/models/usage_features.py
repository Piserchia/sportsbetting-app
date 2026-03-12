"""
models/usage_features.py
Computes usage rate proxy from box score data.

True usage rate requires play-by-play data. Box score approximation:
    usage_proxy = (FGA + 0.44*FTA + TOV) / team_possessions

Also computes usage_trend_last_5 as the rolling slope of usage_proxy.

Outputs fields added to player_features:
    usage_proxy, usage_trend_last_5
"""

import logging
import numpy as np
import pandas as pd

from backend.database.connection import get_connection

logger = logging.getLogger(__name__)


def build_usage_features(conn=None) -> pd.DataFrame:
    """
    Compute per-player usage proxy and trend for every game.

    Returns DataFrame with columns:
        game_id, player_id, usage_proxy, usage_trend_last_5
    """
    close = conn is None
    conn = conn or get_connection()

    try:
        # Player box scores with shooting stats
        players = conn.execute("""
            SELECT
                pgs.game_id,
                CAST(pgs.player_id AS TEXT) AS player_id,
                pgs.team_id,
                g.game_date,
                COALESCE(pgs.fga, 0)  AS fga,
                COALESCE(pgs.fta, 0)  AS fta,
                COALESCE(pgs.tov, 0)  AS tov
            FROM player_game_stats pgs
            JOIN games g ON pgs.game_id = g.game_id
            WHERE pgs.pts IS NOT NULL
        """).df()

        if players.empty:
            logger.warning("No player stats for usage features.")
            return pd.DataFrame()

        # Team possessions per game (reuse pace formula)
        team_poss = conn.execute("""
            SELECT
                tgs.game_id,
                tgs.team_id,
                (COALESCE(tgs.fga, 0) + 0.44 * COALESCE(tgs.fta, 0) + COALESCE(tgs.tov, 0)) AS possessions
            FROM team_game_stats tgs
            WHERE tgs.fga IS NOT NULL
        """).df()

        if team_poss.empty:
            logger.warning("No team stats for usage features — usage_proxy will be null.")
            return pd.DataFrame()

        # Merge team possessions onto player rows
        merged = players.merge(
            team_poss.rename(columns={"possessions": "team_possessions"}),
            on=["game_id", "team_id"],
            how="left"
        )

        merged["team_possessions"] = merged["team_possessions"].fillna(90.0)  # fallback

        # Usage proxy per game
        merged["usage_raw"] = (
            merged["fga"] + 0.44 * merged["fta"] + merged["tov"]
        ) / merged["team_possessions"].clip(lower=1)

        # Rolling usage trend (slope over last 5)
        records = []
        for player_id, group in merged.groupby("player_id"):
            group = group.sort_values("game_date").reset_index(drop=True)
            usage = group["usage_raw"]

            rolling_usage = usage.rolling(5, min_periods=1).mean()

            # Trend: slope of usage over last 5 games
            trends = []
            for i in range(len(usage)):
                start = max(0, i - 4)
                chunk = usage.iloc[start:i + 1].values
                if len(chunk) < 2:
                    trends.append(0.0)
                else:
                    x = np.arange(len(chunk), dtype=float)
                    slope = np.polyfit(x, chunk.astype(float), 1)[0]
                    trends.append(float(slope))

            for i, row in group.iterrows():
                records.append({
                    "game_id":           row["game_id"],
                    "player_id":         str(player_id),
                    "usage_proxy":       round(float(rolling_usage.iloc[i]), 4),
                    "usage_trend_last_5": round(float(trends[i]), 4),
                })

        return pd.DataFrame(records)

    finally:
        if close:
            conn.close()
