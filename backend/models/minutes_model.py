"""
models/minutes_model.py
LightGBM-trained minutes projection model.

Replaces the heuristic formula with a trained regression model that learns
optimal weights from historical data.

Features:
    rolling_minutes_last_5, rolling_minutes_last_10
    games_started_last_5, minutes_trend
    spread, pace, home_vs_away, days_rest, back_to_back

Outputs:
    minutes_avg_last_5, minutes_avg_last_10, minutes_trend,
    games_started_last_5, minutes_projection,
    blowout_risk, blowout_adjustment_factor
"""

import logging
import warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=UserWarning)

try:
    import lightgbm as lgb
    HAS_LGB = True
except ImportError:
    HAS_LGB = False

from backend.db.connection import get_connection

logger = logging.getLogger(__name__)

BLOWOUT_MILD   = 10.0
BLOWOUT_HEAVY  = 15.0
MIN_TRAIN_ROWS = 200


def rolling_linear_slope(series: pd.Series, window: int = 10) -> pd.Series:
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


def _heuristic_projection(l10: float, l5: float, slope: float) -> float:
    trend_adj = l10 + (slope * 2)
    return max((0.5 * l10) + (0.3 * l5) + (0.2 * trend_adj), 0.0)


def _get_context_data(conn) -> tuple:
    spreads = {}
    paces = {}
    home_games = {}

    try:
        rows = conn.execute("""
            SELECT game_id, AVG(ABS(home_point)) AS spread
            FROM odds WHERE market = 'spreads' AND home_point IS NOT NULL
            GROUP BY game_id
        """).fetchall()
        spreads = {r[0]: float(r[1]) for r in rows}
    except Exception:
        pass

    try:
        rows = conn.execute("""
            SELECT game_id, AVG(pts) AS avg_pts
            FROM team_game_stats GROUP BY game_id
        """).fetchall()
        paces = {r[0]: float(r[1]) if r[1] else 110.0 for r in rows}
    except Exception:
        pass

    try:
        rows = conn.execute("SELECT game_id, home_team_abbr FROM games").fetchall()
        home_games = {r[0]: r[1] for r in rows}
    except Exception:
        pass

    return spreads, paces, home_games


def _build_training_data(logs_df, spreads, paces, home_games):
    records = []
    for player_id, group in logs_df.groupby("player_id"):
        group = group.sort_values("game_date").reset_index(drop=True)
        mins = group["minutes"].fillna(0)

        avg_l5  = mins.shift(1).rolling(5,  min_periods=1).mean().fillna(0)
        avg_l10 = mins.shift(1).rolling(10, min_periods=1).mean().fillna(0)
        trend   = rolling_linear_slope(mins.shift(1).fillna(0), window=10)
        started = (mins.shift(1).fillna(0) >= 28).astype(int)
        starts_l5 = started.rolling(5, min_periods=1).sum()
        dates = pd.to_datetime(group["game_date"])
        days_rest = dates.diff().dt.days.fillna(3).clip(0, 10)

        for i in range(1, len(group)):
            row = group.iloc[i]
            actual = float(mins.iloc[i])
            if actual <= 0:
                continue
            game_id = row["game_id"]
            team = row.get("team", "")
            home_abbr = home_games.get(game_id, "")
            records.append({
                "minutes_l5":    float(avg_l5.iloc[i]),
                "minutes_l10":   float(avg_l10.iloc[i]),
                "minutes_trend": float(trend.iloc[i]),
                "games_started": float(starts_l5.iloc[i]),
                "spread":        spreads.get(game_id, 5.0),
                "pace":          paces.get(game_id, 110.0),
                "is_home":       1 if team and team == home_abbr else 0,
                "days_rest":     float(days_rest.iloc[i]),
                "back_to_back":  1 if float(days_rest.iloc[i]) <= 1 else 0,
                "target":        actual,
            })
    return pd.DataFrame(records)


def _train_lgb_model(train_df):
    features = ["minutes_l5", "minutes_l10", "minutes_trend",
                "games_started", "spread", "pace", "is_home",
                "days_rest", "back_to_back"]
    X = train_df[features].fillna(0)
    y = train_df["target"]
    params = {
        "objective": "regression", "metric": "rmse",
        "num_leaves": 31, "learning_rate": 0.05,
        "feature_fraction": 0.8, "bagging_fraction": 0.8,
        "bagging_freq": 5, "n_estimators": 300,
        "min_child_samples": 10, "verbose": -1,
    }
    model = lgb.LGBMRegressor(**params)
    model.fit(X, y)
    return model, features


def build_minutes_features(logs_df: pd.DataFrame, conn=None) -> pd.DataFrame:
    close = conn is None
    if close:
        conn = get_connection()
    try:
        spreads, paces, home_games = _get_context_data(conn)
    finally:
        if close:
            conn.close()

    model = None
    feature_names = None

    if HAS_LGB:
        try:
            train_df = _build_training_data(logs_df, spreads, paces, home_games)
            if len(train_df) >= MIN_TRAIN_ROWS:
                model, feature_names = _train_lgb_model(train_df)
                logger.info(f"  LightGBM minutes model trained on {len(train_df):,} samples.")
            else:
                logger.info(f"  Only {len(train_df)} training rows — using heuristic minutes model.")
        except Exception as e:
            logger.warning(f"  LightGBM minutes training failed: {e} — using heuristic.")
            model = None

    records = []
    for player_id, group in logs_df.groupby("player_id"):
        group = group.sort_values("game_date").reset_index(drop=True)
        mins  = group["minutes"].fillna(0)

        avg_l5  = mins.rolling(5,  min_periods=1).mean()
        avg_l10 = mins.rolling(10, min_periods=1).mean()
        trend   = rolling_linear_slope(mins, window=10)
        started = (mins >= 28).astype(int)
        starts_l5 = started.rolling(5, min_periods=1).sum()
        dates = pd.to_datetime(group["game_date"])
        days_rest = dates.diff().dt.days.fillna(3).clip(0, 10)

        for i, row in group.iterrows():
            l10 = float(avg_l10.iloc[i])
            l5  = float(avg_l5.iloc[i])
            slp = float(trend.iloc[i])
            game_id = row["game_id"]
            spread  = spreads.get(game_id, 5.0)
            pace    = paces.get(game_id, 110.0)
            team    = row.get("team", "")
            home_abbr = home_games.get(game_id, "")
            is_home = 1 if team and team == home_abbr else 0
            rest = float(days_rest.iloc[i])
            b2b  = 1 if rest <= 1 else 0

            if model is not None:
                feats = pd.DataFrame([{
                    "minutes_l5": l5, "minutes_l10": l10, "minutes_trend": slp,
                    "games_started": float(starts_l5.iloc[i]),
                    "spread": spread, "pace": pace, "is_home": is_home,
                    "days_rest": rest, "back_to_back": b2b,
                }])
                proj = float(model.predict(feats[feature_names])[0])
                proj = max(proj, 0.0)
            else:
                proj = _heuristic_projection(l10, l5, slp)

            if spread >= BLOWOUT_HEAVY:
                blowout_factor, blowout_risk = 0.85, "HIGH"
            elif spread >= BLOWOUT_MILD:
                blowout_factor, blowout_risk = 0.92, "MODERATE"
            else:
                blowout_factor, blowout_risk = 1.0, "NONE"

            records.append({
                "game_id":                   game_id,
                "player_id":                 str(player_id),
                "minutes_avg_last_5":        round(l5,  4),
                "minutes_avg_last_10":       round(l10, 4),
                "minutes_trend":             round(slp, 4),
                "games_started_last_5":      int(starts_l5.iloc[i]),
                "minutes_projection":        round(proj * blowout_factor, 4),
                "blowout_risk":              blowout_risk,
                "blowout_adjustment_factor": round(blowout_factor, 4),
            })

    return pd.DataFrame(records)
