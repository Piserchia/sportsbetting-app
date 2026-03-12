"""
models/game_simulator.py
Game-level correlated simulation engine.

Instead of simulating each player independently, this module:
1. Simulates total game possessions from pace data
2. Allocates team possessions
3. Simulates team scoring from offensive/defensive ratings
4. Allocates individual stats using usage_proxy * minutes_projection shares
5. Adds per-player noise from their individual distributions

This preserves realistic correlations:
    minutes ↔ usage, points ↔ assists, rebounds ↔ missed shots
"""

from __future__ import annotations

import logging
import time

import numpy as np
import pandas as pd
from scipy import stats

from backend.database.connection import get_connection, init_model_schema

logger = logging.getLogger(__name__)

SIMULATION_COUNT = 10_000
MIN_STD = 1.5


def simulate_game_level(conn=None) -> dict:
    """
    Run game-level correlated simulations for all today's games.

    Returns dict of {(player_id, stat): np.ndarray of simulated values}
    for use by the main simulation engine.
    """
    close = conn is None
    conn = conn or get_connection()
    init_model_schema(conn)

    try:
        # Load team advanced stats (pace/ratings)
        try:
            adv_stats = conn.execute("""
                SELECT game_id, team_id, off_rating, def_rating, pace, possessions
                FROM team_advanced_stats
            """).df()
        except Exception:
            adv_stats = pd.DataFrame()

        if adv_stats.empty:
            logger.info("  No team_advanced_stats — game-level sim unavailable")
            return {}

        # Load projections for player shares
        projections = conn.execute("""
            SELECT
                p.player_id,
                p.game_id,
                p.minutes_projection,
                pf.usage_proxy,
                pf.team_pace,
                pgs.team_id
            FROM player_projections p
            JOIN player_features pf
              ON p.game_id = pf.game_id AND p.player_id = pf.player_id
            JOIN player_game_stats pgs
              ON p.game_id = pgs.game_id
             AND CAST(pgs.player_id AS TEXT) = p.player_id
        """).df()

        if projections.empty:
            return {}

        projections["player_id"] = projections["player_id"].astype(str)
        projections["team_id"] = projections["team_id"].astype(str)

        # Load distributions for per-player noise
        distributions = conn.execute("""
            SELECT player_id, stat, mean, std_dev
            FROM player_distributions
        """).df()
        dist_lookup = {}
        for _, row in distributions.iterrows():
            dist_lookup[(str(row["player_id"]), row["stat"])] = {
                "mean": float(row["mean"]),
                "std": max(float(row["std_dev"]), MIN_STD),
            }

        # Get latest rolling stats per team for pace/ratings
        team_stats = {}
        for _, row in adv_stats.iterrows():
            tid = str(row["team_id"])
            if tid not in team_stats:
                team_stats[tid] = []
            team_stats[tid].append(row)

        # Compute rolling averages per team
        team_pace = {}
        team_off = {}
        team_def = {}
        for tid, rows in team_stats.items():
            df = pd.DataFrame(rows).sort_values("game_id")
            team_pace[tid] = float(df["pace"].tail(10).mean())
            team_off[tid] = float(df["off_rating"].tail(10).mean())
            team_def[tid] = float(df["def_rating"].tail(10).mean())

        rng = np.random.default_rng(seed=42)
        t0 = time.time()

        # Group players by game and team
        game_teams = projections.groupby(["game_id", "team_id"])

        player_sims = {}

        for (game_id, team_id), team_players in game_teams:
            tid = str(team_id)
            pace = team_pace.get(tid, 100.0)
            off_rtg = team_off.get(tid, 110.0)

            # Step 1: Simulate game possessions
            sim_poss = rng.normal(pace, 5.0, SIMULATION_COUNT).clip(70, 130)

            # Step 2: Simulate team total points
            # pts_per_poss = off_rating / 100
            pts_per_poss = off_rtg / 100.0
            sim_team_pts = sim_poss * pts_per_poss

            # Step 3: Compute player shares
            players = team_players.copy()
            players["share_raw"] = (
                players["usage_proxy"].fillna(0.2) *
                players["minutes_projection"].fillna(20.0)
            )
            total_share = players["share_raw"].sum()
            if total_share <= 0:
                total_share = 1.0
            players["share"] = players["share_raw"] / total_share

            # Step 4: Allocate stats per player
            for _, player in players.iterrows():
                pid = str(player["player_id"])
                share = float(player["share"])

                # Points: share of team total + noise
                base_pts = sim_team_pts * share
                dist = dist_lookup.get((pid, "points"), {"mean": 15.0, "std": 5.0})
                noise_scale = dist["std"] * 0.3  # 30% of individual std as noise
                sim_pts = base_pts + rng.normal(0, noise_scale, SIMULATION_COUNT)
                player_sims[(pid, "points")] = sim_pts.clip(0)

                # Rebounds: loosely tied to missed shots (more possessions = more rebounds)
                dist_reb = dist_lookup.get((pid, "rebounds"), {"mean": 5.0, "std": 3.0})
                reb_base = dist_reb["mean"] * (sim_poss / pace)  # scale with possessions
                noise_reb = rng.normal(0, dist_reb["std"] * 0.4, SIMULATION_COUNT)
                player_sims[(pid, "rebounds")] = (reb_base + noise_reb).clip(0)

                # Assists: correlated with team scoring
                dist_ast = dist_lookup.get((pid, "assists"), {"mean": 3.0, "std": 2.0})
                ast_base = dist_ast["mean"] * (sim_team_pts / (pace * pts_per_poss))
                noise_ast = rng.normal(0, dist_ast["std"] * 0.4, SIMULATION_COUNT)
                player_sims[(pid, "assists")] = (ast_base + noise_ast).clip(0)

                # Steals/blocks: less correlated with game flow
                for stat in ["steals", "blocks"]:
                    dist_s = dist_lookup.get((pid, stat), {"mean": 0.8, "std": 0.8})
                    sim_s = rng.normal(dist_s["mean"], dist_s["std"], SIMULATION_COUNT)
                    player_sims[(pid, stat)] = sim_s.clip(0)

        elapsed = time.time() - t0
        logger.info(f"  Game-level simulation complete in {elapsed:.2f}s — {len(player_sims)} player-stat arrays")

        return player_sims

    finally:
        if close:
            conn.close()
