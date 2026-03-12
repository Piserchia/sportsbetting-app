"""
Stage 02 — Game Log Sync
Normalizes raw box score data into player_game_logs.
"""

import logging
from backend.data_sources.nba.game_log_sync import sync_game_logs

logger = logging.getLogger(__name__)


def run(conn):
    """Sync game logs from player_game_stats → player_game_logs."""
    logger.info("[Stage 2] Game log sync...")
    sync_game_logs(conn=conn)
