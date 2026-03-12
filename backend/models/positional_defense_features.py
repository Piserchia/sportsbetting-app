"""
models/positional_defense_features.py
Opponent defensive stats broken down by player position.

Positions are grouped into 5 buckets:
    PG, SG, SF, PF, C

For each team/game we compute rolling 10-game averages of pts/reb/ast
allowed to each position group. These produce per-player adjustment
factors based on the opponent's positional defensive strength.

Features added:
    defense_vs_pg, defense_vs_sg, defense_vs_sf, defense_vs_pf, defense_vs_c
    positional_defense_adj  (the relevant factor for each player's position)
"""

from __future__ import annotations

import logging
import pandas as pd
import numpy as np

from backend.db.connection import get_connection

logger = logging.getLogger(__name__)

# Map raw position strings to canonical 5 buckets
POSITION_MAP = {
    # Point guards
    "PG": "PG", "G": "PG",
    # Shooting guards
    "SG": "SG", "G-F": "SG",
    # Small forwards
    "SF": "SF", "F": "SF", "F-G": "SF",
    # Power forwards
    "PF": "PF", "F-C": "PF",
    # Centers
    "C": "C", "C-F": "C",
}

POSITIONS = ["PG", "SG", "SF", "PF", "C"]


def _normalize_position(pos: str) -> str:
    """Map a raw position string to one of the 5 canonical positions."""
    if not pos or pd.isna(pos):
        return "SF"  # default to SF (modal position)
    pos = str(pos).strip().upper()
    return POSITION_MAP.get(pos, "SF")


def build_positional_defense_features(conn=None) -> pd.DataFrame:
    """
    Compute opponent defensive stats by position for every player-game.

    Returns DataFrame with columns:
        game_id, player_id, player_position,
        defense_vs_pg, defense_vs_sg, defense_vs_sf, defense_vs_pf, defense_vs_c,
        positional_defense_adj_pts, positional_defense_adj_reb, positional_defense_adj_ast
    """
    close = conn is None
    conn  = conn or get_connection()

    try:
        # Get player positions from nba_api players table (if available)
        # or infer from common position data
        try:
            pos_df = conn.execute("""
                SELECT
                    CAST(pgs.player_id AS TEXT) AS player_id,
                    pgs.game_id,
                    pgs.team_id,
                    pgs.pts,
                    pgs.reb,
                    pgs.ast,
                    g.game_date,
                    g.home_team_id,
                    g.away_team_id
                FROM player_game_stats pgs
                JOIN games g ON pgs.game_id = g.game_id
                WHERE pgs.pts IS NOT NULL
            """).df()
        except Exception as e:
            logger.warning(f"Could not load player stats for positional defense: {e}")
            return pd.DataFrame()

        if pos_df.empty:
            return pd.DataFrame()

        # Try to get positions from a positions table / player metadata
        # nba_api doesn't reliably give position in box scores
        # We use a heuristic: assign positions based on stat ratios
        # (high reb/game = C/PF, high ast/game = PG, etc.)
        # This is computed per player across their season logs
        try:
            player_avg = conn.execute("""
                SELECT
                    CAST(player_id AS TEXT) AS player_id,
                    AVG(CAST(pts AS DOUBLE))  AS avg_pts,
                    AVG(CAST(reb AS DOUBLE))  AS avg_reb,
                    AVG(CAST(ast AS DOUBLE))  AS avg_ast
                FROM player_game_stats
                WHERE pts IS NOT NULL
                GROUP BY player_id
            """).df()
        except Exception:
            player_avg = pd.DataFrame()

        # Infer position from rebounding/assist ratios
        def infer_position(row) -> str:
            if pd.isna(row.get("avg_reb")) or pd.isna(row.get("avg_ast")):
                return "SF"
            reb = float(row["avg_reb"])
            ast = float(row["avg_ast"])
            pts = float(row.get("avg_pts", 10.0))
            if reb >= 7.0:
                return "C" if reb >= 9.0 else "PF"
            if ast >= 6.0:
                return "PG"
            if ast >= 4.0:
                return "SG"
            return "SF"

        if not player_avg.empty:
            player_avg["position"] = player_avg.apply(infer_position, axis=1)
            pos_map = dict(zip(player_avg["player_id"], player_avg["position"]))
        else:
            pos_map = {}

        pos_df["position"] = pos_df["player_id"].map(pos_map).fillna("SF")

        # For each game, compute pts/reb/ast scored by position GROUP against each team
        # "team X allowed Y pts to PGs in game Z" = sum of scoring PG's stats
        #  when they played against team X

        records_allowed = []
        for _, row in pos_df.iterrows():
            game_id  = row["game_id"]
            team_id  = row["team_id"]
            home_id  = row["home_team_id"]
            away_id  = row["away_team_id"]
            # defending team = the other team
            try:
                def_team = int(away_id) if int(team_id) == int(home_id) else int(home_id)
            except (ValueError, TypeError):
                continue

            records_allowed.append({
                "game_id":   game_id,
                "game_date": row["game_date"],
                "def_team":  def_team,
                "position":  row["position"],
                "pts":       float(row["pts"] or 0),
                "reb":       float(row["reb"] or 0),
                "ast":       float(row["ast"] or 0),
            })

        if not records_allowed:
            return pd.DataFrame()

        allowed_df = pd.DataFrame(records_allowed)
        allowed_df["game_date"] = pd.to_datetime(allowed_df["game_date"])

        # Aggregate: per defending team, per game, per position
        agg = (
            allowed_df
            .groupby(["def_team", "game_id", "game_date", "position"])
            [["pts", "reb", "ast"]]
            .sum()
            .reset_index()
        )

        # Rolling 10-game average per team per position
        rolling_records = []
        for (def_team, position), group in agg.groupby(["def_team", "position"]):
            group = group.sort_values("game_date").reset_index(drop=True)
            roll_pts = group["pts"].rolling(10, min_periods=1).mean()
            roll_reb = group["reb"].rolling(10, min_periods=1).mean()
            roll_ast = group["ast"].rolling(10, min_periods=1).mean()
            for i, r in group.iterrows():
                rolling_records.append({
                    "def_team": def_team,
                    "game_id":  r["game_id"],
                    "position": position,
                    "avg_pts_allowed": float(roll_pts.iloc[i]),
                    "avg_reb_allowed": float(roll_reb.iloc[i]),
                    "avg_ast_allowed": float(roll_ast.iloc[i]),
                })

        rolling_df = pd.DataFrame(rolling_records)

        # League averages per position
        league_pos_avg = (
            rolling_df
            .groupby("position")[["avg_pts_allowed", "avg_reb_allowed", "avg_ast_allowed"]]
            .mean()
            .to_dict("index")
        )

        # Build per-player per-game positional defense adjustment
        output_records = []
        for _, row in pos_df.iterrows():
            game_id   = row["game_id"]
            player_id = str(row["player_id"])
            position  = str(row["position"])
            team_id   = row["team_id"]
            home_id   = row["home_team_id"]
            away_id   = row["away_team_id"]

            try:
                def_team = int(away_id) if int(team_id) == int(home_id) else int(home_id)
            except (ValueError, TypeError):
                continue

            # Get rolling allowed for this defending team / position
            match = rolling_df[
                (rolling_df["def_team"] == def_team) &
                (rolling_df["game_id"]  == game_id) &
                (rolling_df["position"] == position)
            ]

            if match.empty:
                pos_def_pts_adj = 1.0
                pos_def_reb_adj = 1.0
                pos_def_ast_adj = 1.0
            else:
                league_pos = league_pos_avg.get(position, {})
                l_pts = max(league_pos.get("avg_pts_allowed", 8.0), 1.0)
                l_reb = max(league_pos.get("avg_reb_allowed", 3.5), 1.0)
                l_ast = max(league_pos.get("avg_ast_allowed", 2.5), 1.0)

                pos_def_pts_adj = float(match["avg_pts_allowed"].iloc[-1]) / l_pts
                pos_def_reb_adj = float(match["avg_reb_allowed"].iloc[-1]) / l_reb
                pos_def_ast_adj = float(match["avg_ast_allowed"].iloc[-1]) / l_ast

            # Also build the positional defense pivot (one column per position)
            # for all 5 positions for this defending team in this game
            pos_allowed = {}
            for pos in POSITIONS:
                pm = rolling_df[
                    (rolling_df["def_team"] == def_team) &
                    (rolling_df["game_id"]  == game_id) &
                    (rolling_df["position"] == pos)
                ]
                if not pm.empty:
                    pos_allowed[f"defense_vs_{pos.lower()}"] = float(
                        pm["avg_pts_allowed"].iloc[-1]
                    )
                else:
                    pos_allowed[f"defense_vs_{pos.lower()}"] = league_pos_avg.get(
                        pos, {}
                    ).get("avg_pts_allowed", 8.0)

            output_records.append({
                "game_id":                   game_id,
                "player_id":                 player_id,
                "player_position":           position,
                **pos_allowed,
                "positional_defense_adj_pts": round(np.clip(pos_def_pts_adj, 0.75, 1.30), 4),
                "positional_defense_adj_reb": round(np.clip(pos_def_reb_adj, 0.75, 1.30), 4),
                "positional_defense_adj_ast": round(np.clip(pos_def_ast_adj, 0.75, 1.30), 4),
            })

        return pd.DataFrame(output_records)

    finally:
        if close:
            conn.close()
