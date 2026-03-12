#!/usr/bin/env python3
"""
scripts/backtest_model.py
Backtesting framework for PropModel v2.

Evaluates historical prediction accuracy by comparing model probabilities
against actual outcomes. Metrics:
  - Brier Score, Log Loss, Hit Rate, ROI, Calibration Error

Usage:
    python scripts/backtest_model.py
    python scripts/backtest_model.py --stat points --season 2025-26
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import sys
import os
from datetime import date

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.logging_config import setup_logging
from backend.database.connection import get_connection, init_model_schema

setup_logging()
logger = logging.getLogger(__name__)

MODEL_VERSION  = "v2"
DEFAULT_SEASON = "2025-26"
STATS          = ["points", "rebounds", "assists", "PRA", "PR", "PA"]
STAKE          = 100.0
VIG_PAYOUT     = 100.0 * 100.0 / 110.0   # net profit per $100 at -110


def _brier_score(y_true: np.ndarray, y_prob: np.ndarray) -> float:
    return float(np.mean((y_prob - y_true) ** 2))


def _log_loss(y_true: np.ndarray, y_prob: np.ndarray, eps: float = 1e-7) -> float:
    p = np.clip(y_prob, eps, 1 - eps)
    return float(-np.mean(y_true * np.log(p) + (1 - y_true) * np.log(1 - p)))


def _roi(y_true: np.ndarray, y_prob: np.ndarray, threshold: float = 0.55) -> float:
    mask  = y_prob >= threshold
    bets  = mask.sum()
    if bets == 0:
        return 0.0
    wins  = y_true[mask].sum()
    total = bets * STAKE
    returned = wins * (STAKE + VIG_PAYOUT)
    return float((returned - total) / total * 100)


def _ece(y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 10) -> float:
    edges = np.linspace(0, 1, n_bins + 1)
    n     = len(y_true)
    ece   = 0.0
    for i in range(n_bins):
        m = (y_prob >= edges[i]) & (y_prob < edges[i + 1])
        if m.sum() == 0:
            continue
        ece += m.sum() / n * abs(y_prob[m].mean() - y_true[m].mean())
    return float(ece)


def run_backtest(conn=None, season: str = DEFAULT_SEASON,
                 stats_to_eval=None, threshold: float = 0.55) -> pd.DataFrame:
    close = conn is None
    conn  = conn or get_connection()
    init_model_schema(conn)

    if stats_to_eval is None:
        stats_to_eval = STATS

    actuals = conn.execute(f"""
        SELECT pgl.game_id, pgl.player_id,
               pgl.points, pgl.rebounds, pgl.assists,
               (pgl.points + pgl.rebounds + pgl.assists) AS PRA,
               (pgl.points + pgl.rebounds)               AS PR,
               (pgl.points + pgl.assists)                AS PA
        FROM player_game_logs pgl
        JOIN games g ON pgl.game_id = g.game_id
        WHERE g.season = '{season}' AND pgl.points IS NOT NULL
    """).df()

    sims = conn.execute("""
        SELECT game_id, player_id, stat, line, probability
        FROM player_simulations
    """).df()

    if actuals.empty or sims.empty:
        logger.warning("Need both actuals and simulations to backtest.")
        if close: conn.close()
        return pd.DataFrame()

    actuals["player_id"] = actuals["player_id"].astype(str)
    sims["player_id"]    = sims["player_id"].astype(str)

    stat_cols = [s for s in stats_to_eval if s in actuals.columns]
    long = actuals[["game_id", "player_id"] + stat_cols].melt(
        id_vars=["game_id", "player_id"],
        value_vars=stat_cols,
        var_name="stat", value_name="actual"
    )

    merged = sims.merge(long, on=["game_id", "player_id", "stat"], how="inner")
    merged["hit"] = (merged["actual"] >= merged["line"]).astype(float)

    run_date = date.today().isoformat()
    records  = []

    for stat in stats_to_eval:
        s_df = merged[merged["stat"] == stat]
        if s_df.empty:
            continue
        for line in sorted(s_df["line"].unique()):
            l_df = s_df[s_df["line"] == line].dropna(subset=["probability", "hit"])
            if len(l_df) < 20:
                continue
            yt = l_df["hit"].values
            yp = l_df["probability"].values
            bid = hashlib.md5(f"{run_date}_{stat}_{line}_{MODEL_VERSION}".encode()).hexdigest()[:16]
            records.append({
                "backtest_id":   bid,
                "run_date":      run_date,
                "model_version": MODEL_VERSION,
                "stat":          stat,
                "line":          float(line),
                "n_predictions": int(len(l_df)),
                "hit_rate":      round(float(yt.mean()), 4),
                "brier_score":   round(_brier_score(yt, yp), 4),
                "log_loss":      round(_log_loss(yt, yp), 4),
                "roi":           round(_roi(yt, yp, threshold), 4),
                "avg_edge":      round(float((yp - yt).mean()), 4),
                "created_at":    run_date,
            })

    if not records:
        if close: conn.close()
        return pd.DataFrame()

    df = pd.DataFrame(records)
    conn.execute("INSERT OR REPLACE INTO model_backtests SELECT * FROM df")

    summary = df.groupby("stat").agg(
        n=("n_predictions","sum"), hit_rate=("hit_rate","mean"),
        brier=("brier_score","mean"), roi=("roi","mean"),
        avg_edge=("avg_edge","mean")
    ).round(4)

    logger.info("\n── Backtest Summary ──")
    for stat, row in summary.iterrows():
        logger.info(
            f"  {stat:10s}  n={int(row['n']):6,}  hit={row['hit_rate']:.3f}  "
            f"brier={row['brier']:.4f}  ROI={row['roi']:+.1f}%  "
            f"edge={row['avg_edge']:+.4f}"
        )

    if close: conn.close()
    return df


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--season",    default=DEFAULT_SEASON)
    parser.add_argument("--stat",      default=None)
    parser.add_argument("--threshold", type=float, default=0.55)
    args = parser.parse_args()

    conn    = get_connection()
    results = run_backtest(conn, season=args.season,
                           stats_to_eval=[args.stat] if args.stat else None,
                           threshold=args.threshold)
    conn.close()
    if not results.empty:
        print(f"✅ Backtest complete — {len(results):,} rows written to model_backtests.")
    else:
        print("⚠️  No backtest results generated.")
