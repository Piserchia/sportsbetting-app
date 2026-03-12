"""
models/lineup_features.py
Lineup impact features based on player on/off splits.

Computes how a player's stats change when specific teammates are out
(injured/DNP). Uses historical game logs cross-referenced with injury data
to build on/off splits per player pair.

Features added:
    usage_delta_teammate_out    — total usage boost from all currently injured teammates
    assist_delta_teammate_out   — total assist boost from all currently injured teammates
    rebound_delta_teammate_out  — total rebound boost from all currently injured teammates

Also populates the player_onoff_splits table.
"""

from __future__ import annotations

import logging
import pandas as pd
import numpy as np

from backend.database.connection import get_connection, init_model_schema

logger = logging.getLogger(__name__)

# Minimum games "without" to trust the split
MIN_SAMPLE_WITHOUT = 3
# Bayesian shrinkage cap
SHRINKAGE_CAP = 10


def _add_onoff_schema(conn):
    """Create player_onoff_splits table if not exists."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS player_onoff_splits (
            player_id       TEXT,
            teammate_id     TEXT,
            stat            TEXT,
            mean_with       DOUBLE,
            mean_without    DOUBLE,
            delta           DOUBLE,
            sample_size     INTEGER,
            PRIMARY KEY (player_id, teammate_id, stat)
        )
    """)


def build_onoff_splits(conn=None) -> pd.DataFrame:
    """
    Compute on/off splits for all player-teammate pairs and write to
    player_onoff_splits table.

    Returns the splits DataFrame.
    """
    close = conn is None
    conn = conn or get_connection()
    init_model_schema(conn)
    _add_onoff_schema(conn)

    try:
        # Get all game logs with team info
        logs = conn.execute("""
            SELECT
                pgl.player_id,
                pgl.game_id,
                pgl.game_date,
                pgl.points,
                pgl.rebounds,
                pgl.assists,
                pgl.minutes,
                pgs.team_id
            FROM player_game_logs pgl
            JOIN player_game_stats pgs
              ON pgl.game_id = pgs.game_id
             AND CAST(pgs.player_id AS TEXT) = pgl.player_id
            WHERE pgl.minutes > 0
        """).df()

        if logs.empty:
            return pd.DataFrame()

        logs["player_id"] = logs["player_id"].astype(str)
        logs["team_id"] = logs["team_id"].astype(str)

        # Build set of (game_id, player_id) combinations where player participated
        played_set = set(zip(logs["game_id"], logs["player_id"]))

        # Group players by team
        player_teams = (
            logs.groupby("player_id")["team_id"]
            .agg(lambda x: x.mode()[0])
            .to_dict()
        )

        # Group logs by player for fast access
        player_logs = {
            pid: grp[["game_id", "points", "rebounds", "assists"]].copy()
            for pid, grp in logs.groupby("player_id")
        }

        # Get all unique games per team
        team_games = logs.groupby("team_id")["game_id"].apply(set).to_dict()

        # For each player, find teammates (same team), compute splits
        records = []
        teams_to_players = {}
        for pid, tid in player_teams.items():
            teams_to_players.setdefault(tid, []).append(pid)

        for team_id, players in teams_to_players.items():
            if len(players) < 2:
                continue

            team_game_set = team_games.get(team_id, set())

            for player_id in players:
                p_logs = player_logs.get(player_id)
                if p_logs is None or len(p_logs) < 10:
                    continue

                p_games = set(p_logs["game_id"])

                for teammate_id in players:
                    if teammate_id == player_id:
                        continue

                    t_games = set(player_logs.get(teammate_id, pd.DataFrame()).get("game_id", []))

                    # Games where both played (teammate "on")
                    games_with = p_games & t_games
                    # Games where player played but teammate didn't (teammate "off")
                    games_without = p_games - t_games

                    if len(games_without) < MIN_SAMPLE_WITHOUT:
                        continue

                    with_df = p_logs[p_logs["game_id"].isin(games_with)]
                    without_df = p_logs[p_logs["game_id"].isin(games_without)]

                    for stat in ["points", "rebounds", "assists"]:
                        mean_with = float(with_df[stat].mean()) if len(with_df) > 0 else 0.0
                        mean_without = float(without_df[stat].mean())
                        raw_delta = mean_without - mean_with

                        # Bayesian shrinkage
                        shrinkage = min(len(games_without), SHRINKAGE_CAP) / SHRINKAGE_CAP
                        delta = raw_delta * shrinkage

                        records.append({
                            "player_id": player_id,
                            "teammate_id": teammate_id,
                            "stat": stat,
                            "mean_with": round(mean_with, 4),
                            "mean_without": round(mean_without, 4),
                            "delta": round(delta, 4),
                            "sample_size": len(games_without),
                        })

        if not records:
            logger.info("  No on/off splits computed (insufficient data)")
            return pd.DataFrame()

        splits_df = pd.DataFrame(records)

        conn.execute("DELETE FROM player_onoff_splits")
        conn.execute("INSERT INTO player_onoff_splits SELECT * FROM splits_df")
        logger.info(f"  → {len(splits_df)} on/off split rows written")

        return splits_df

    finally:
        if close:
            conn.close()


def build_lineup_features(conn=None) -> pd.DataFrame:
    """
    Build per-player lineup impact features based on currently injured teammates.

    Uses player_onoff_splits + player_injuries to compute expected stat deltas
    for each player given who is currently out.

    Returns DataFrame with columns:
        game_id, player_id,
        usage_delta_teammate_out, assist_delta_teammate_out, rebound_delta_teammate_out
    """
    close = conn is None
    conn = conn or get_connection()
    _add_onoff_schema(conn)

    try:
        # Get current injuries (Out or Doubtful)
        try:
            injuries = conn.execute("""
                SELECT DISTINCT player_id
                FROM player_injuries
                WHERE status IN ('Out', 'Doubtful')
            """).df()
            injured_ids = set(injuries["player_id"].astype(str))
        except Exception:
            injured_ids = set()

        if not injured_ids:
            logger.info("  No injured players — lineup features will be neutral")

        # Get on/off splits
        try:
            splits = conn.execute("SELECT * FROM player_onoff_splits").df()
        except Exception:
            splits = pd.DataFrame()

        if splits.empty:
            # Try computing them first
            splits = build_onoff_splits(conn)

        if splits.empty:
            return pd.DataFrame()

        # Get latest game_id per player from player_features
        try:
            latest_games = conn.execute("""
                SELECT player_id, game_id
                FROM player_features
            """).df()
        except Exception:
            latest_games = conn.execute("""
                SELECT DISTINCT player_id, game_id
                FROM player_game_logs
            """).df()

        if latest_games.empty:
            return pd.DataFrame()

        # For each player, sum deltas from all currently injured teammates
        splits["player_id"] = splits["player_id"].astype(str)
        splits["teammate_id"] = splits["teammate_id"].astype(str)

        # Filter splits to injured teammates only
        injured_splits = splits[splits["teammate_id"].isin(injured_ids)].copy()

        # Aggregate deltas per player per stat
        if injured_splits.empty:
            # No injured teammates with splits — return neutral features
            result = latest_games[["game_id", "player_id"]].copy()
            result["usage_delta_teammate_out"] = 0.0
            result["assist_delta_teammate_out"] = 0.0
            result["rebound_delta_teammate_out"] = 0.0
            return result

        agg = (
            injured_splits
            .groupby(["player_id", "stat"])["delta"]
            .sum()
            .reset_index()
        )

        # Pivot to wide format
        pivot = agg.pivot(index="player_id", columns="stat", values="delta").fillna(0.0)
        pivot = pivot.rename(columns={
            "points": "usage_delta_teammate_out",
            "assists": "assist_delta_teammate_out",
            "rebounds": "rebound_delta_teammate_out",
        })

        for col in ["usage_delta_teammate_out", "assist_delta_teammate_out", "rebound_delta_teammate_out"]:
            if col not in pivot.columns:
                pivot[col] = 0.0

        pivot = pivot.reset_index()

        # Merge with latest game info
        result = latest_games.merge(pivot, on="player_id", how="left")
        for col in ["usage_delta_teammate_out", "assist_delta_teammate_out", "rebound_delta_teammate_out"]:
            result[col] = result[col].fillna(0.0).round(4)

        return result[["game_id", "player_id", "usage_delta_teammate_out",
                        "assist_delta_teammate_out", "rebound_delta_teammate_out"]]

    finally:
        if close:
            conn.close()
