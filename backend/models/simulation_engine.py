"""
models/simulation_engine.py
Monte Carlo simulation engine for NBA player prop probability estimation.

Two simulation modes:
  1. Independent — normal draw per stat (points, rebounds, assists)
  2. Correlated — multivariate_normal draw using per-player covariance matrix
     Enables combo prop evaluation: PRA, PR, PA

Performance target: 500 players × 10,000 sims < 10 seconds (vectorized NumPy).

Populates: player_simulations
"""

import logging
import time
import numpy as np
import pandas as pd

from backend.db.connection import get_connection, init_model_schema

logger = logging.getLogger(__name__)

SIMULATION_COUNT = 10_000

# Individual stat prop ladders
PROP_LINES = {
    "points":   [10, 15, 20, 25, 30, 35, 40, 45, 50],
    "rebounds": [2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 15],
    "assists":  [2, 3, 4, 5, 6, 7, 8, 9, 10, 12],
}

# Combo prop ladders
COMBO_LINES = {
    "PRA": [10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60],
    "PR":  [10, 15, 20, 25, 30, 35, 40, 45],
    "PA":  [10, 15, 20, 25, 30, 35, 40, 45],
}

MIN_STD = 1.5  # floor on std dev to prevent distribution collapse


def _build_covariance_matrix(player_logs: pd.DataFrame) -> np.ndarray:
    """
    Compute 3×3 covariance matrix for [points, rebounds, assists]
    from a player's historical game log.

    Falls back to diagonal (independent) if insufficient data.
    """
    stats = player_logs[["points", "rebounds", "assists"]].dropna()
    if len(stats) < 10:
        # Not enough data — use diagonal (independent) covariance
        std_pts = max(float(stats["points"].std())   if len(stats) > 1 else 5.0, MIN_STD)
        std_reb = max(float(stats["rebounds"].std()) if len(stats) > 1 else 3.0, MIN_STD)
        std_ast = max(float(stats["assists"].std())  if len(stats) > 1 else 2.0, MIN_STD)
        return np.diag([std_pts**2, std_reb**2, std_ast**2])

    cov = stats.cov().values
    # Enforce minimum variances on the diagonal
    for i, min_var in enumerate([MIN_STD**2, MIN_STD**2, MIN_STD**2]):
        cov[i, i] = max(cov[i, i], min_var)

    # Ensure positive semi-definite via eigenvalue clipping
    eigvals, eigvecs = np.linalg.eigh(cov)
    eigvals = np.clip(eigvals, 1e-6, None)
    cov = eigvecs @ np.diag(eigvals) @ eigvecs.T

    return cov


def simulate_player_props(conn=None) -> int:
    """
    Run Monte Carlo simulations for all players:
      - Independent draws per stat for individual prop ladders
      - Multivariate draws for correlated combo props (PRA, PR, PA)

    Returns total number of simulation rows written.
    """
    close = conn is None
    conn = conn or get_connection()
    init_model_schema(conn)

    logger.info("Loading projections, distributions, and game logs...")

    projections = conn.execute("""
        SELECT player_id, game_id, points_mean, rebounds_mean, assists_mean
        FROM player_projections
    """).df()

    distributions = conn.execute("""
        SELECT player_id, game_id, stat, mean, std_dev
        FROM player_distributions
    """).df()

    game_logs = conn.execute("""
        SELECT player_id, game_id, points, rebounds, assists
        FROM player_game_logs
    """).df()

    if distributions.empty:
        logger.warning("No player_distributions found. Run run_projections first.")
        if close:
            conn.close()
        return 0

    # Build lookup dicts
    proj_means = {}
    for _, row in projections.iterrows():
        pid = str(row["player_id"])
        proj_means[(pid, "points")]   = float(row["points_mean"])
        proj_means[(pid, "rebounds")] = float(row["rebounds_mean"])
        proj_means[(pid, "assists")]  = float(row["assists_mean"])

    dist_lookup = {}
    for _, row in distributions.iterrows():
        key = (str(row["player_id"]), row["stat"])
        dist_lookup[key] = {
            "mean":    float(row["mean"]),
            "std_dev": float(row["std_dev"]),
            "game_id": str(row["game_id"]),
        }

    # Group game logs by player for covariance computation
    logs_by_player = {
        str(pid): grp
        for pid, grp in game_logs.groupby("player_id")
    }

    players    = distributions["player_id"].astype(str).unique()
    stats      = list(PROP_LINES.keys())
    combo_stats = list(COMBO_LINES.keys())

    logger.info(
        f"Simulating {SIMULATION_COUNT:,} games for {len(players)} players "
        f"across {len(stats)} stats + {len(combo_stats)} combo props..."
    )

    t0 = time.time()
    records = []
    rng = np.random.default_rng(seed=42)

    for player_id in players:
        # ── Resolve mean / std per stat ───────────────────────────────────
        pts_key = (player_id, "points")
        reb_key = (player_id, "rebounds")
        ast_key = (player_id, "assists")

        if pts_key not in dist_lookup:
            continue

        game_id = dist_lookup[pts_key]["game_id"]

        mean_pts = proj_means.get(pts_key, dist_lookup[pts_key]["mean"])
        mean_reb = proj_means.get(reb_key, dist_lookup.get(reb_key, {}).get("mean", 0.0))
        mean_ast = proj_means.get(ast_key, dist_lookup.get(ast_key, {}).get("mean", 0.0))

        std_pts  = max(dist_lookup[pts_key]["std_dev"], MIN_STD)
        std_reb  = max(dist_lookup.get(reb_key, {}).get("std_dev", MIN_STD), MIN_STD)
        std_ast  = max(dist_lookup.get(ast_key, {}).get("std_dev", MIN_STD), MIN_STD)

        mean_vec = np.array([
            max(mean_pts, 0.0),
            max(mean_reb, 0.0),
            max(mean_ast, 0.0),
        ])

        # ── Independent simulations for individual prop ladders ───────────
        sim_pts = np.clip(rng.normal(mean_pts, std_pts, SIMULATION_COUNT), 0, None)
        sim_reb = np.clip(rng.normal(mean_reb, std_reb, SIMULATION_COUNT), 0, None)
        sim_ast = np.clip(rng.normal(mean_ast, std_ast, SIMULATION_COUNT), 0, None)

        for stat, simulated in [
            ("points",   sim_pts),
            ("rebounds", sim_reb),
            ("assists",  sim_ast),
        ]:
            for line in PROP_LINES[stat]:
                prob = float(np.mean(simulated >= line))
                records.append({
                    "game_id":     game_id,
                    "player_id":   player_id,
                    "stat":        stat,
                    "line":        float(line),
                    "probability": round(prob, 6),
                })

        # ── Correlated multivariate simulation for combo props ────────────
        player_log_df = logs_by_player.get(player_id, pd.DataFrame())
        cov_matrix    = _build_covariance_matrix(player_log_df)

        # Override diagonal with projection-based std devs
        cov_matrix[0, 0] = max(cov_matrix[0, 0], std_pts**2)
        cov_matrix[1, 1] = max(cov_matrix[1, 1], std_reb**2)
        cov_matrix[2, 2] = max(cov_matrix[2, 2], std_ast**2)

        try:
            corr_sims = rng.multivariate_normal(mean_vec, cov_matrix, size=SIMULATION_COUNT)
            corr_sims = np.clip(corr_sims, 0, None)

            sim_pts_c, sim_reb_c, sim_ast_c = corr_sims[:, 0], corr_sims[:, 1], corr_sims[:, 2]
            sim_pra = sim_pts_c + sim_reb_c + sim_ast_c
            sim_pr  = sim_pts_c + sim_reb_c
            sim_pa  = sim_pts_c + sim_ast_c

            for stat, simulated in [
                ("PRA", sim_pra),
                ("PR",  sim_pr),
                ("PA",  sim_pa),
            ]:
                for line in COMBO_LINES[stat]:
                    prob = float(np.mean(simulated >= line))
                    records.append({
                        "game_id":     game_id,
                        "player_id":   player_id,
                        "stat":        stat,
                        "line":        float(line),
                        "probability": round(prob, 6),
                    })

        except np.linalg.LinAlgError as e:
            logger.warning(f"  Covariance matrix invalid for player {player_id}: {e} — skipping combo props")

    elapsed = time.time() - t0
    logger.info(f"  Simulations complete in {elapsed:.2f}s — {len(records):,} probability rows")

    sim_df = pd.DataFrame(records)
    conn.execute("DELETE FROM player_simulations")
    conn.execute("INSERT INTO player_simulations SELECT * FROM sim_df")
    logger.info(f"  → {len(sim_df):,} rows written to player_simulations.")

    if close:
        conn.close()
    return len(sim_df)


def probability_to_american_odds(probability: float) -> int:
    if probability <= 0 or probability >= 1:
        return 0
    if probability >= 0.5:
        return int(-(probability / (1 - probability)) * 100)
    return int(((1 - probability) / probability) * 100)


def american_odds_to_probability(american_odds: float) -> float:
    if american_odds > 0:
        return 100 / (american_odds + 100)
    return abs(american_odds) / (abs(american_odds) + 100)
