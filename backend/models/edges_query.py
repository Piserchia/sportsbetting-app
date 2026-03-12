"""
models/edges_query.py
Aggregated edge query — best book per prop line, ranked by bet score.

bet_score = (edge_percent * 0.6) + (model_probability * 25)
"""


def get_best_edges(conn, limit=100, min_edge=0.0):
    """
    Returns the best sportsbook line per (player, stat, line) with ranking score.
    Deduplicates books — one row per prop.
    """
    query = """
    WITH today_edges AS (
        SELECT
            pe.game_id,
            pe.player_id,
            p.full_name          AS player_name,
            g.home_team_abbr,
            g.away_team_abbr,
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
            ROW_NUMBER() OVER (
                PARTITION BY pe.game_id, pe.player_id, pe.stat, pe.line
                ORDER BY pe.edge_percent DESC
            ) AS book_rank
        FROM prop_edges pe
        JOIN games g ON pe.game_id = g.game_id
        JOIN players p ON CAST(pe.player_id AS INTEGER) = p.player_id
        LEFT JOIN player_projections pr
            ON pe.player_id = pr.player_id
            AND pe.game_id  = pr.game_id
        WHERE g.game_date = CURRENT_DATE
          AND pe.book != 'model_only'
          AND pe.edge_percent IS NOT NULL
    )
    SELECT *,
        ROUND((edge_percent * 0.6) + (model_probability * 25), 3) AS bet_score
    FROM today_edges
    WHERE book_rank = 1
      AND edge_percent >= ?
    ORDER BY bet_score DESC
    LIMIT ?
    """
    return conn.execute(query, [min_edge, limit]).df()
