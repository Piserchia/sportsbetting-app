"""
models/advanced_defense_features.py
Possession-adjusted offensive and defensive ratings per team per game.

Replaces raw box-score-based defense adjustments with per-100-possession metrics.

Features added to player_features:
    opponent_def_rating     — opponent's defensive rating (pts allowed per 100 poss)
    team_off_rating         — team's offensive rating (pts scored per 100 poss)
    rating_matchup_factor   — team_off_rating / opponent_def_rating (>1 = favorable)

Also populates the team_advanced_stats table with rolling 10-game averages.
"""

from __future__ import annotations

import logging
import pandas as pd
import numpy as np

from backend.db.connection import get_connection, init_model_schema

logger = logging.getLogger(__name__)


def _compute_possessions(fga, fta, tov, oreb=None):
    """
    Estimate possessions from box score stats.
    Formula: possessions ≈ FGA + 0.44*FTA + TOV - OREB
    If OREB not available, approximate as 0.28 * (FGA - FGM) but since
    we don't have FGM here, just omit OREB term.
    """
    poss = fga + 0.44 * fta + tov
    if oreb is not None:
        poss = poss - oreb
    return poss


def build_advanced_defense_features(conn=None) -> pd.DataFrame:
    """
    Compute possession-adjusted ratings and write to team_advanced_stats.

    Returns DataFrame with columns:
        game_id, player_id,
        opponent_def_rating, team_off_rating, rating_matchup_factor
    """
    close = conn is None
    conn = conn or get_connection()
    init_model_schema(conn)

    try:
        # Get team game stats with shooting details for possession estimation
        tgs = conn.execute("""
            SELECT
                tgs.game_id,
                tgs.team_id,
                tgs.pts,
                tgs.fga,
                tgs.fta,
                tgs.tov,
                tgs.reb,
                g.game_date,
                g.home_team_id,
                g.away_team_id
            FROM team_game_stats tgs
            JOIN games g ON tgs.game_id = g.game_id
            WHERE tgs.pts IS NOT NULL AND tgs.fga IS NOT NULL
            ORDER BY tgs.team_id, g.game_date
        """).df()

        if tgs.empty:
            logger.warning("No team_game_stats data for advanced defense features.")
            return pd.DataFrame()

        # Compute possessions and ratings per team per game
        tgs["possessions"] = _compute_possessions(
            tgs["fga"].fillna(0).astype(float),
            tgs["fta"].fillna(0).astype(float),
            tgs["tov"].fillna(0).astype(float),
        )
        tgs["possessions"] = tgs["possessions"].clip(lower=1.0)  # avoid division by zero

        # Off rating = pts scored / possessions * 100
        tgs["off_rating"] = (tgs["pts"].astype(float) / tgs["possessions"]) * 100

        # To get def rating, we need the opposing team's points in the same game
        # Build opponent lookup: for each (game_id, team_id), find opponent's pts and possessions
        game_teams = tgs[["game_id", "team_id", "pts", "possessions", "off_rating"]].copy()
        game_teams = game_teams.rename(columns={
            "team_id": "opp_team_id",
            "pts": "opp_pts",
            "possessions": "opp_possessions",
            "off_rating": "opp_off_rating",
        })

        # For each game, there are 2 teams. Merge to get opponent stats.
        tgs_with_opp = tgs.merge(
            game_teams,
            on="game_id",
            how="inner",
        )
        # Filter to only cross-team rows (not self-joins)
        tgs_with_opp = tgs_with_opp[
            tgs_with_opp["team_id"] != tgs_with_opp["opp_team_id"]
        ].copy()

        # Def rating = opponent pts allowed / team's possessions * 100
        # (how many points the opponent scored against this team, per 100 possessions)
        tgs_with_opp["def_rating"] = (
            tgs_with_opp["opp_pts"].astype(float) / tgs_with_opp["possessions"]
        ) * 100

        # Use average possessions between both teams as "pace"
        tgs_with_opp["pace"] = (
            (tgs_with_opp["possessions"] + tgs_with_opp["opp_possessions"]) / 2
        )

        # Write raw per-game stats to team_advanced_stats
        adv_stats = tgs_with_opp[["game_id", "team_id", "off_rating", "def_rating", "pace", "possessions"]].copy()
        conn.execute("DELETE FROM team_advanced_stats")
        conn.execute("INSERT INTO team_advanced_stats SELECT * FROM adv_stats")
        logger.info(f"  → {len(adv_stats)} rows written to team_advanced_stats")

        # Compute rolling 10-game averages per team
        tgs_with_opp = tgs_with_opp.sort_values(["team_id", "game_date"])
        tgs_with_opp["rolling_off_rating"] = (
            tgs_with_opp.groupby("team_id")["off_rating"]
            .transform(lambda x: x.rolling(10, min_periods=1).mean())
        )
        tgs_with_opp["rolling_def_rating"] = (
            tgs_with_opp.groupby("team_id")["def_rating"]
            .transform(lambda x: x.rolling(10, min_periods=1).mean())
        )

        # Build lookup: (game_id, team_id) → rolling ratings
        rating_lookup = {}
        for _, row in tgs_with_opp.iterrows():
            rating_lookup[(row["game_id"], int(row["team_id"]))] = {
                "off_rating": float(row["rolling_off_rating"]),
                "def_rating": float(row["rolling_def_rating"]),
            }

        # Now map to players: for each player-game, get their team's off_rating
        # and opponent's def_rating
        player_teams = conn.execute("""
            SELECT
                pgl.game_id,
                pgl.player_id,
                pgs.team_id,
                g.home_team_id,
                g.away_team_id
            FROM player_game_logs pgl
            JOIN player_game_stats pgs
              ON pgl.game_id = pgs.game_id
             AND CAST(pgs.player_id AS TEXT) = pgl.player_id
            JOIN games g ON pgl.game_id = g.game_id
        """).df()

        records = []
        for _, row in player_teams.iterrows():
            game_id = row["game_id"]
            team_id = int(row["team_id"])
            home_id = int(row["home_team_id"])
            away_id = int(row["away_team_id"])
            opp_id = away_id if team_id == home_id else home_id

            team_ratings = rating_lookup.get((game_id, team_id), {})
            opp_ratings = rating_lookup.get((game_id, opp_id), {})

            off_rating = team_ratings.get("off_rating", 110.0)
            def_rating = opp_ratings.get("def_rating", 110.0)

            # rating_matchup_factor > 1 means favorable matchup
            matchup = off_rating / max(def_rating, 1.0)

            records.append({
                "game_id": game_id,
                "player_id": str(row["player_id"]),
                "team_off_rating": round(off_rating, 2),
                "opponent_def_rating": round(def_rating, 2),
                "rating_matchup_factor": round(matchup, 4),
            })

        result = pd.DataFrame(records)
        logger.info(f"  → {len(result)} advanced defense feature rows")
        return result

    finally:
        if close:
            conn.close()
