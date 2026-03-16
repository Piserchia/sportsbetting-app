"""
features/rolling_stats.py
Rolling stat features: EWMA-based recent_adj, L10, and season averages
for pts/reb/ast/stl/blk.

EWMA windows exclude the current game to prevent target leakage.
The rolling stats computation is inline in feature_builder.py (step 2).
This module provides a standalone function for use outside the builder.
"""

import logging
import pandas as pd

logger = logging.getLogger(__name__)

EWMA_WEIGHTS = [0.40, 0.25, 0.15, 0.10, 0.06, 0.04]
DELTA_CLIP = 6.0


def _ewma_series(series: pd.Series) -> pd.Series:
    """Compute EWMA at each position using up to 6 PRIOR games (excludes current)."""
    result = []
    for idx in range(len(series)):
        end = idx  # exclude current game
        if end <= 0:
            result.append(None)
            continue
        start = max(0, end - len(EWMA_WEIGHTS))
        window = series.iloc[start:end].values[::-1]
        weights = EWMA_WEIGHTS[:len(window)]
        w_sum = sum(weights)
        result.append(sum(w * float(v) for w, v in zip(weights, window)) / w_sum)
    return pd.Series(result, index=series.index)


def compute_rolling_stats(logs: pd.DataFrame) -> pd.DataFrame:
    """
    Compute rolling stat features from game logs.

    Input: DataFrame with columns: game_id, player_id, game_date,
           points, rebounds, assists, steals, blocks
    Output: DataFrame with EWMA-adjusted, L10, and season averages per player-game.

    All features use only PRIOR games (no leakage from the current game).
    """
    stat_records = []

    for player_id, player_logs in logs.groupby("player_id"):
        player_logs = player_logs.sort_values("game_date").reset_index(drop=True)

        stats_by_game = {}
        for stat, col in [
            ("points", "points"), ("rebounds", "rebounds"), ("assists", "assists"),
            ("steals", "steals"), ("blocks", "blocks"),
        ]:
            series = player_logs[col].fillna(0)
            ewma = _ewma_series(series)
            # shift(1) excludes current game
            l10 = series.shift(1).rolling(10, min_periods=1).mean()
            season = series.shift(1).expanding().mean()

            for i in range(len(player_logs)):
                gid = player_logs.iloc[i]["game_id"]
                if gid not in stats_by_game:
                    stats_by_game[gid] = {"game_id": gid, "player_id": str(player_id)}

                ewma_val = ewma.iloc[i]
                season_val = season.iloc[i]
                l10_val = l10.iloc[i]

                if ewma_val is None or pd.isna(season_val):
                    stats_by_game[gid][f"{stat}_recent_adj"] = 0.0
                    stats_by_game[gid][f"{stat}_avg_last_10"] = 0.0 if pd.isna(l10_val) else round(float(l10_val), 4)
                    stats_by_game[gid][f"season_avg_{stat}"] = 0.0 if pd.isna(season_val) else round(float(season_val), 4)
                else:
                    delta = ewma_val - season_val
                    clipped = max(-DELTA_CLIP, min(DELTA_CLIP, delta))
                    stats_by_game[gid][f"{stat}_recent_adj"] = round(season_val + clipped, 4)
                    stats_by_game[gid][f"{stat}_avg_last_10"] = round(float(l10_val), 4) if not pd.isna(l10_val) else 0.0
                    stats_by_game[gid][f"season_avg_{stat}"] = round(float(season_val), 4)

        stat_records.extend(stats_by_game.values())

    return pd.DataFrame(stat_records)
