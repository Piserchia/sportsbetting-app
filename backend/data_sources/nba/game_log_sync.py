"""
ingestion/game_log_sync.py
Syncs data from player_game_stats (raw nba_api data) into player_game_logs
(the normalized format used by the model pipeline).

This is the bridge between ingestion and modeling layers.
"""

import uuid
import logging
from backend.database.connection import get_connection, init_model_schema

logger = logging.getLogger(__name__)


def sync_game_logs(conn=None) -> int:
    """
    Populates player_game_logs from player_game_stats + games tables.
    Skips game/player combos already present (incremental).
    Returns number of new rows written.
    """
    close = conn is None
    conn = conn or get_connection()
    init_model_schema(conn)

    logger.info("Syncing player_game_stats → player_game_logs...")

    result = conn.execute("""
        INSERT OR IGNORE INTO player_game_logs
        SELECT
            pgs.game_id,
            CAST(pgs.player_id AS TEXT)     AS player_id,
            g.game_date,
            t.abbreviation                  AS team,
            TRY_CAST(
                SPLIT_PART(pgs.min, ':', 1) AS DOUBLE
            ) +
            TRY_CAST(
                SPLIT_PART(pgs.min, ':', 2) AS DOUBLE
            ) / 60.0                        AS minutes,
            COALESCE(pgs.pts, 0)            AS points,
            COALESCE(pgs.reb, 0)            AS rebounds,
            COALESCE(pgs.ast, 0)            AS assists,
            COALESCE(pgs.stl, 0)            AS steals,
            COALESCE(pgs.blk, 0)            AS blocks,
            COALESCE(pgs.tov, 0)            AS turnovers,
            COALESCE(pgs.fga, 0)            AS fg_attempts,
            COALESCE(pgs.fg3a, 0)           AS three_attempts,
            COALESCE(pgs.fta, 0)            AS free_throw_attempts
        FROM player_game_stats pgs
        JOIN games g ON pgs.game_id = g.game_id
        LEFT JOIN teams t ON pgs.team_id = t.team_id
        WHERE pgs.pts IS NOT NULL
    """)

    # DuckDB doesn't return rowcount cleanly for INSERT OR IGNORE, so query it
    count = conn.execute("""
        SELECT COUNT(*) FROM player_game_logs
    """).fetchone()[0]

    logger.info(f"  → player_game_logs now contains {count:,} rows.")
    conn.execute(
        "INSERT OR REPLACE INTO ingestion_log VALUES (?,?,?,?,?,?,current_timestamp)",
        [str(uuid.uuid4()), "game_log_sync", "player_game_logs", count, "success", ""]
    )
    if close:
        conn.close()
    return count
