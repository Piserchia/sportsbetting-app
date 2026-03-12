"""
Stage 03 — Feature Engineering
Builds all player features from game logs → player_features.
"""

import logging
from backend.models.feature_builder import build_player_features

logger = logging.getLogger(__name__)


def run(conn, incremental: bool = True):
    """Build player features (incremental or full rebuild)."""
    logger.info("[Stage 3] Feature engineering...")
    build_player_features(conn=conn, incremental=incremental)
