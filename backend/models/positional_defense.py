"""
models/positional_defense.py
Opponent defensive strength broken down by position group.

Positions are bucketed into three groups:
    GUARD  → PG, SG, G (guard-eligible)
    FORWARD→ SF, PF, F (forward-eligible)
    CENTER → C

For each team, computes rolling 10-game averages of:
    pts/reb/ast allowed to each position group

Then derives defense_adj factors vs league average for that position group.

These supplement (rather than replace) the team-level defense_adj from
defense_features.py. The position-specific adjustments are stored in
player_features as additional columns via the feature builder.
"""

import logging
import pandas as pd
import numpy as np

from backend.db.connection import get_connection

logger = logging.getLogger(__name__)

POSITION_MAP = {
    "PG": "GUARD", "SG": "GUARD", "G": "GUARD", "G-F": "GUARD",
    "SF": "FORWARD", "PF": "FORWARD", "F": "FORWARD", "F-G": "FORWARD", "F-C": "FORWARD",
    "C":  "CENTER",  "C-F": "CENTER",
}
DEFAULT_POSITION = "FORWARD"

ROLLING_WINDOW = 10


def _get_player_positions(conn) -> dict:
    """
    Returns {player_id (str): position_group} from player_game_stats.
    Uses the most common position for each player.
    """
    try:
        rows = conn.execute("""
            SELECT CAST(player_id AS TEXT) AS player_id, position
            FROM (
                SELECT pgs.player_id,
                       UPPER(TRIM(pgs.position)) AS position,
                       COUNT(*) AS cnt
                FROM player_game_stats pgs
                WHERE pgs.position IS NOT NULL AND pgs.position != ''
                GROUP BY pgs.player_id, UPPER(TRIM(pgs.position))
            ) t
            WHERE cnt = (
                SELECT MAX(cnt2)
                FROM (
                    SELECT player_id, position, COUNT(*) AS cnt2
                    FROM player_game_stats
                    WHERE position IS NOT NULL AND position != ''
                    GROUP BY player_id, position
                ) t2
                WHERE t2.player_id = t.player_id
            )
        """).fetchall()
        return {str(r[0]): POSITION_MAP.get(r[1], DEFAULT_POSITION) for r in rows}
    except Exception as e:
        logger.warning(f"  Could not load player positions: {e}")
        return {}


def build_positional_defense_features(conn=None) -> pd.DataFrame:
    """
    For every player/game row in player_game_logs, compute:
        pos_defense_adj_pts  — how many pts this team allows to players of this position
        pos_defense_adj_reb
        pos_defense_adj_ast

    Returns DataFrame keyed on (game_id, player_id).
    """
    close = conn is None
    if close:
        conn = get_connection()

    try:
        # ── Load box scores ──────────────────────────────────────────────
        df = conn.execute("""
            SELECT
                pgs.game_id,
                CAST(pgs.player_id AS TEXT) AS player_id,
                CAST(pgs.team_id   AS TEXT) AS team_id,
                pgs.pts, pgs.reb, pgs.ast,
                UPPER(TRIM(pgs.position)) AS position,
                g.game_date,
                -- opponent is the other team in the game
                CASE WHEN pgs.team_id = g.home_team_id
                     THEN CAST(g.away_team_id AS TEXT)
                     ELSE CAST(g.home_team_id AS TEXT)
                END AS opp_team_id
            FROM player_game_stats pgs
            JOIN games g ON pgs.game_id = g.game_id
            WHERE g.status = 'Final'
              AND pgs.pts IS NOT NULL
        """).df()

        if df.empty:
            logger.warning("  No box score data for positional defense features.")
            return pd.DataFrame()

    finally:
        if close:
            conn.close()

    df["position_group"] = df["position"].map(POSITION_MAP).fillna(DEFAULT_POSITION)
    df["game_date"] = pd.to_datetime(df["game_date"])
    df = df.sort_values("game_date")

    # ── Compute per-game stats allowed by each team to each position group ──
    # "allowed" means: stats scored BY opponents OF that position GROUP vs THIS team
    allowed = (
        df.groupby(["game_id", "opp_team_id", "position_group"])[["pts", "reb", "ast"]]
        .sum()
        .reset_index()
        .rename(columns={"opp_team_id": "defending_team_id"})
    )

    # Join game_date back
    game_dates = df[["game_id", "game_date"]].drop_duplicates()
    allowed = allowed.merge(game_dates, on="game_id", how="left").sort_values("game_date")

    # ── Rolling 10-game averages per (defending_team, position_group) ───────
    rolling_records = []
    for (team_id, pos_group), group in allowed.groupby(["defending_team_id", "position_group"]):
        group = group.sort_values("game_date").reset_index(drop=True)
        roll_pts = group["pts"].rolling(ROLLING_WINDOW, min_periods=1).mean()
        roll_reb = group["reb"].rolling(ROLLING_WINDOW, min_periods=1).mean()
        roll_ast = group["ast"].rolling(ROLLING_WINDOW, min_periods=1).mean()
        for i, row in group.iterrows():
            rolling_records.append({
                "game_id":              row["game_id"],
                "defending_team_id":    team_id,
                "position_group":       pos_group,
                "pos_pts_allowed_avg":  round(float(roll_pts.iloc[i]), 4),
                "pos_reb_allowed_avg":  round(float(roll_reb.iloc[i]), 4),
                "pos_ast_allowed_avg":  round(float(roll_ast.iloc[i]), 4),
            })

    roll_df = pd.DataFrame(rolling_records)

    if roll_df.empty:
        return pd.DataFrame()

    # ── League averages per position group ───────────────────────────────────
    league_avgs = (
        roll_df.groupby("position_group")[["pos_pts_allowed_avg", "pos_reb_allowed_avg", "pos_ast_allowed_avg"]]
        .mean()
        .rename(columns={
            "pos_pts_allowed_avg": "lg_pts_avg",
            "pos_reb_allowed_avg": "lg_reb_avg",
            "pos_ast_allowed_avg": "lg_ast_avg",
        })
    )

    # ── Build player-level features ──────────────────────────────────────────
    # For each player/game: look up their position group + opponent's allowed avg
    player_positions = _get_player_positions(
        conn if not close else get_connection()
    ) if True else {}

    df["position_group"] = df["player_id"].map(player_positions).fillna(DEFAULT_POSITION)

    result_records = []
    for _, player_row in df.iterrows():
        player_id  = player_row["player_id"]
        game_id    = player_row["game_id"]
        opp        = player_row["opp_team_id"]
        pos_group  = player_row["position_group"]

        # Find opp's rolling allowed for this position group at this game
        match = roll_df[
            (roll_df["game_id"] == game_id) &
            (roll_df["defending_team_id"] == opp) &
            (roll_df["position_group"] == pos_group)
        ]

        if match.empty:
            # No data yet — default to 1.0 adjustment
            result_records.append({
                "game_id":           game_id,
                "player_id":         player_id,
                "pos_defense_adj_pts": 1.0,
                "pos_defense_adj_reb": 1.0,
                "pos_defense_adj_ast": 1.0,
                "position_group":    pos_group,
            })
            continue

        row = match.iloc[-1]
        lg  = league_avgs.loc[pos_group] if pos_group in league_avgs.index else None

        if lg is not None and lg["lg_pts_avg"] > 0:
            adj_pts = float(np.clip(row["pos_pts_allowed_avg"] / lg["lg_pts_avg"], 0.75, 1.30))
            adj_reb = float(np.clip(row["pos_reb_allowed_avg"] / lg["lg_reb_avg"], 0.75, 1.30)) if lg["lg_reb_avg"] > 0 else 1.0
            adj_ast = float(np.clip(row["pos_ast_allowed_avg"] / lg["lg_ast_avg"], 0.75, 1.30)) if lg["lg_ast_avg"] > 0 else 1.0
        else:
            adj_pts = adj_reb = adj_ast = 1.0

        result_records.append({
            "game_id":             game_id,
            "player_id":           player_id,
            "pos_defense_adj_pts": round(adj_pts, 4),
            "pos_defense_adj_reb": round(adj_reb, 4),
            "pos_defense_adj_ast": round(adj_ast, 4),
            "position_group":      pos_group,
        })

    result = pd.DataFrame(result_records)
    if not result.empty:
        result = result.drop_duplicates(subset=["game_id", "player_id"])
    return result
