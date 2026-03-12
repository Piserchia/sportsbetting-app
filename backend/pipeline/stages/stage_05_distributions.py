"""
Stage 05 — Distributions
Distribution fitting is handled as part of the projection stage
(player_distributions table is populated by generate_projections).

This stage is a no-op placeholder for explicit pipeline ordering.
Future: could extract distribution fitting from projection_model.
"""

import logging

logger = logging.getLogger(__name__)


def run(conn):
    """Distribution fitting (currently handled in stage 04)."""
    logger.info("[Stage 5] Distributions — handled in projection stage.")
