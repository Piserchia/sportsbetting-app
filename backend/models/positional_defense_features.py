"""
models/positional_defense_features.py
Opponent defensive stats broken down by player position.

Positions are grouped into 5 buckets:
    PG, SG, SF, PF, C

For each team/game we compute rolling 10-game averages of pts/reb/ast
allowed to each position group. These produce per-player adjustment
factors based on the opponent's positional defensive strength.

v2: Rewritten to use DuckDB SQL window functions instead of Python loops
    for ~100x performance improvement (minutes → seconds).

Features added:
    defense_vs_pg, defense_vs_sg, defense_vs_sf, defense_vs_pf, defense_vs_c
    positional_defense_adj  (the relevant factor for each player's position)
"""

from __future__ import annotations

import logging
import pandas as pd
import numpy as np

from backend.database.connection import get_connection

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

    Uses DuckDB SQL window functions for performance.

    Returns DataFrame with columns:
        game_id, player_id, player_position,
        defense_vs_pg, defense_vs_sg, defense_vs_sf, defense_vs_pf, defense_vs_c,
        positional_defense_adj_pts, positional_defense_adj_reb, positional_defense_adj_ast
    """
    close = conn is None
    conn  = conn or get_connection()

    try:
        # Step 1: Infer player positions from season averages
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

        if player_avg.empty:
            return pd.DataFrame()

        def infer_position(row) -> str:
            if pd.isna(row.get("avg_reb")) or pd.isna(row.get("avg_ast")):
                return "SF"
            reb = float(row["avg_reb"])
            ast = float(row["avg_ast"])
            if reb >= 7.0:
                return "C" if reb >= 9.0 else "PF"
            if ast >= 6.0:
                return "PG"
            if ast >= 4.0:
                return "SG"
            return "SF"

        player_avg["position"] = player_avg.apply(infer_position, axis=1)

        # Register position lookup as a DuckDB temp table
        pos_lookup = player_avg[["player_id", "position"]].copy()
        conn.execute("CREATE OR REPLACE TEMP TABLE _pos_lookup AS SELECT * FROM pos_lookup")

        # Step 2: Build per-game stats with defending team and position using SQL
        # This computes: for each player-game, the defending team (opponent) and position
        conn.execute("""
            CREATE OR REPLACE TEMP TABLE _player_game_pos AS
            SELECT
                pgs.game_id,
                CAST(pgs.player_id AS TEXT) AS player_id,
                pgs.team_id,
                CAST(pgs.pts AS DOUBLE) AS pts,
                CAST(pgs.reb AS DOUBLE) AS reb,
                CAST(pgs.ast AS DOUBLE) AS ast,
                g.game_date,
                COALESCE(pl.position, 'SF') AS position,
                CASE
                    WHEN CAST(pgs.team_id AS INTEGER) = CAST(g.home_team_id AS INTEGER)
                    THEN CAST(g.away_team_id AS INTEGER)
                    ELSE CAST(g.home_team_id AS INTEGER)
                END AS def_team
            FROM player_game_stats pgs
            JOIN games g ON pgs.game_id = g.game_id
            LEFT JOIN _pos_lookup pl ON CAST(pgs.player_id AS TEXT) = pl.player_id
            WHERE pgs.pts IS NOT NULL
        """)

        # Step 3: Aggregate per defending team / game / position
        conn.execute("""
            CREATE OR REPLACE TEMP TABLE _pos_agg AS
            SELECT
                def_team,
                game_id,
                game_date,
                position,
                SUM(pts) AS pts,
                SUM(reb) AS reb,
                SUM(ast) AS ast
            FROM _player_game_pos
            GROUP BY def_team, game_id, game_date, position
        """)

        # Step 4: Rolling 10-game averages using window functions
        conn.execute("""
            CREATE OR REPLACE TEMP TABLE _rolling_allowed AS
            SELECT
                def_team,
                game_id,
                game_date,
                position,
                AVG(pts) OVER (
                    PARTITION BY def_team, position
                    ORDER BY game_date
                    ROWS BETWEEN 9 PRECEDING AND CURRENT ROW
                ) AS avg_pts_allowed,
                AVG(reb) OVER (
                    PARTITION BY def_team, position
                    ORDER BY game_date
                    ROWS BETWEEN 9 PRECEDING AND CURRENT ROW
                ) AS avg_reb_allowed,
                AVG(ast) OVER (
                    PARTITION BY def_team, position
                    ORDER BY game_date
                    ROWS BETWEEN 9 PRECEDING AND CURRENT ROW
                ) AS avg_ast_allowed
            FROM _pos_agg
        """)

        # Step 5: League averages per position (for adjustment factors)
        league_avg = conn.execute("""
            SELECT
                position,
                AVG(avg_pts_allowed) AS league_avg_pts,
                AVG(avg_reb_allowed) AS league_avg_reb,
                AVG(avg_ast_allowed) AS league_avg_ast
            FROM _rolling_allowed
            GROUP BY position
        """).df()
        league_map = {
            row["position"]: {
                "pts": max(float(row["league_avg_pts"]), 1.0),
                "reb": max(float(row["league_avg_reb"]), 1.0),
                "ast": max(float(row["league_avg_ast"]), 1.0),
            }
            for _, row in league_avg.iterrows()
        }

        # Step 6: Pivot defense_vs columns per defending team/game using SQL
        pivot_df = conn.execute("""
            SELECT
                def_team,
                game_id,
                MAX(CASE WHEN position = 'PG' THEN avg_pts_allowed END) AS defense_vs_pg,
                MAX(CASE WHEN position = 'SG' THEN avg_pts_allowed END) AS defense_vs_sg,
                MAX(CASE WHEN position = 'SF' THEN avg_pts_allowed END) AS defense_vs_sf,
                MAX(CASE WHEN position = 'PF' THEN avg_pts_allowed END) AS defense_vs_pf,
                MAX(CASE WHEN position = 'C'  THEN avg_pts_allowed END) AS defense_vs_c
            FROM _rolling_allowed
            GROUP BY def_team, game_id
        """).df()

        # Step 7: Get rolling allowed for each player's position
        rolling_df = conn.execute("SELECT * FROM _rolling_allowed").df()

        # Step 8: Build output — one row per player-game
        player_games = conn.execute("""
            SELECT
                game_id,
                player_id,
                team_id,
                position,
                def_team
            FROM _player_game_pos
        """).df()

        # Build rolling lookup for fast access
        rolling_lookup = {}
        for _, r in rolling_df.iterrows():
            rolling_lookup[(int(r["def_team"]), r["game_id"], r["position"])] = {
                "pts": float(r["avg_pts_allowed"]),
                "reb": float(r["avg_reb_allowed"]),
                "ast": float(r["avg_ast_allowed"]),
            }

        # Build pivot lookup
        pivot_lookup = {}
        for _, r in pivot_df.iterrows():
            pivot_lookup[(int(r["def_team"]), r["game_id"])] = {
                "defense_vs_pg": r.get("defense_vs_pg"),
                "defense_vs_sg": r.get("defense_vs_sg"),
                "defense_vs_sf": r.get("defense_vs_sf"),
                "defense_vs_pf": r.get("defense_vs_pf"),
                "defense_vs_c":  r.get("defense_vs_c"),
            }

        # Defaults from league averages
        default_pos_pts = {pos: league_map.get(pos, {}).get("pts", 8.0) for pos in POSITIONS}

        output_records = []
        for _, row in player_games.iterrows():
            game_id = row["game_id"]
            player_id = str(row["player_id"])
            position = str(row["position"])
            def_team = int(row["def_team"])

            # Adjustment factors for this player's position
            allowed = rolling_lookup.get((def_team, game_id, position))
            league = league_map.get(position, {"pts": 8.0, "reb": 3.5, "ast": 2.5})

            if allowed:
                adj_pts = allowed["pts"] / league["pts"]
                adj_reb = allowed["reb"] / league["reb"]
                adj_ast = allowed["ast"] / league["ast"]
            else:
                adj_pts = adj_reb = adj_ast = 1.0

            # Pivot columns for all 5 positions
            piv = pivot_lookup.get((def_team, game_id), {})
            pos_allowed = {}
            for pos in POSITIONS:
                col = f"defense_vs_{pos.lower()}"
                val = piv.get(col)
                pos_allowed[col] = float(val) if val is not None and not pd.isna(val) else default_pos_pts[pos]

            output_records.append({
                "game_id": game_id,
                "player_id": player_id,
                "player_position": position,
                **pos_allowed,
                "positional_defense_adj_pts": round(float(np.clip(adj_pts, 0.75, 1.30)), 4),
                "positional_defense_adj_reb": round(float(np.clip(adj_reb, 0.75, 1.30)), 4),
                "positional_defense_adj_ast": round(float(np.clip(adj_ast, 0.75, 1.30)), 4),
            })

        # Clean up temp tables
        for t in ["_pos_lookup", "_player_game_pos", "_pos_agg", "_rolling_allowed"]:
            try:
                conn.execute(f"DROP TABLE IF EXISTS {t}")
            except Exception:
                pass

        return pd.DataFrame(output_records)

    finally:
        if close:
            conn.close()
