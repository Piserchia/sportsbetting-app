#!/usr/bin/env python3
"""
scripts/train_minutes_model.py
Train a LightGBM model to predict player minutes played.

The trained model is saved to data/models/minutes_lgbm.pkl and is
automatically picked up by minutes_model.py on the next pipeline run.

Features used:
    minutes_avg_last_5, minutes_avg_last_10, minutes_trend,
    games_started_last_5, spread, pace_adjustment_factor,
    is_home, days_rest, is_back_to_back

Usage:
    python scripts/train_minutes_model.py
    python scripts/train_minutes_model.py --force   # retrain even if model exists
"""

from __future__ import annotations

import argparse
import logging
import os
import pickle
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.logging_config import setup_logging
from backend.db.connection import get_connection, init_model_schema

setup_logging()
logger = logging.getLogger(__name__)

MODEL_PATH    = Path(__file__).parent.parent / "data" / "models" / "minutes_lgbm.pkl"
MIN_TRAIN_ROWS = 300

FEATURES = [
    "minutes_avg_last_5",
    "minutes_avg_last_10",
    "minutes_trend",
    "games_started_last_5",
    "spread",
    "pace_adjustment_factor",
    "is_home",
    "days_rest",
    "is_back_to_back",
]


def _build_training_data(conn) -> pd.DataFrame:
    """
    Join player_features with player_game_logs to get training rows.
    Target: actual minutes played.
    Context features come from player_features + odds/games joins.
    """
    df = conn.execute("""
        SELECT
            pf.game_id,
            pf.player_id,
            pf.minutes_avg_last_5,
            pf.minutes_avg_last_10,
            pf.minutes_trend,
            pf.games_started_last_5,
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

    # Spread from odds table
    try:
        odds = conn.execute("""
            SELECT game_id, AVG(ABS(home_point)) AS spread
            FROM odds
            WHERE market = 'spreads' AND home_point IS NOT NULL
            GROUP BY game_id
        """).df()
        spread_map = dict(zip(odds["game_id"], odds["spread"]))
    except Exception:
        spread_map = {}

    df["spread"] = df["game_id"].map(spread_map).fillna(0.0)

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

    return df


def train(conn=None, force: bool = False) -> bool:
    """
    Train and save the minutes LightGBM model.
    Returns True if a model was trained and saved.
    """
    if MODEL_PATH.exists() and not force:
        logger.info(f"Model already exists at {MODEL_PATH}. Use --force to retrain.")
        return False

    close = conn is None
    conn  = conn or get_connection()
    init_model_schema(conn)

    try:
        logger.info("Building minutes training data...")
        df = _build_training_data(conn)
    finally:
        if close:
            conn.close()

    if df.empty or len(df) < MIN_TRAIN_ROWS:
        logger.warning(
            f"Insufficient training data ({len(df)} rows, need {MIN_TRAIN_ROWS}). "
            "Run the ingestion pipeline first to populate player_features."
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
        "objective":        "regression_l1",
        "metric":           "mae",
        "learning_rate":    0.04,
        "num_leaves":       31,
        "min_data_in_leaf": 20,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.85,
        "bagging_freq":     5,
        "lambda_l1":        0.1,
        "lambda_l2":        0.1,
        "verbose":          -1,
        "n_jobs":           -1,
        "seed":             42,
    }

    dtrain = lgb.Dataset(X, label=y)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = lgb.train(
            params, dtrain, num_boost_round=400,
            valid_sets=[dtrain],
            callbacks=[lgb.early_stopping(40, verbose=False), lgb.log_evaluation(-1)],
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Retrain even if model exists")
    args = parser.parse_args()

    conn = get_connection()
    success = train(conn=conn, force=args.force)
    conn.close()
    if success:
        print(f"✅ Minutes model trained and saved to {MODEL_PATH}")
    else:
        print("⚠️  Model not trained — check logs for details.")
