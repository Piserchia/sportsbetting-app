"""
features/rolling_stats.py
Rolling stat averages (L5, L10, season) for pts/reb/ast/stl/blk.

The rolling stats computation is inline in feature_builder.py (step 2).
This module provides a standalone function for use outside the builder.
"""

import pandas as pd


def compute_rolling_stats(logs: pd.DataFrame) -> pd.DataFrame:
    """
    Compute rolling stat features from game logs.

    Input: DataFrame with columns: game_id, player_id, game_date,
           points, rebounds, assists, steals, blocks
    Output: DataFrame with rolling averages per player-game.
    """
    stat_records = []

    for player_id, player_logs in logs.groupby("player_id"):
        player_logs = player_logs.sort_values("game_date").reset_index(drop=True)

        stats = {}
        for stat, col in [
            ("points", "points"), ("rebounds", "rebounds"), ("assists", "assists"),
            ("steals", "steals"), ("blocks", "blocks"),
        ]:
            series = player_logs[col].fillna(0)
            stats[f"{stat}_avg_last_5"] = series.rolling(5, min_periods=1).mean()
            stats[f"{stat}_avg_last_10"] = series.rolling(10, min_periods=1).mean()
            stats[f"season_avg_{stat}"] = series.expanding().mean()

        for i, row in player_logs.iterrows():
            record = {
                "game_id": row["game_id"],
                "player_id": str(player_id),
            }
            for key, series in stats.items():
                record[key] = round(float(series.iloc[i]), 4)
            stat_records.append(record)

    return pd.DataFrame(stat_records)
