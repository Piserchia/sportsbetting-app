"""
analysis/calibration.py
Probability calibration evaluation using bet_results.

Buckets model predictions by probability (0.05 increments), computes
actual hit rate per bucket, and reports calibration metrics.
"""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

BUCKET_SIZE = 0.05


def evaluate_calibration(conn) -> pd.DataFrame:
    """
    Evaluate model calibration using historical bet_results.

    Buckets predictions into 5-percentage-point bins and compares
    predicted probability to actual hit rate.

    Returns DataFrame with columns:
        bucket_lower, bucket_upper, n_bets, predicted_prob, actual_hit_rate,
        calibration_error
    """
    try:
        results = conn.execute("""
            SELECT model_probability, result
            FROM bet_results
            WHERE model_probability IS NOT NULL
              AND result IS NOT NULL
        """).df()
    except Exception as e:
        logger.warning(f"Could not read bet_results: {e}")
        return pd.DataFrame()

    if results.empty:
        logger.info("No bet_results available for calibration.")
        return pd.DataFrame()

    results["hit"] = (results["result"] == "win").astype(float)

    # Create buckets
    edges = np.arange(0.0, 1.0 + BUCKET_SIZE, BUCKET_SIZE)
    results["bucket"] = pd.cut(
        results["model_probability"],
        bins=edges,
        labels=False,
        include_lowest=True,
    )

    rows = []
    for bucket_idx in range(len(edges) - 1):
        lower = edges[bucket_idx]
        upper = edges[bucket_idx + 1]
        mask = results["bucket"] == bucket_idx
        subset = results[mask]

        if len(subset) == 0:
            continue

        predicted = float(subset["model_probability"].mean())
        actual = float(subset["hit"].mean())
        cal_error = actual - predicted

        rows.append({
            "bucket_lower": round(lower, 2),
            "bucket_upper": round(upper, 2),
            "n_bets": len(subset),
            "predicted_prob": round(predicted, 4),
            "actual_hit_rate": round(actual, 4),
            "calibration_error": round(cal_error, 4),
        })

    cal_df = pd.DataFrame(rows)

    if not cal_df.empty:
        weighted_error = np.average(
            cal_df["calibration_error"].abs(),
            weights=cal_df["n_bets"],
        )
        total = cal_df["n_bets"].sum()
        logger.info(
            f"Calibration: {total} bets across {len(cal_df)} buckets, "
            f"weighted absolute error = {weighted_error:.4f}"
        )

        # Log overconfident and underconfident ranges
        over = cal_df[cal_df["calibration_error"] < -0.05]
        under = cal_df[cal_df["calibration_error"] > 0.05]
        if not over.empty:
            logger.info(
                f"  Overconfident buckets: "
                f"{list(zip(over['bucket_lower'], over['bucket_upper']))}"
            )
        if not under.empty:
            logger.info(
                f"  Underconfident buckets: "
                f"{list(zip(under['bucket_lower'], under['bucket_upper']))}"
            )

    return cal_df
