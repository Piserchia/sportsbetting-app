"""
models/stat_models.py
LightGBM regression models for points, rebounds, assists, steals, and blocks.

Position-specific models: trains separate models per position group
(Guard=PG/SG, Forward=SF/PF, Center=C) for each stat, reducing bias
from pooling players with different stat distributions.

Each stat gets its own model with features:
    minutes_projection, usage_proxy,
    rolling_stats (L5, L10, season),
    pace_adjustment_factor, defense_adj_*,
    spread, team_total, home_away,
    days_rest, is_back_to_back

Training: fit on all completed games in player_features joined to
          player_game_logs (actuals as targets)

Falls back to:
  1. All-positions model when a position group has too few rows
  2. Weighted-average formula when total data is insufficient
"""

from __future__ import annotations

import logging
import warnings
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

MIN_TRAIN_ROWS = 300
MIN_POSITION_ROWS = 150  # minimum rows to train a position-specific model

POSITION_GROUPS = {
    "Guard":   ["PG", "SG", "G", "G-F"],
    "Forward": ["SF", "PF", "F", "F-G", "F-C"],
    "Center":  ["C", "C-F"],
}

def _get_position_group(pos: str) -> str:
    """Map a position string to Guard/Forward/Center group."""
    if not pos or str(pos).strip() == "":
        return "Forward"
    pos = str(pos).strip().upper()
    for group, positions in POSITION_GROUPS.items():
        if pos in positions:
            return group
    return "Forward"

# Cache keyed by (stat, position_group) or (stat, "all") for all-positions fallback
_MODEL_CACHE: dict = {}

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
    "steals": [
        "minutes_projection",
        "steals_avg_last_5",
        "steals_avg_last_10",
        "season_avg_steals",
        "pace_adjustment_factor",
        "defense_adj_stl",
        "is_home",
        "days_rest",
        "is_back_to_back",
        "games_started_last_5",
    ],
    "blocks": [
        "minutes_projection",
        "blocks_avg_last_5",
        "blocks_avg_last_10",
        "season_avg_blocks",
        "pace_adjustment_factor",
        "defense_adj_blk",
        "is_home",
        "days_rest",
        "is_back_to_back",
        "games_started_last_5",
    ],
}


def _train_lgbm(X: pd.DataFrame, y: pd.Series, stat: str):
    """Train one LightGBM regressor for a given stat.

    Uses the most recent 20% of rows as a validation set (chronological
    split) so early stopping evaluates on held-out data.
    """
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

    split = int(len(X) * 0.80)
    X_train, X_val = X.iloc[:split], X.iloc[split:]
    y_train, y_val = y.iloc[:split], y.iloc[split:]

    dtrain = lgb.Dataset(X_train, label=y_train)
    dval   = lgb.Dataset(X_val,   label=y_val, reference=dtrain)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = lgb.train(
            params, dtrain, num_boost_round=400,
            valid_sets=[dval],
            callbacks=[lgb.early_stopping(40, verbose=False), lgb.log_evaluation(-1)],
        )
    logger.info(
        f"    [{stat}] trained on {len(X_train):,} rows, "
        f"validated on {len(X_val):,}  best_iter={model.best_iteration}"
    )
    return model


def _weighted_avg_fallback(
    features_df: pd.DataFrame, stat: str
) -> np.ndarray:
    """Original formula as fallback.
    Supports: points, rebounds, assists, steals, blocks.
    """
    # steals/blocks use singular column names; others use plural (e.g. rebounds_avg_last_5)
    singular_stats = {"assists", "steals", "blocks"}
    if stat in singular_stats:
        l10_col = f"{stat}_avg_last_10"
        l5_col  = f"{stat}_avg_last_5"
        sea_col = f"season_avg_{stat}"
    else:
        l10_col = f"{stat}s_avg_last_10"
        l5_col  = f"{stat}s_avg_last_5"
        sea_col = f"season_avg_{stat}s"

    l10 = features_df.get(l10_col, pd.Series(0.0, index=features_df.index))
    l5  = features_df.get(l5_col,  pd.Series(0.0, index=features_df.index))
    sea = features_df.get(sea_col, pd.Series(0.0, index=features_df.index))

    base = 0.5 * l10 + 0.3 * l5 + 0.2 * sea

    # context adjustments
    pace = features_df.get("pace_adjustment_factor",
                           pd.Series(1.0, index=features_df.index)).fillna(1.0)
    # defense_adj column: defense_adj_pts/reb/ast/stl/blk
    _def_suffix = {"points": "pts", "rebounds": "reb", "assists": "ast",
                   "steals": "stl", "blocks": "blk"}.get(stat, stat[:3])
    def_adj = features_df.get(f"defense_adj_{_def_suffix}",
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


def compute_shap_contributions(model, X_row, feature_names):
    """Compute SHAP feature contributions for a single prediction row."""
    try:
        import shap
        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(X_row)
        if len(shap_values.shape) == 1:
            vals = shap_values
        else:
            vals = shap_values[0]
        return dict(zip(feature_names, [float(v) for v in vals]))
    except Exception:
        return {}


def generate_ml_projections(conn=None, force_retrain: bool = False) -> pd.DataFrame:
    """
    Train (or reuse cached) LightGBM models for points/rebounds/assists
    and produce projections for every player's latest feature row.

    Returns a DataFrame with columns:
        game_id, player_id, points_mean, rebounds_mean, assists_mean,
        minutes_projection
    """
    from backend.database.connection import get_connection as _get_conn
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
            SELECT game_id, player_id, points, rebounds, assists, steals, blocks
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

    # Add position group to training data and latest for position-specific models
    if "player_position" in train_df.columns:
        train_df["position_group"] = train_df["player_position"].apply(_get_position_group)
    else:
        train_df["position_group"] = "Forward"

    if "player_position" in latest.columns:
        latest["position_group"] = latest["player_position"].apply(_get_position_group)
    else:
        latest["position_group"] = "Forward"

    for stat in ["points", "rebounds", "assists", "steals", "blocks"]:
        feat_cols = STAT_FEATURES[stat]
        available = [c for c in feat_cols if c in train_df.columns]

        # player_game_logs column name for this stat
        actual_col = stat
        if actual_col not in train_df.columns:
            actual_col = stat + "s"

        y_train_all = train_df.get(actual_col, train_df.get(stat, None))

        if y_train_all is None:
            logger.warning(f"  No actuals for {stat} — using fallback")
            result[f"{stat}_mean"] = _weighted_avg_fallback(latest, stat)
            continue

        # Train position-specific models
        for pos_group in ["Guard", "Forward", "Center"]:
            cache_key = (stat, pos_group)
            if not force_retrain and cache_key in _MODEL_CACHE:
                continue

            pos_mask = train_df["position_group"] == pos_group
            X_pos = train_df.loc[pos_mask, available].fillna(0.0)
            y_pos = y_train_all.loc[pos_mask]

            if len(X_pos) >= MIN_POSITION_ROWS:
                try:
                    model = _train_lgbm(X_pos, y_pos, f"{stat}/{pos_group}")
                    _MODEL_CACHE[cache_key] = model
                except Exception as e:
                    logger.warning(f"  [{stat}/{pos_group}] LightGBM failed: {e}")
            else:
                logger.info(f"  [{stat}/{pos_group}] only {len(X_pos)} rows — will use all-positions model")

        # Train all-positions fallback model
        all_cache_key = (stat, "all")
        X_train_all = train_df[available].fillna(0.0)
        if len(X_train_all) >= MIN_TRAIN_ROWS and (force_retrain or all_cache_key not in _MODEL_CACHE):
            try:
                model = _train_lgbm(X_train_all, y_train_all, f"{stat}/all")
                _MODEL_CACHE[all_cache_key] = model
            except Exception as e:
                logger.warning(f"  [{stat}/all] LightGBM failed: {e}")

        # Predict per position group
        preds = pd.Series(index=latest.index, dtype=float)
        for pos_group in ["Guard", "Forward", "Center"]:
            pos_mask = latest["position_group"] == pos_group
            if not pos_mask.any():
                continue

            X_pos_latest = latest.loc[pos_mask, available].fillna(0.0)
            cache_key = (stat, pos_group)

            if cache_key in _MODEL_CACHE:
                preds.loc[pos_mask] = np.clip(
                    _MODEL_CACHE[cache_key].predict(X_pos_latest), 0.0, None
                ).round(4)
                logger.info(f"  [{stat}/{pos_group}] projections via position-specific LightGBM.")
            elif (stat, "all") in _MODEL_CACHE:
                preds.loc[pos_mask] = np.clip(
                    _MODEL_CACHE[(stat, "all")].predict(X_pos_latest), 0.0, None
                ).round(4)
                logger.info(f"  [{stat}/{pos_group}] projections via all-positions LightGBM fallback.")
            else:
                preds.loc[pos_mask] = _weighted_avg_fallback(latest.loc[pos_mask], stat)
                logger.info(f"  [{stat}/{pos_group}] projections via weighted-average fallback.")

        result[f"{stat}_mean"] = preds



    # Ensure all output columns exist
    for col in ["points_mean", "rebounds_mean", "assists_mean", "steals_mean", "blocks_mean"]:
        if col not in result.columns:
            result[col] = 0.0

    # ── SHAP explanations for today's players ─────────────────────────────
    _store_shap_explanations(conn, latest, result)

    return result[["game_id", "player_id", "points_mean", "rebounds_mean",
                   "assists_mean", "steals_mean", "blocks_mean", "minutes_projection"]]


def _store_shap_explanations(conn, latest: pd.DataFrame, result: pd.DataFrame):
    """Compute and store SHAP feature contributions for today's projected players."""
    if conn is None or _MODEL_CACHE is None or not _MODEL_CACHE:
        return

    try:
        from backend.database.connection import init_model_schema
        init_model_schema(conn)
    except Exception:
        pass

    # Filter to today's games only
    try:
        today_games = conn.execute(
            "SELECT game_id FROM games WHERE game_date = CURRENT_DATE"
        ).df()
        if today_games.empty:
            # Fall back: use the most recent game_id in result
            today_game_ids = set(result["game_id"].unique()[:50])
        else:
            today_game_ids = set(today_games["game_id"].astype(str))
    except Exception:
        today_game_ids = set(result["game_id"].unique()[:50])

    today_mask = latest["game_id"].isin(today_game_ids)
    today_latest = latest[today_mask]

    if today_latest.empty:
        return

    explanation_rows = []
    for stat in ["points", "rebounds", "assists", "steals", "blocks"]:
        feat_cols = STAT_FEATURES[stat]
        available = [c for c in feat_cols if c in latest.columns]
        if not available:
            continue

        for _, row in today_latest.iterrows():
            pos_group = row.get("position_group", "Forward")
            cache_key = (stat, pos_group)
            if cache_key not in _MODEL_CACHE:
                cache_key = (stat, "all")
            if cache_key not in _MODEL_CACHE:
                continue

            model = _MODEL_CACHE[cache_key]
            X_row = pd.DataFrame([row[available].fillna(0.0).values], columns=available)
            contributions = compute_shap_contributions(model, X_row, available)

            game_id = str(row["game_id"])
            player_id = row["player_id"]
            try:
                player_id = int(player_id)
            except (ValueError, TypeError):
                pass

            for feature, value in contributions.items():
                if abs(value) > 0.01:  # skip negligible contributions
                    explanation_rows.append((game_id, player_id, stat, feature, round(value, 4)))

    if explanation_rows:
        try:
            conn.execute("DELETE FROM projection_explanations")
            for row in explanation_rows:
                conn.execute(
                    "INSERT INTO projection_explanations VALUES (?, ?, ?, ?, ?)",
                    list(row)
                )
            logger.info(f"  → {len(explanation_rows)} SHAP explanations stored.")
        except Exception as e:
            logger.warning(f"  SHAP storage failed: {e}")


def get_feature_importances() -> dict[str, pd.DataFrame]:
    """Return feature importances for each trained stat model."""
    out = {}
    for key, model in _MODEL_CACHE.items():
        if isinstance(key, tuple):
            stat, pos_group = key
        else:
            stat, pos_group = key, "all"
        if stat in ("points", "rebounds", "assists", "steals", "blocks"):
            feats = STAT_FEATURES[stat]
            imps  = model.feature_importance(importance_type="gain")
            label = f"{stat}/{pos_group}"
            out[label] = pd.DataFrame({
                "feature":    feats[:len(imps)],
                "importance": imps,
            }).sort_values("importance", ascending=False)
    return out
