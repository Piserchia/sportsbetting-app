"""
Stage 03 — Feature Engineering
Computes Bayesian shrinkage posteriors, then builds all player features
from game logs → player_features.
"""

import logging
from backend.database.connection import init_model_schema
from backend.models.feature_builder import build_player_features

logger = logging.getLogger(__name__)


def run(conn, incremental: bool = True):
    """Compute Bayesian posteriors then build player features."""
    logger.info("[Stage 3] Feature engineering...")
    init_model_schema(conn)  # ensure player_stat_posteriors table exists
    build_player_features(conn=conn, incremental=incremental)
