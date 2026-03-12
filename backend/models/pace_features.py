"""
models/pace_features.py
Computes team pace from box score data and generates game-level pace context
for use in projection adjustments.

Pace formula:  possessions ≈ FGA + 0.44*FTA - ORB + TOV
(ORB not available in standard box scores, so we omit it — standard approximation)

Outputs fields added to player_features:
    team_pace, opponent_pace, expected_game_pace, pace_adjustment_factor
"""

import logging
import pandas as pd
import numpy as np

from backend.database.connection import get_connection

logger = logging.getLogger(__name__)


def compute_team_pace(conn=None) -> pd.DataFrame:
    """
    Compute rolling team pace from team_game_stats.
    Returns a DataFrame indexed by (game_id, team_id) with pace columns.
    """
    close = conn is None
    conn = conn or get_connection()

    try:
        tgs = conn.execute("""
            SELECT
                tgs.game_id,
                tgs.team_id,
                g.game_date,
                tgs.fga,
                tgs.fta,
                tgs.tov
            FROM team_game_stats tgs
            JOIN games g ON tgs.game_id = g.game_id
            WHERE tgs.fga IS NOT NULL
            ORDER BY tgs.team_id, g.game_date ASC
        """).df()
    finally:
        if close:
            conn.close()

    if tgs.empty:
        logger.warning("No team_game_stats found for pace computation.")
        return pd.DataFrame()

    # possessions ≈ FGA + 0.44*FTA + TOV  (ORB omitted — not in standard box)
    tgs["possessions"] = tgs["fga"] + 0.44 * tgs["fta"] + tgs["tov"].fillna(0)

    # Rolling 10-game team pace per team
    records = []
    for team_id, group in tgs.groupby("team_id"):
        group = group.sort_values("game_date").reset_index(drop=True)
        rolling_pace = group["possessions"].rolling(10, min_periods=1).mean()
        for i, row in group.iterrows():
            records.append({
                "game_id":    row["game_id"],
                "team_id":    int(team_id),
                "team_pace":  round(float(rolling_pace.iloc[i]), 4),
            })

    return pd.DataFrame(records)


def build_pace_features(conn=None) -> pd.DataFrame:
    """
    Build pace adjustment features per player per game.

    Returns a DataFrame with columns:
        game_id, player_id, team_pace, opponent_pace,
        expected_game_pace, pace_adjustment_factor
    """
    close = conn is None
    conn = conn or get_connection()

    try:
        team_pace_df = compute_team_pace(conn)
        if team_pace_df.empty:
            logger.warning("Pace computation returned empty — skipping pace features.")
            return pd.DataFrame()

        # League average pace (scalar)
        league_avg_pace = float(team_pace_df["team_pace"].mean())
        if league_avg_pace == 0:
            league_avg_pace = 100.0  # fallback

        logger.info(f"  League average pace: {league_avg_pace:.1f} possessions/game")

        # Map game_id + team_id → team_pace
        pace_lookup = team_pace_df.set_index(["game_id", "team_id"])["team_pace"].to_dict()

        # Get player → team mapping per game from player_game_stats
        player_teams = conn.execute("""
            SELECT
                pgs.game_id,
                CAST(pgs.player_id AS TEXT) AS player_id,
                pgs.team_id,
                g.home_team_id,
                g.away_team_id
            FROM player_game_stats pgs
            JOIN games g ON pgs.game_id = g.game_id
            WHERE pgs.pts IS NOT NULL
            AND g.home_team_id IS NOT NULL
            AND g.away_team_id IS NOT NULL
        """).df()

        if player_teams.empty:
            return pd.DataFrame()

        records = []
        for _, row in player_teams.iterrows():
            game_id    = row["game_id"]
            player_id  = str(row["player_id"])
            try:
                team_id = int(row["team_id"])
                home_id = int(row["home_team_id"])
                away_id = int(row["away_team_id"])
            except (ValueError, TypeError):
                continue  # skip rows with null team ids
            opp_id = away_id if team_id == home_id else home_id

            team_pace = pace_lookup.get((game_id, team_id), league_avg_pace)
            opp_pace  = pace_lookup.get((game_id, opp_id),  league_avg_pace)

            expected_pace      = (team_pace + opp_pace) / 2
            pace_adj_factor    = expected_pace / league_avg_pace

            records.append({
                "game_id":              game_id,
                "player_id":            player_id,
                "team_pace":            round(team_pace, 4),
                "opponent_pace":        round(opp_pace, 4),
                "expected_game_pace":   round(expected_pace, 4),
                "pace_adjustment_factor": round(pace_adj_factor, 4),
            })

        return pd.DataFrame(records)

    finally:
        if close:
            conn.close()
