"""
simulation_validation.py
Post-simulation sanity checks to detect distribution inflation or miscalibration.

Checks:
    1. Mean consistency   — simulated mean ≈ projected mean (within 10%)
    2. Std bounds         — 0.15×proj < std < 1.25×proj
    3. Probability sanity — no P < 0.001 or P > 0.999
    4. Tail sanity        — P(stat >= mean + 2σ) between 1% and 10%

Results logged to ingestion_log with source="simulation_validation".
"""

import uuid
import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def validate_simulations(
    conn,
    proj_means: dict[tuple, float],
) -> dict:
    """
    Run sanity checks on player_simulations after a simulation run.

    Args:
        conn: DuckDB connection
        proj_means: dict of {(player_id, stat): projected_mean}

    Returns:
        dict with check results summary
    """
    logger.info("  Running simulation validation checks...")

    sims = conn.execute("""
        SELECT player_id, stat, line, probability
        FROM player_simulations
        WHERE stat IN ('points', 'rebounds', 'assists', 'steals', 'blocks')
    """).df()

    dists = conn.execute("""
        SELECT player_id, stat, mean, std_dev
        FROM player_distributions
    """).df()

    if sims.empty:
        logger.warning("  No simulation data to validate.")
        return {}

    dist_lookup = {}
    for _, row in dists.iterrows():
        dist_lookup[(str(row["player_id"]), row["stat"])] = {
            "mean": float(row["mean"]),
            "std": float(row["std_dev"]),
        }

    warnings_count = 0
    errors_count = 0
    checked = 0

    # Group simulations by player/stat
    for (pid, stat), group in sims.groupby(["player_id", "stat"]):
        pid = str(pid)
        key = (pid, stat)
        proj_mean = proj_means.get(key)
        dist_info = dist_lookup.get(key)

        if proj_mean is None or proj_mean <= 0:
            continue

        checked += 1
        lines = group.sort_values("line")

        # ── Check 1: Mean consistency ──────────────────────────────────
        # Estimate simulated mean from probability curve:
        # P(X >= line) at each line → simulated mean ≈ line where P ≈ 0.5
        p50_rows = lines[lines["probability"].between(0.40, 0.60)]
        if not p50_rows.empty:
            sim_median = float(p50_rows.iloc[len(p50_rows)//2]["line"])
            deviation = abs(sim_median - proj_mean) / proj_mean
            if deviation > 0.10:
                logger.warning(
                    f"  MEAN DRIFT: {stat} player={pid} "
                    f"proj={proj_mean:.1f} sim_median≈{sim_median:.1f} "
                    f"deviation={deviation:.1%}"
                )
                warnings_count += 1

        # ── Check 2: Std bounds ────────────────────────────────────────
        if dist_info:
            std = dist_info["std"]
            lower_bound = 0.15 * proj_mean
            upper_bound = 1.25 * proj_mean
            if std < lower_bound or std > upper_bound:
                logger.warning(
                    f"  STD BOUNDS: {stat} player={pid} "
                    f"std={std:.2f} bounds=[{lower_bound:.2f}, {upper_bound:.2f}]"
                )
                warnings_count += 1

        # ── Check 3: Probability sanity ────────────────────────────────
        extreme_high = lines[lines["probability"] > 0.999]
        extreme_low  = lines[lines["probability"] < 0.001]
        if not extreme_high.empty:
            logger.error(
                f"  PROB >99.9%: {stat} player={pid} "
                f"lines={extreme_high['line'].tolist()}"
            )
            errors_count += 1
        if not extreme_low.empty and float(lines["line"].min()) > 0:
            # Only flag if the lowest line still shows near-zero probability
            min_line_prob = float(lines.iloc[0]["probability"])
            if min_line_prob < 0.001:
                logger.error(
                    f"  PROB <0.1%: {stat} player={pid} "
                    f"line={float(lines.iloc[0]['line'])} prob={min_line_prob}"
                )
                errors_count += 1

        # ── Check 4: Tail sanity ───────────────────────────────────────
        if dist_info:
            tail_line = proj_mean + 2 * dist_info["std"]
            tail_rows = lines[lines["line"] >= tail_line - 0.5]
            if not tail_rows.empty:
                tail_prob = float(tail_rows.iloc[0]["probability"])
                if tail_prob < 0.01 or tail_prob > 0.10:
                    logger.warning(
                        f"  TAIL CHECK: {stat} player={pid} "
                        f"P(>={tail_line:.1f})={tail_prob:.3f} "
                        f"expected [0.01, 0.10]"
                    )
                    warnings_count += 1

    status = "success" if errors_count == 0 else "error"
    message = (
        f"checked={checked} warnings={warnings_count} errors={errors_count}"
    )
    logger.info(f"  Validation: {message}")

    conn.execute(
        "INSERT OR REPLACE INTO ingestion_log VALUES (?,?,?,?,?,?,current_timestamp)",
        [str(uuid.uuid4()), "simulation_validation", "player_simulations",
         checked, status, message]
    )

    return {
        "checked": checked,
        "warnings": warnings_count,
        "errors": errors_count,
    }
