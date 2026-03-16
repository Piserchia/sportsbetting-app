"""
models/bayesian_shrinkage.py
Hierarchical Bayesian shrinkage for player stat estimates.

Shrinks observed player means toward position-group priors to stabilize
projections for role players, rookies, and volatile stats.

    posterior_mean = (n * player_mean + k * prior_mean) / (n + k)

Where:
    n = games played by this player
    k = shrinkage strength (prior weight, default 20)
    prior_mean = position-group average for that stat

Players with many games (n >> k) keep their own mean.
Players with few games regress heavily toward the position prior.
"""

import logging
import pandas as pd

logger = logging.getLogger(__name__)

# Default shrinkage strength — higher = more regression toward prior
SHRINKAGE_K = 20

# Minimum games before using player data at all
MIN_GAMES_FOR_PLAYER_DATA = 3

STATS = ["points", "rebounds", "assists", "steals", "blocks"]

# Position group mapping (matches stat_models.py)
POSITION_GROUPS = {
    "Guard":   ["PG", "SG", "G", "G-F"],
    "Forward": ["SF", "PF", "F", "F-G", "F-C"],
    "Center":  ["C", "C-F"],
}


def _get_position_group(pos: str) -> str:
    """Map a position string to Guard/Forward/Center."""
    if not pos or str(pos).strip() == "":
        return "Forward"
    pos = str(pos).strip().upper()
    for group, positions in POSITION_GROUPS.items():
        if pos in positions:
            return group
    return "Forward"


def compute_player_posteriors(conn, k: int = SHRINKAGE_K) -> pd.DataFrame:
    """
    Compute Bayesian posterior stat estimates for all players.

    Steps:
        1. Pull game logs + player positions
        2. Compute per-player means and sample sizes
        3. Compute position-group priors (population means)
        4. Shrink player means toward priors

    Returns DataFrame with columns:
        player_id, stat, posterior_mean, player_mean, prior_mean, n_games, position_group

    Also writes results to player_stat_posteriors table.
    """
    logger.info("Computing Bayesian shrinkage posteriors (k=%d)...", k)

    # Load game logs
    logs = conn.execute("""
        SELECT player_id, points, rebounds, assists, steals, blocks
        FROM player_game_logs
        WHERE points IS NOT NULL
    """).df()

    if logs.empty:
        logger.warning("No game logs — skipping Bayesian shrinkage.")
        return pd.DataFrame()

    logs["player_id"] = logs["player_id"].astype(str)

    # Get player positions (from player_features if available, else infer)
    try:
        positions = conn.execute("""
            SELECT DISTINCT player_id, player_position
            FROM player_features
            WHERE player_position IS NOT NULL
        """).df()
        positions["player_id"] = positions["player_id"].astype(str)
        pos_map = dict(zip(positions["player_id"], positions["player_position"]))
    except Exception:
        pos_map = {}

    # Compute per-player stats
    player_stats = logs.groupby("player_id").agg(
        n_games=("points", "count"),
        points_mean=("points", "mean"),
        rebounds_mean=("rebounds", "mean"),
        assists_mean=("assists", "mean"),
        steals_mean=("steals", "mean"),
        blocks_mean=("blocks", "mean"),
    ).reset_index()

    # Assign position groups
    player_stats["position"] = player_stats["player_id"].map(pos_map).fillna("SF")
    player_stats["position_group"] = player_stats["position"].apply(_get_position_group)

    # Compute position-group priors (population means)
    # Weight each player equally (not each game) to avoid star-player bias
    prior_records = []
    for pg in ["Guard", "Forward", "Center"]:
        pg_mask = player_stats["position_group"] == pg
        pg_players = player_stats[pg_mask]
        if pg_players.empty:
            continue
        for stat in STATS:
            prior_records.append({
                "position_group": pg,
                "stat": stat,
                "prior_mean": float(pg_players[f"{stat}_mean"].mean()),
            })

    if not prior_records:
        # Global fallback if no position data
        for stat in STATS:
            global_mean = float(player_stats[f"{stat}_mean"].mean())
            for pg in ["Guard", "Forward", "Center"]:
                prior_records.append({
                    "position_group": pg,
                    "stat": stat,
                    "prior_mean": global_mean,
                })

    priors_df = pd.DataFrame(prior_records)
    prior_lookup = {
        (r["position_group"], r["stat"]): r["prior_mean"]
        for _, r in priors_df.iterrows()
    }

    logger.info("  Position priors computed:")
    for (pg, stat), pm in sorted(prior_lookup.items()):
        logger.info("    %s/%s: %.2f", pg, stat, pm)

    # Compute posteriors
    posterior_rows = []
    for _, player in player_stats.iterrows():
        pid = player["player_id"]
        n = int(player["n_games"])
        pg = player["position_group"]

        for stat in STATS:
            player_mean = float(player[f"{stat}_mean"])
            prior_mean = prior_lookup.get((pg, stat), player_mean)

            if n < MIN_GAMES_FOR_PLAYER_DATA:
                # Not enough data — use prior entirely
                posterior = prior_mean
            else:
                posterior = (n * player_mean + k * prior_mean) / (n + k)

            posterior_rows.append({
                "player_id": pid,
                "stat": stat,
                "posterior_mean": round(posterior, 4),
                "player_mean": round(player_mean, 4),
                "prior_mean": round(prior_mean, 4),
                "n_games": n,
                "position_group": pg,
            })

    result = pd.DataFrame(posterior_rows)

    # Log shrinkage summary
    n_players = result["player_id"].nunique()
    heavy_shrink = result[
        (result["n_games"] < 20) &
        ((result["posterior_mean"] - result["player_mean"]).abs() > 1.0)
    ]
    logger.info(
        "  → %d posterior estimates for %d players (%d with heavy shrinkage)",
        len(result), n_players, len(heavy_shrink),
    )

    # Write to DB
    try:
        conn.execute("DELETE FROM player_stat_posteriors")
        conn.execute("""
            INSERT INTO player_stat_posteriors
                (player_id, stat, posterior_mean, player_mean, prior_mean, n_games, position_group)
            SELECT player_id, stat, posterior_mean, player_mean, prior_mean, n_games, position_group
            FROM result
        """)
        logger.info("  → Written to player_stat_posteriors.")
    except Exception as e:
        logger.warning("  Failed to write posteriors to DB: %s", e)

    return result
