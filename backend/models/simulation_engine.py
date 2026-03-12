"""
models/simulation_engine.py
Monte Carlo simulation engine — v2 with improved statistical distributions.

Distribution choices:
    Points    → Log-normal  (right-skewed, never negative, realistic NBA scoring)
    Rebounds  → Negative Binomial (count data, overdispersed)
    Assists   → Negative Binomial (count data, overdispersed)

For combo props (PRA, PR, PA) we use a Gaussian copula to preserve
the correlation structure between stats while using marginal distributions
that are statistically appropriate for each stat.

Falls back to normal distribution if parameter fitting fails.
"""

from __future__ import annotations

import logging
import time
from typing import NamedTuple

import numpy as np
import pandas as pd
from scipy import stats

from backend.db.connection import get_connection, init_model_schema

logger = logging.getLogger(__name__)

SIMULATION_COUNT = 10_000

PROP_LINES = {
    "points":   [10, 15, 20, 25, 30, 35, 40, 45, 50],
    "rebounds": [2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 15],
    "assists":  [2, 3, 4, 5, 6, 7, 8, 9, 10, 12],
    "steals":   [0.5, 1.5, 2.5, 3.5],
    "blocks":   [0.5, 1.5, 2.5, 3.5],
}

COMBO_LINES = {
    "PRA": [10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60],
    "PR":  [10, 15, 20, 25, 30, 35, 40, 45],
    "PA":  [10, 15, 20, 25, 30, 35, 40, 45],
    "SB":  [0.5, 1.5, 2.5, 3.5, 4.5, 5.5],
}

MIN_STD = 1.5


# ── Distribution parameter fitting ────────────────────────────────────────────

class LogNormalParams(NamedTuple):
    mu: float
    sigma: float

class NegBinParams(NamedTuple):
    n: float      # number of successes (dispersion)
    p: float      # probability of success


def _fit_lognormal(mean: float, std: float) -> LogNormalParams:
    """
    Fit log-normal parameters from a target mean and std dev.

    For X ~ LogNormal(mu, sigma):
        E[X] = exp(mu + sigma^2/2)
        Var[X] = (exp(sigma^2) - 1) * exp(2*mu + sigma^2)
    """
    mean = max(mean, 0.5)
    std  = max(std,  MIN_STD)
    var  = std ** 2
    # sigma^2 = log(1 + var/mean^2)
    sigma2 = np.log(1 + var / (mean ** 2))
    sigma  = np.sqrt(sigma2)
    mu     = np.log(mean) - sigma2 / 2
    return LogNormalParams(mu=mu, sigma=sigma)


def _fit_negbin(mean: float, std: float) -> NegBinParams:
    """
    Fit Negative Binomial from mean and std dev.

    NB parameterisation: mean = n*(1-p)/p, var = n*(1-p)/p^2
    => var = mean + mean^2/n
    => n   = mean^2 / (var - mean)   [requires var > mean]
    """
    mean = max(mean, 0.5)
    std  = max(std,  MIN_STD)
    var  = std ** 2

    if var <= mean:
        # Variance <= mean → Poisson-like; use n=1000 to approximate Poisson
        n = 1000.0
    else:
        n = (mean ** 2) / (var - mean)
        n = max(n, 0.1)

    p = n / (n + mean)
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return NegBinParams(n=n, p=p)


def _sim_lognormal(
    rng: np.random.Generator,
    mean: float,
    std: float,
    size: int,
) -> np.ndarray:
    """Draw `size` log-normal samples targeting given mean/std. Clipped to [0, inf)."""
    try:
        p = _fit_lognormal(mean, std)
        samples = rng.lognormal(p.mu, p.sigma, size)
        return np.clip(samples, 0.0, None)
    except Exception:
        # Fallback: normal
        return np.clip(rng.normal(mean, std, size), 0.0, None)


def _sim_negbin(
    rng: np.random.Generator,
    mean: float,
    std: float,
    size: int,
) -> np.ndarray:
    """
    Draw `size` negative binomial samples targeting given mean/std.
    NB is discrete, which is appropriate for count stats.
    """
    try:
        p = _fit_negbin(mean, std)
        # scipy's nbinom.rvs uses (n, p) parameterisation
        # numpy doesn't have negbin, so use scipy
        samples = stats.nbinom.rvs(p.n, p.p, size=size,
                                   random_state=int(rng.integers(0, 2**31)))
        return samples.astype(float)
    except Exception:
        return np.clip(rng.normal(mean, std, size), 0.0, None)


# ── Gaussian copula for correlated combo props ─────────────────────────────────

def _build_correlation_matrix(player_logs: pd.DataFrame) -> np.ndarray:
    """
    Compute the 3×3 Spearman rank correlation matrix for
    [points, rebounds, assists] from a player's game logs.

    Spearman is more robust than Pearson for non-normal marginals.
    Returns identity matrix as fallback when insufficient data.
    """
    data = player_logs[["points", "rebounds", "assists"]].dropna()
    if len(data) < 10:
        return np.eye(3)

    try:
        corr, _ = stats.spearmanr(data.values)
        if corr.ndim == 0:
            return np.eye(3)
        corr_mat = np.array(corr)

        # Enforce positive semi-definite
        eigvals, eigvecs = np.linalg.eigh(corr_mat)
        eigvals = np.clip(eigvals, 1e-6, None)
        corr_mat = (eigvecs @ np.diag(eigvals) @ eigvecs.T).copy()

        # Re-normalise diagonal to 1
        d = np.sqrt(np.diag(corr_mat))
        corr_mat = corr_mat / np.outer(d, d)
        np.fill_diagonal(corr_mat, 1.0)

        return corr_mat
    except Exception:
        return np.eye(3)


def _gaussian_copula_sample(
    rng: np.random.Generator,
    corr_matrix: np.ndarray,
    size: int,
) -> np.ndarray:
    """
    Draw `size` samples from a 3-dim Gaussian copula.
    Returns array of shape (size, 3) with uniform marginals in (0, 1).
    """
    # Draw correlated normals
    L       = np.linalg.cholesky(corr_matrix + 1e-8 * np.eye(3))
    z       = rng.standard_normal((size, 3))
    corr_z  = z @ L.T
    # Transform to uniform via standard normal CDF
    uniform = stats.norm.cdf(corr_z)
    return uniform


def _correlated_combo_sims(
    rng: np.random.Generator,
    mean_pts: float, std_pts: float,
    mean_reb: float, std_reb: float,
    mean_ast: float, std_ast: float,
    corr_matrix: np.ndarray,
    size: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Generate correlated samples for (points, rebounds, assists) using a
    Gaussian copula with the appropriate marginal distributions.

    Returns three arrays of shape (size,).
    """
    try:
        # Get correlated uniforms from copula
        u = _gaussian_copula_sample(rng, corr_matrix, size)

        # Invert through each marginal's CDF to get correlated stat samples
        # Points → log-normal PPF
        pts_p = _fit_lognormal(mean_pts, std_pts)
        sim_pts = stats.lognorm.ppf(
            np.clip(u[:, 0], 1e-6, 1 - 1e-6),
            s=pts_p.sigma, scale=np.exp(pts_p.mu)
        )

        # Rebounds → negative binomial PPF
        reb_p = _fit_negbin(mean_reb, std_reb)
        sim_reb = stats.nbinom.ppf(
            np.clip(u[:, 1], 1e-6, 1 - 1e-6),
            reb_p.n, reb_p.p
        ).astype(float)

        # Assists → negative binomial PPF
        ast_p = _fit_negbin(mean_ast, std_ast)
        sim_ast = stats.nbinom.ppf(
            np.clip(u[:, 2], 1e-6, 1 - 1e-6),
            ast_p.n, ast_p.p
        ).astype(float)

        return (
            np.clip(sim_pts, 0.0, None),
            np.clip(sim_reb, 0.0, None),
            np.clip(sim_ast, 0.0, None),
        )

    except Exception as e:
        logger.debug(f"Copula simulation failed: {e} — using independent normals")
        return (
            np.clip(rng.normal(mean_pts, std_pts, size), 0.0, None),
            np.clip(rng.normal(mean_reb, std_reb, size), 0.0, None),
            np.clip(rng.normal(mean_ast, std_ast, size), 0.0, None),
        )


def _build_covariance_matrix(player_logs: pd.DataFrame) -> np.ndarray:
    """Legacy helper kept for compatibility."""
    stats_df = player_logs[["points", "rebounds", "assists"]].dropna()
    if len(stats_df) < 10:
        std_pts = max(float(stats_df["points"].std())   if len(stats_df) > 1 else 5.0, MIN_STD)
        std_reb = max(float(stats_df["rebounds"].std()) if len(stats_df) > 1 else 3.0, MIN_STD)
        std_ast = max(float(stats_df["assists"].std())  if len(stats_df) > 1 else 2.0, MIN_STD)
        return np.diag([std_pts**2, std_reb**2, std_ast**2])
    cov = stats_df.cov().values.copy()
    for i in range(3):
        cov[i, i] = max(cov[i, i], MIN_STD**2)
    eigvals, eigvecs = np.linalg.eigh(cov)
    eigvals = np.clip(eigvals, 1e-6, None)
    return (eigvecs @ np.diag(eigvals) @ eigvecs.T).copy()


# ── Main simulation entry point ────────────────────────────────────────────────

def simulate_player_props(conn=None) -> int:
    """
    Run Monte Carlo simulations for all players:

      Individual props:
        - Points   via log-normal distribution
        - Rebounds via negative binomial
        - Assists  via negative binomial

      Combo props (PRA, PR, PA):
        - Gaussian copula preserving Spearman rank correlations
        - Each marginal uses its appropriate distribution

    Returns total simulation rows written.
    """
    close = conn is None
    conn  = conn or get_connection()
    init_model_schema(conn)

    logger.info("Loading projections, distributions, and game logs...")

    projections = conn.execute("""
        SELECT player_id, game_id, points_mean, rebounds_mean, assists_mean,
               COALESCE(steals_mean, 0.0) AS steals_mean,
               COALESCE(blocks_mean, 0.0) AS blocks_mean
        FROM player_projections
    """).df()

    distributions = conn.execute("""
        SELECT player_id, game_id, stat, mean, std_dev
        FROM player_distributions
    """).df()

    game_logs = conn.execute("""
        SELECT player_id, game_id, points, rebounds, assists, steals, blocks
        FROM player_game_logs
    """).df()

    if distributions.empty:
        logger.warning("No player_distributions found. Run run_projections first.")
        if close:
            conn.close()
        return 0

    # Build lookup dicts
    proj_means: dict[tuple, float] = {}
    for _, row in projections.iterrows():
        pid = str(row["player_id"])
        proj_means[(pid, "points")]   = float(row["points_mean"])
        proj_means[(pid, "rebounds")] = float(row["rebounds_mean"])
        proj_means[(pid, "assists")]  = float(row["assists_mean"])
        proj_means[(pid, "steals")]   = float(row["steals_mean"])
        proj_means[(pid, "blocks")]   = float(row["blocks_mean"])

    dist_lookup: dict[tuple, dict] = {}
    for _, row in distributions.iterrows():
        key = (str(row["player_id"]), row["stat"])
        dist_lookup[key] = {
            "mean":    float(row["mean"]),
            "std_dev": float(row["std_dev"]),
            "game_id": str(row["game_id"]),
        }

    logs_by_player = {
        str(pid): grp.copy()
        for pid, grp in game_logs.groupby("player_id")
    }

    players = distributions["player_id"].astype(str).unique()
    logger.info(
        f"Simulating {SIMULATION_COUNT:,} games for {len(players)} players "
        f"(lognormal pts | negbin reb/ast | copula combos)..."
    )

    t0      = time.time()
    records = []
    rng     = np.random.default_rng(seed=42)

    for player_id in players:
        pts_key = (player_id, "points")
        reb_key = (player_id, "rebounds")
        ast_key = (player_id, "assists")

        if pts_key not in dist_lookup:
            continue

        game_id = dist_lookup[pts_key]["game_id"]

        stl_key = (player_id, "steals")
        blk_key = (player_id, "blocks")

        mean_pts = proj_means.get(pts_key, dist_lookup[pts_key]["mean"])
        mean_reb = proj_means.get(reb_key, dist_lookup.get(reb_key, {}).get("mean", 0.0))
        mean_ast = proj_means.get(ast_key, dist_lookup.get(ast_key, {}).get("mean", 0.0))
        mean_stl = proj_means.get(stl_key, dist_lookup.get(stl_key, {}).get("mean", 0.8))
        mean_blk = proj_means.get(blk_key, dist_lookup.get(blk_key, {}).get("mean", 0.5))

        std_pts = max(dist_lookup[pts_key]["std_dev"], MIN_STD)
        std_reb = max(dist_lookup.get(reb_key, {}).get("std_dev", MIN_STD), MIN_STD)
        std_ast = max(dist_lookup.get(ast_key, {}).get("std_dev", MIN_STD), MIN_STD)
        std_stl = max(dist_lookup.get(stl_key, {}).get("std_dev", 0.8), 0.5)
        std_blk = max(dist_lookup.get(blk_key, {}).get("std_dev", 0.7), 0.5)

        # ── Individual prop simulations with better distributions ─────────
        sim_pts = _sim_lognormal(rng, mean_pts, std_pts, SIMULATION_COUNT)
        sim_reb = _sim_negbin(rng, mean_reb, std_reb, SIMULATION_COUNT)
        sim_ast = _sim_negbin(rng, mean_ast, std_ast, SIMULATION_COUNT)
        sim_stl = _sim_negbin(rng, mean_stl, std_stl, SIMULATION_COUNT)
        sim_blk = _sim_negbin(rng, mean_blk, std_blk, SIMULATION_COUNT)

        for stat, simulated in [
            ("points",   sim_pts),
            ("rebounds", sim_reb),
            ("assists",  sim_ast),
            ("steals",   sim_stl),
            ("blocks",   sim_blk),
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

        # ── Correlated combo props via Gaussian copula ────────────────────
        player_log_df = logs_by_player.get(player_id, pd.DataFrame())
        corr_matrix   = _build_correlation_matrix(player_log_df)

        sim_pts_c, sim_reb_c, sim_ast_c = _correlated_combo_sims(
            rng,
            mean_pts, std_pts,
            mean_reb, std_reb,
            mean_ast, std_ast,
            corr_matrix,
            SIMULATION_COUNT,
        )

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

        # ── SB (Steals + Blocks) correlated combo ─────────────────────────
        # Use 2D copula with Spearman correlation from game logs
        try:
            sb_data = player_log_df[["steals", "blocks"]].dropna()
            if len(sb_data) >= 10:
                sb_corr, _ = stats.spearmanr(sb_data.values)
                sb_corr_val = float(sb_corr) if np.ndim(sb_corr) == 0 else 0.3
            else:
                sb_corr_val = 0.3
            sb_corr_val = float(np.clip(sb_corr_val, -0.99, 0.99))
            sb_corr_matrix = np.array([[1.0, sb_corr_val], [sb_corr_val, 1.0]])
            # Ensure PSD
            eigvals, eigvecs = np.linalg.eigh(sb_corr_matrix)
            eigvals = np.clip(eigvals, 1e-6, None)
            sb_corr_matrix = (eigvecs @ np.diag(eigvals) @ eigvecs.T).copy()
            np.fill_diagonal(sb_corr_matrix, 1.0)

            L_sb = np.linalg.cholesky(sb_corr_matrix + 1e-8 * np.eye(2))
            z_sb = rng.standard_normal((SIMULATION_COUNT, 2))
            u_sb = stats.norm.cdf(z_sb @ L_sb.T)

            stl_p = _fit_negbin(mean_stl, std_stl)
            blk_p = _fit_negbin(mean_blk, std_blk)
            sim_stl_c = stats.nbinom.ppf(np.clip(u_sb[:, 0], 1e-6, 1 - 1e-6), stl_p.n, stl_p.p).astype(float)
            sim_blk_c = stats.nbinom.ppf(np.clip(u_sb[:, 1], 1e-6, 1 - 1e-6), blk_p.n, blk_p.p).astype(float)
        except Exception:
            sim_stl_c = sim_stl
            sim_blk_c = sim_blk

        sim_sb = sim_stl_c + sim_blk_c
        for line in COMBO_LINES["SB"]:
            prob = float(np.mean(sim_sb >= line))
            records.append({
                "game_id":     game_id,
                "player_id":   player_id,
                "stat":        "SB",
                "line":        float(line),
                "probability": round(prob, 6),
            })

    elapsed = time.time() - t0
    logger.info(f"  Simulations complete in {elapsed:.2f}s — {len(records):,} rows")

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
