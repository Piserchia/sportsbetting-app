"""
models/edges_query.py
Aggregated edge query — all books per prop line, ranked by bet score.

bet_score = (edge_percent * 0.6) + (model_probability * 25)

Projections are joined by (player_id, game_id) to ensure the projection
corresponds to the same event as the edge — never a historical game.
"""

import logging

logger = logging.getLogger(__name__)


def get_best_edges(conn, limit=100, min_edge=0.0, min_line=None, max_line=None):
    """
    Returns all sportsbook rows for each (player, stat, line) combo today.
    Caller groups by prop key to produce a nested books structure.
    """
    params = [min_edge]

    line_filters = ""
    if min_line is not None:
        line_filters += " AND pe.line >= ?"
        params.append(min_line)
    if max_line is not None:
        line_filters += " AND pe.line <= ?"
        params.append(max_line)

    params.append(limit)

    query = f"""
    WITH today_edges AS (
        SELECT
            pe.game_id,
            pe.player_id,
            p.full_name          AS player_name,
            g.home_team_abbr,
            g.away_team_abbr,
            g.status             AS game_status,
            g.game_time_et,
            pe.stat,
            pe.line,
            pe.book,
            pe.sportsbook_odds,
            pe.model_probability,
            pe.fair_odds,
            pe.edge_percent,
            pr.points_mean,
            pr.rebounds_mean,
            pr.assists_mean,
            pr.steals_mean,
            pr.blocks_mean,
            ROUND((pe.edge_percent * 0.6) + (pe.model_probability * 25), 3) AS bet_score
        FROM prop_edges pe
        JOIN games g ON pe.game_id = g.game_id
        JOIN players p ON CAST(pe.player_id AS INTEGER) = p.player_id
        LEFT JOIN player_projections pr
            ON pe.player_id = pr.player_id
            AND pe.game_id  = pr.game_id
        WHERE g.game_date = CURRENT_DATE
          AND pe.book != 'model_only'
          AND pe.edge_percent IS NOT NULL
          AND pe.edge_percent >= ?
          {line_filters}
    )
    SELECT *
    FROM today_edges
    ORDER BY bet_score DESC
    LIMIT ?
    """
    df = conn.execute(query, params).df()

    if not df.empty:
        null_proj = df["points_mean"].isna().sum()
        if null_proj > 0:
            logger.info(
                f"Edges: {null_proj}/{len(df)} rows missing projection "
                f"(no player_projections row matching game_id)"
            )

    return df
