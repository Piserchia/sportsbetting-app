"""
Stage 04 — Projections
Generates stat projections using LightGBM + heuristic fallback.
Populates player_projections and player_distributions.
"""

import logging
from backend.models.stat_models.projection_model import generate_projections

logger = logging.getLogger(__name__)


def run(conn):
    """Generate player projections."""
    logger.info("[Stage 4] Projections...")
    generate_projections(conn=conn)
