"""
models/stat_models.py
LightGBM regression models for points, rebounds, and assists.

Replaces the static weighted-average formula:
    base = 0.5 * L10 + 0.3 * L5 + 0.2 * season_avg

Each stat gets its own model with features:
    minutes_projection, usage_proxy,
    rolling_stats (L5, L10, season),
    pace_adjustment_factor, defense_adj_*,
    spread, team_total, home_away,
    days_rest, is_back_to_back

Training: fit on all completed games in player_features joined to
          player_game_logs (actuals as targets)

Falls back to the original weighted-average formula when fewer than
MIN_TRAIN_ROWS training samples are available.
"""

from __future__ import annotations

import logging
import warnings
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

MIN_TRAIN_ROWS = 300

_MODEL_CACHE: dict = {}   # {"points": model, "rebounds": model, "assists": model}

STAT_FEATURES = {
    "points": [
        "minutes_projection",
        "points_avg_last_5",
        "points_avg_last_10",
        "season_avg_points",
        "usage_proxy",
        "pace_adjustment_factor",
        "defense_adj_pts",
        "spread",
        "team_total",
        "is_home",
        "days_rest",
        "is_back_to_back",
        "games_started_last_5",
    ],
    "rebounds": [
        "minutes_projection",
        "rebounds_avg_last_5",
        "rebounds_avg_last_10",
        "season_avg_rebounds",
        "pace_adjustment_factor",
        "defense_adj_reb",
        "spread",
        "is_home",
        "days_rest",
        "is_back_to_back",
        "games_started_last_5",
    ],
    "assists": [
        "minutes_projection",
        "assists_avg_last_5",
        "assists_avg_last_10",
        "season_avg_assists",
        "usage_proxy",
        "pace_adjustment_factor",
        "defense_adj_ast",
        "spread",
        "team_total",
        "is_home",
        "days_rest",
        "is_back_to_back",
        "games_started_last_5",
    ],
}


def _train_lgbm(X: pd.DataFrame, y: pd.Series, stat: str):
    """Train one LightGBM regressor for a given stat."""
    import lightgbm as lgb

    params = {
        "objective":        "regression_l1",
        "metric":           "mae",
        "learning_rate":    0.04,
        "num_leaves":       63,
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
    logger.info(
        f"    [{stat}] trained on {len(X):,} rows  "
        f"best_iter={model.best_iteration}"
    )
    return model


def _weighted_avg_fallback(
    features_df: pd.DataFrame, stat: str
) -> np.ndarray:
    """Original formula as fallback."""
    l10_col = f"{stat}s_avg_last_10" if stat != "assists" else "assists_avg_last_10"
    l5_col  = f"{stat}s_avg_last_5"  if stat != "assists" else "assists_avg_last_5"
    sea_col = f"season_avg_{stat}s"  if stat != "assists" else "season_avg_assists"

    # normalise column names to what's actually in the df
    col_map = {
        "points_avg_last_10":   "points_avg_last_10",
        "points_avg_last_5":    "points_avg_last_5",
        "season_avg_points":    "season_avg_points",
        "rebounds_avg_last_10": "rebounds_avg_last_10",
        "rebounds_avg_last_5":  "rebounds_avg_last_5",
        "season_avg_rebounds":  "season_avg_rebounds",
        "assists_avg_last_10":  "assists_avg_last_10",
        "assists_avg_last_5":   "assists_avg_last_5",
        "season_avg_assists":   "season_avg_assists",
    }

    l10 = features_df.get(f"{stat}_avg_last_10",
          features_df.get(f"{stat}s_avg_last_10", pd.Series(0.0, index=features_df.index)))
    l5  = features_df.get(f"{stat}_avg_last_5",
          features_df.get(f"{stat}s_avg_last_5",  pd.Series(0.0, index=features_df.index)))
    sea = features_df.get(f"season_avg_{stat}",
          features_df.get(f"season_avg_{stat}s",  pd.Series(0.0, index=features_df.index)))

    base = 0.5 * l10 + 0.3 * l5 + 0.2 * sea

    # context adjustments
    pace = features_df.get("pace_adjustment_factor",
                           pd.Series(1.0, index=features_df.index)).fillna(1.0)
    def_adj = features_df.get(f"defense_adj_{stat[:3]}",
                              pd.Series(1.0, index=features_df.index)).fillna(1.0)
    usage_adj = pd.Series(1.0, index=features_df.index)
    if stat == "points":
        usage = features_df.get("usage_proxy",
                                pd.Series(0.2, index=features_df.index)).fillna(0.2)
        usage_adj = (usage / 0.20).clip(0.85, 1.15)

    return np.clip((base * pace * def_adj * usage_adj).values, 0.0, None)


def _enrich_with_game_context(
    features_df: pd.DataFrame,
    conn,
) -> pd.DataFrame:
    """
    Add game-level context columns not already in player_features:
        spread, team_total, is_home, days_rest, is_back_to_back
    """
    # Spread and team_total from odds
    try:
        odds = conn.execute("""
            SELECT
                game_id,
                AVG(ABS(home_point))    AS spread,
                AVG(CASE WHEN market = 'totals' THEN home_point END) AS team_total
            FROM odds
            WHERE home_point IS NOT NULL
            GROUP BY game_id
        """).df()
        spread_map = dict(zip(odds["game_id"], odds["spread"]))
        total_map  = dict(zip(odds["game_id"], odds["team_total"]))
    except Exception:
        spread_map, total_map = {}, {}

    # Home/away + rest from player_game_logs
    try:
        rest_df = conn.execute("""
            SELECT
                pgl.player_id,
                pgl.game_id,
                pgl.game_date,
                g.home_team_id,
                pgs.team_id
            FROM player_game_logs pgl
            JOIN games g ON pgl.game_id = g.game_id
            JOIN player_game_stats pgs
              ON pgl.game_id = pgs.game_id
             AND CAST(pgs.player_id AS TEXT) = pgl.player_id
        """).df()

        rest_df["game_date"] = pd.to_datetime(rest_df["game_date"])
        rest_df = rest_df.sort_values(["player_id", "game_date"])
        rest_df["days_rest"] = rest_df.groupby("player_id")["game_date"].diff().dt.days.fillna(3).clip(upper=10)
        rest_df["is_back_to_back"] = (rest_df["days_rest"] <= 1).astype(int)
        rest_df["is_home"] = (
            rest_df["team_id"].astype(str) == rest_df["home_team_id"].astype(str)
        ).astype(int)

        ctx = rest_df[["game_id", "player_id", "days_rest", "is_back_to_back", "is_home"]].copy()
        ctx["player_id"] = ctx["player_id"].astype(str)
    except Exception as e:
        logger.warning(f"  Could not build game context: {e}")
        ctx = pd.DataFrame(columns=["game_id", "player_id", "days_rest", "is_back_to_back", "is_home"])

    df = features_df.copy()
    df["player_id"] = df["player_id"].astype(str)

    if not ctx.empty:
        df = df.merge(ctx, on=["game_id", "player_id"], how="left")

    df["spread"]         = df["game_id"].map(spread_map).fillna(0.0)
    df["team_total"]     = df["game_id"].map(total_map).fillna(220.0)
    df["is_home"]        = df.get("is_home",        pd.Series(0, index=df.index)).fillna(0).astype(int)
    df["days_rest"]      = df.get("days_rest",      pd.Series(3.0, index=df.index)).fillna(3.0)
    df["is_back_to_back"]= df.get("is_back_to_back",pd.Series(0,   index=df.index)).fillna(0).astype(int)

    return df


def generate_ml_projections(conn=None, force_retrain: bool = False) -> pd.DataFrame:
    """
    Train (or reuse cached) LightGBM models for points/rebounds/assists
    and produce projections for every player's latest feature row.

    Returns a DataFrame with columns:
        game_id, player_id, points_mean, rebounds_mean, assists_mean,
        minutes_projection
    """
    from backend.db.connection import get_connection as _get_conn
    close = conn is None
    conn  = conn or _get_conn()

    try:
        logger.info("Loading player_features for ML projections...")
        features_df = conn.execute("SELECT * FROM player_features").df()

        if features_df.empty:
            logger.warning("No player_features — run build_features first.")
            return pd.DataFrame()

        # Enrich with game context (spread, totals, home/away, rest)
        logger.info("  Enriching features with game context...")
        features_df = _enrich_with_game_context(features_df, conn)

        # Join actuals from player_game_logs for training
        logger.info("  Loading actuals for training...")
        actuals = conn.execute("""
            SELECT game_id, player_id, points, rebounds, assists
            FROM player_game_logs
        """).df()
        actuals["player_id"] = actuals["player_id"].astype(str)

        train_df = features_df.merge(actuals, on=["game_id", "player_id"], how="inner")

    finally:
        if close:
            conn.close()

    # ── Get the latest row per player for inference ───────────────────────
    latest = (
        features_df
        .sort_values("game_id", ascending=False)
        .drop_duplicates(subset=["player_id"])
        .copy()
    )

    result = latest[["game_id", "player_id"]].copy()
    result["minutes_projection"] = latest.get(
        "minutes_projection",
        latest.get("minutes_avg_last_10", pd.Series(20.0, index=latest.index))
    ).fillna(0.0).values

    for stat in ["points", "rebounds", "assists"]:
        feat_cols = STAT_FEATURES[stat]
        available = [c for c in feat_cols if c in train_df.columns]

        X_all   = features_df[available].fillna(0.0)
        X_train_df = train_df[available].fillna(0.0)

        target_col = f"{stat}s" if stat != "assists" else "assists"
        # player_game_logs uses: points, rebounds, assists (no trailing s on assists)
        actual_col = stat  # points, rebounds, assists
        if actual_col not in train_df.columns:
            actual_col = stat + "s"

        y_train = train_df.get(actual_col, train_df.get(stat, None))

        if y_train is None:
            logger.warning(f"  No actuals for {stat} — using fallback")
            result[f"{stat}_mean"] = _weighted_avg_fallback(latest, stat)
            continue

        use_lgbm = len(X_train_df) >= MIN_TRAIN_ROWS

        if use_lgbm and (force_retrain or stat not in _MODEL_CACHE):
            logger.info(f"  Training LightGBM [{stat}] on {len(X_train_df):,} rows...")
            try:
                model = _train_lgbm(X_train_df, y_train, stat)
                _MODEL_CACHE[stat] = model
            except Exception as e:
                logger.warning(f"  [{stat}] LightGBM failed: {e} — fallback")
                use_lgbm = False

        X_latest = latest[available].fillna(0.0)

        if use_lgbm and stat in _MODEL_CACHE:
            preds = _MODEL_CACHE[stat].predict(X_latest)
            result[f"{stat}_mean"] = np.clip(preds, 0.0, None).round(4)
            logger.info(f"  [{stat}] projections via LightGBM.")
        else:
            result[f"{stat}_mean"] = _weighted_avg_fallback(latest, stat)
            logger.info(f"  [{stat}] projections via weighted-average fallback.")

    result = result.rename(columns={
        "points_mean":   "points_mean",
        "rebounds_mean": "rebounds_mean",
        "assists_mean":  "assists_mean",
    })

    # Ensure all output columns exist
    for col in ["points_mean", "rebounds_mean", "assists_mean"]:
        if col not in result.columns:
            result[col] = 0.0

    return result[["game_id", "player_id", "points_mean", "rebounds_mean",
                   "assists_mean", "minutes_projection"]]


def get_feature_importances() -> dict[str, pd.DataFrame]:
    """Return feature importances for each trained stat model."""
    out = {}
    for stat, model in _MODEL_CACHE.items():
        if stat in ("points", "rebounds", "assists"):
            feats = STAT_FEATURES[stat]
            imps  = model.feature_importance(importance_type="gain")
            out[stat] = pd.DataFrame({
                "feature":    feats[:len(imps)],
                "importance": imps,
            }).sort_values("importance", ascending=False)
    return out
