"""
models/minutes_model.py
Improved minutes projection using rolling averages, trend, and blowout risk.

Formula:
    minutes_projection = 0.5 * last_10 + 0.3 * last_5 + 0.2 * trend_adjustment
    trend_adjustment   = last_10_avg + (minutes_trend * 2)

Blowout risk (from sportsbook spreads):
    spread >= 10 → multiply by 0.92
    spread >= 15 → multiply by 0.85

Outputs:
    minutes_avg_last_5, minutes_avg_last_10, minutes_trend,
    games_started_last_5, minutes_projection,
    blowout_risk, blowout_adjustment_factor
"""

import logging
import numpy as np
import pandas as pd

from backend.db.connection import get_connection

logger = logging.getLogger(__name__)

# Blowout thresholds
BLOWOUT_MILD   = 10.0   # spread >= this → 0.92 multiplier
BLOWOUT_HEAVY  = 15.0   # spread >= this → 0.85 multiplier


def rolling_linear_slope(series: pd.Series, window: int = 10) -> pd.Series:
    """
    Compute the linear regression slope over a rolling window.
    Positive slope = player trending toward more minutes.
    Returns a Series of the same length as the input.
    """
    slopes = []
    values = series.values
    for i in range(len(values)):
        start = max(0, i - window + 1)
        chunk = values[start:i + 1]
        if len(chunk) < 2:
            slopes.append(0.0)
        else:
            x = np.arange(len(chunk), dtype=float)
            slope = np.polyfit(x, chunk.astype(float), 1)[0]
            slopes.append(float(slope))
    return pd.Series(slopes, index=series.index)


def get_blowout_spreads(conn) -> dict:
    """
    Returns a dict of {game_id: abs_spread} for upcoming/scheduled games
    where spread data is available from the odds table.
    Uses the average spread across all books for a game.
    """
    try:
        spreads = conn.execute("""
            SELECT game_id, AVG(ABS(home_point)) AS spread
            FROM odds
            WHERE market = 'spreads'
            AND home_point IS NOT NULL
            GROUP BY game_id
        """).df()
        if spreads.empty:
            return {}
        return dict(zip(spreads["game_id"], spreads["spread"]))
    except Exception as e:
        logger.warning(f"Could not load spread data for blowout model: {e}")
        return {}


def build_minutes_features(logs_df: pd.DataFrame, conn=None) -> pd.DataFrame:
    """
    Given a player_game_logs DataFrame (sorted ascending by game_date per player),
    compute improved minutes features and projections.

    Args:
        logs_df: Must contain columns: game_id, player_id, game_date, minutes
        conn:    DuckDB connection (used to fetch spread data for blowout risk)

    Returns DataFrame with columns:
        game_id, player_id,
        minutes_avg_last_5, minutes_avg_last_10, minutes_trend,
        games_started_last_5, minutes_projection,
        blowout_risk, blowout_adjustment_factor
    """
    close = conn is None
    conn = conn or get_connection()

    try:
        blowout_spreads = get_blowout_spreads(conn)
    finally:
        if close:
            conn.close()

    records = []

    for player_id, group in logs_df.groupby("player_id"):
        group = group.sort_values("game_date").reset_index(drop=True)
        mins  = group["minutes"].fillna(0)

        avg_last_5  = mins.rolling(5,  min_periods=1).mean()
        avg_last_10 = mins.rolling(10, min_periods=1).mean()
        trend       = rolling_linear_slope(mins, window=10)

        # games_started proxy: minutes >= 28 treated as "started"
        started     = (mins >= 28).astype(int)
        starts_l5   = started.rolling(5, min_periods=1).sum()

        for i, row in group.iterrows():
            l10   = float(avg_last_10.iloc[i])
            l5    = float(avg_last_5.iloc[i])
            slope = float(trend.iloc[i])

            # Trend adjustment: anchor to L10, push in slope direction
            trend_adj = l10 + (slope * 2)

            # Weighted projection
            proj = (0.5 * l10) + (0.3 * l5) + (0.2 * trend_adj)
            proj = max(proj, 0.0)

            # Blowout risk
            game_id = row["game_id"]
            spread  = blowout_spreads.get(game_id, 0.0)
            if spread >= BLOWOUT_HEAVY:
                blowout_factor = 0.85
                blowout_risk   = "HIGH"
            elif spread >= BLOWOUT_MILD:
                blowout_factor = 0.92
                blowout_risk   = "MODERATE"
            else:
                blowout_factor = 1.0
                blowout_risk   = "NONE"

            proj_adjusted = proj * blowout_factor

            records.append({
                "game_id":                  game_id,
                "player_id":                str(player_id),
                "minutes_avg_last_5":       round(l5, 4),
                "minutes_avg_last_10":      round(l10, 4),
                "minutes_trend":            round(slope, 4),
                "games_started_last_5":     int(starts_l5.iloc[i]),
                "minutes_projection":       round(proj_adjusted, 4),
                "blowout_risk":             blowout_risk,
                "blowout_adjustment_factor": round(blowout_factor, 4),
            })

    return pd.DataFrame(records)
