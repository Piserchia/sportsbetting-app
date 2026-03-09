"""
models/defense_features.py
Computes opponent defensive strength per game and generates defense
adjustment factors for projection scaling.

Metrics:
  - points / rebounds / assists allowed per game (rolling 10)
  - positional splits where position data is available
  - defense_adjustment_factor = opponent_stat_allowed / league_average_stat

Outputs fields added to player_features:
    opponent_points_allowed, opponent_rebounds_allowed,
    opponent_assists_allowed, defense_adjustment_factor
"""

import logging
import pandas as pd
import numpy as np

from backend.db.connection import get_connection

logger = logging.getLogger(__name__)


def build_defense_features(conn=None) -> pd.DataFrame:
    """
    Compute per-player opponent defensive context for every game.

    Returns a DataFrame with columns:
        game_id, player_id,
        opponent_points_allowed, opponent_rebounds_allowed, opponent_assists_allowed,
        defense_adj_pts, defense_adj_reb, defense_adj_ast
    """
    close = conn is None
    conn = conn or get_connection()

    try:
        # Aggregate opponent stats allowed per team per game
        # "Points allowed by team X in game Y" = sum of opponent player pts in that game
        allowed = conn.execute("""
            SELECT
                g.game_id,
                g.game_date,
                -- For home team: allowed = away players' stats
                -- We pull both sides: team_id = defensive team
                CASE
                    WHEN pgs.team_id = g.home_team_id THEN g.away_team_id
                    ELSE g.home_team_id
                END AS defending_team_id,
                pgs.team_id AS scoring_team_id,
                SUM(pgs.pts) AS pts_allowed,
                SUM(pgs.reb) AS reb_allowed,
                SUM(pgs.ast) AS ast_allowed
            FROM player_game_stats pgs
            JOIN games g ON pgs.game_id = g.game_id
            WHERE pgs.pts IS NOT NULL
            GROUP BY g.game_id, g.game_date, defending_team_id, scoring_team_id
        """).df()

        if allowed.empty:
            logger.warning("No data for defense features — skipping.")
            return pd.DataFrame()

        # League average stats allowed per game
        league_avg = {
            "pts": float(allowed["pts_allowed"].mean()),
            "reb": float(allowed["reb_allowed"].mean()),
            "ast": float(allowed["ast_allowed"].mean()),
        }
        # Clamp to avoid division by zero
        league_avg = {k: max(v, 1.0) for k, v in league_avg.items()}
        logger.info(
            f"  League avg allowed — pts: {league_avg['pts']:.1f}, "
            f"reb: {league_avg['reb']:.1f}, ast: {league_avg['ast']:.1f}"
        )

        # Rolling 10-game defensive averages per defending team
        def_records = {}
        for def_team_id, group in allowed.groupby("defending_team_id"):
            group = group.sort_values("game_date").reset_index(drop=True)
            roll_pts = group["pts_allowed"].rolling(10, min_periods=1).mean()
            roll_reb = group["reb_allowed"].rolling(10, min_periods=1).mean()
            roll_ast = group["ast_allowed"].rolling(10, min_periods=1).mean()
            for i, row in group.iterrows():
                def_records[(row["game_id"], int(def_team_id))] = {
                    "opp_pts_allowed": round(float(roll_pts.iloc[i]), 4),
                    "opp_reb_allowed": round(float(roll_reb.iloc[i]), 4),
                    "opp_ast_allowed": round(float(roll_ast.iloc[i]), 4),
                }

        # Map to players: for each player find their opponent (defending team)
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
        """).df()

        records = []
        for _, row in player_teams.iterrows():
            game_id   = row["game_id"]
            player_id = str(row["player_id"])
            team_id   = int(row["team_id"])
            home_id   = int(row["home_team_id"])
            away_id   = int(row["away_team_id"])
            opp_id    = away_id if team_id == home_id else home_id

            def_stats = def_records.get(
                (game_id, opp_id),
                {
                    "opp_pts_allowed": league_avg["pts"],
                    "opp_reb_allowed": league_avg["reb"],
                    "opp_ast_allowed": league_avg["ast"],
                }
            )

            # defense_adj = how generous the opponent defense is vs league average
            # > 1.0 means opponent allows more than average → favorable
            # < 1.0 means opponent allows less than average → tough
            def_adj_pts = def_stats["opp_pts_allowed"] / league_avg["pts"]
            def_adj_reb = def_stats["opp_reb_allowed"] / league_avg["reb"]
            def_adj_ast = def_stats["opp_ast_allowed"] / league_avg["ast"]

            records.append({
                "game_id":                  game_id,
                "player_id":                player_id,
                "opponent_points_allowed":  def_stats["opp_pts_allowed"],
                "opponent_rebounds_allowed": def_stats["opp_reb_allowed"],
                "opponent_assists_allowed": def_stats["opp_ast_allowed"],
                "defense_adj_pts":          round(def_adj_pts, 4),
                "defense_adj_reb":          round(def_adj_reb, 4),
                "defense_adj_ast":          round(def_adj_ast, 4),
            })

        return pd.DataFrame(records)

    finally:
        if close:
            conn.close()
