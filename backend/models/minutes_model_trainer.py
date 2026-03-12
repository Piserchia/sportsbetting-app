"""
models/minutes_model_trainer.py
Dedicated LightGBM training module for minutes projection.

Expanded feature set (15 features):
    minutes_avg_last_5, minutes_avg_last_10, minutes_trend,
    games_started_last_5, rotation_players_last_5,
    usage_proxy, team_pace, opponent_pace, pace_adjustment_factor,
    spread, team_total, is_home, days_rest, is_back_to_back,
    injury_usage_boost

Tuned hyperparameters:
    objective: regression_l2, metric: rmse
    learning_rate: 0.03, num_leaves: 64
    600 rounds with early stopping at 50
"""

from __future__ import annotations

import logging
import pickle
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

MODEL_PATH = Path(__file__).parent.parent.parent / "data" / "models" / "minutes_lgbm.pkl"
MIN_TRAIN_ROWS = 300

FEATURES = [
    "minutes_avg_last_5",
    "minutes_avg_last_10",
    "minutes_trend",
    "games_started_last_5",
    "rotation_players_last_5",
    "usage_proxy",
    "team_pace",
    "opponent_pace",
    "pace_adjustment_factor",
    "spread",
    "team_total",
    "is_home",
    "days_rest",
    "is_back_to_back",
    "injury_usage_boost",
]


def _build_training_data(conn) -> pd.DataFrame:
    """
    Build training data by joining player_features with player_game_logs.
    Computes rotation depth and injury boost features.
    """
    df = conn.execute("""
        SELECT
            pf.game_id,
            pf.player_id,
            pf.minutes_avg_last_5,
            pf.minutes_avg_last_10,
            pf.minutes_trend,
            pf.games_started_last_5,
            pf.usage_proxy,
            pf.team_pace,
            pf.opponent_pace,
            pf.pace_adjustment_factor,
            pgl.minutes AS actual_minutes,
            pgl.game_date,
            pgs.team_id,
            g.home_team_id
        FROM player_features pf
        JOIN player_game_logs pgl
          ON pf.game_id = pgl.game_id AND pf.player_id = pgl.player_id
        JOIN games g ON pf.game_id = g.game_id
        JOIN player_game_stats pgs
          ON pf.game_id = pgs.game_id
         AND CAST(pgs.player_id AS TEXT) = pf.player_id
        WHERE pgl.minutes IS NOT NULL AND pgl.minutes > 0
    """).df()

    if df.empty:
        return df

    # Spread and team total from odds
    try:
        odds = conn.execute("""
            SELECT
                game_id,
                AVG(ABS(home_point)) AS spread,
                AVG(CASE WHEN market = 'totals' THEN home_point END) AS team_total
            FROM odds
            WHERE home_point IS NOT NULL
            GROUP BY game_id
        """).df()
        spread_map = dict(zip(odds["game_id"], odds["spread"]))
        total_map  = dict(zip(odds["game_id"], odds["team_total"]))
    except Exception:
        spread_map, total_map = {}, {}

    df["spread"]     = df["game_id"].map(spread_map).fillna(0.0)
    df["team_total"] = df["game_id"].map(total_map).fillna(220.0)

    # Home/away and rest
    df["game_date"] = pd.to_datetime(df["game_date"])
    df = df.sort_values(["player_id", "game_date"])
    df["days_rest"] = (
        df.groupby("player_id")["game_date"].diff().dt.days.fillna(3).clip(upper=10)
    )
    df["is_back_to_back"] = (df["days_rest"] <= 1).astype(int)
    df["is_home"] = (
        df["team_id"].astype(str) == df["home_team_id"].astype(str)
    ).astype(int)

    # Rotation depth: count players with >= 15 min per team per game (rolling 5-game avg)
    try:
        rotation = conn.execute("""
            SELECT
                g.game_id,
                pgs.team_id,
                COUNT(DISTINCT pgs.player_id) AS rotation_count
            FROM player_game_stats pgs
            JOIN games g ON pgs.game_id = g.game_id
            WHERE CAST(pgs.min AS DOUBLE) >= 15.0
              AND pgs.min IS NOT NULL
            GROUP BY g.game_id, pgs.team_id
        """).df()
        rotation["team_id"] = rotation["team_id"].astype(str)
        rot_map = {}
        for _, r in rotation.iterrows():
            rot_map[(r["game_id"], r["team_id"])] = float(r["rotation_count"])
        df["rotation_players_last_5"] = df.apply(
            lambda r: rot_map.get((r["game_id"], str(r["team_id"])), 8.0), axis=1
        )
    except Exception as e:
        logger.warning(f"Could not compute rotation depth: {e}")
        df["rotation_players_last_5"] = 8.0

    # Injury usage boost
    try:
        from backend.ingestion.injury_lineup_ingestor import get_teammate_injury_multipliers
        injury_mult = get_teammate_injury_multipliers(conn)
        df["injury_usage_boost"] = df["player_id"].map(
            lambda pid: injury_mult.get(str(pid), 1.0)
        )
    except Exception:
        df["injury_usage_boost"] = 1.0

    # Fill missing feature columns
    for col in FEATURES:
        if col not in df.columns:
            df[col] = 0.0

    return df


def train(conn=None, force: bool = False) -> bool:
    """Train and save the enhanced minutes LightGBM model."""
    if MODEL_PATH.exists() and not force:
        logger.info(f"Model already exists at {MODEL_PATH}. Use --force to retrain.")
        return False

    from backend.db.connection import get_connection, init_model_schema
    close = conn is None
    conn  = conn or get_connection()
    init_model_schema(conn)

    try:
        logger.info("Building enhanced minutes training data...")
        df = _build_training_data(conn)
    finally:
        if close:
            conn.close()

    if df.empty or len(df) < MIN_TRAIN_ROWS:
        logger.warning(
            f"Insufficient training data ({len(df)} rows, need {MIN_TRAIN_ROWS}). "
            "Run the ingestion pipeline first."
        )
        return False

    available = [c for c in FEATURES if c in df.columns]
    X = df[available].fillna(0.0)
    y = df["actual_minutes"]

    logger.info(f"Training LightGBM minutes model on {len(X):,} rows, {len(available)} features...")

    try:
        import lightgbm as lgb
    except ImportError:
        logger.error("lightgbm not installed. Run: pip install lightgbm")
        return False

    params = {
        "objective":        "regression_l2",
        "metric":           "rmse",
        "learning_rate":    0.03,
        "num_leaves":       64,
        "min_data_in_leaf": 25,
        "feature_fraction": 0.85,
        "bagging_fraction": 0.9,
        "bagging_freq":     5,
        "verbose":          -1,
        "n_jobs":           -1,
        "seed":             42,
    }

    # 80/20 chronological split for validation
    split = int(len(X) * 0.80)
    X_train, X_val = X.iloc[:split], X.iloc[split:]
    y_train, y_val = y.iloc[:split], y.iloc[split:]

    dtrain = lgb.Dataset(X_train, label=y_train)
    dval   = lgb.Dataset(X_val,   label=y_val, reference=dtrain)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = lgb.train(
            params, dtrain, num_boost_round=600,
            valid_sets=[dval],
            callbacks=[lgb.early_stopping(50, verbose=False), lgb.log_evaluation(-1)],
        )

    logger.info(f"  best_iteration={model.best_iteration}")

    # Feature importances
    imps = model.feature_importance(importance_type="gain")
    for feat, imp in sorted(zip(available, imps), key=lambda x: -x[1]):
        logger.info(f"    {feat:30s}  gain={imp:.1f}")

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MODEL_PATH, "wb") as f:
        pickle.dump({"model": model, "features": available}, f)

    logger.info(f"Model saved to {MODEL_PATH}")
    return True
