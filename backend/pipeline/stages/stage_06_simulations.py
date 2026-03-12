"""
Stage 06 — Monte Carlo Simulations
Runs 10k MC samples per player/stat → player_simulations.
"""

import logging
from backend.pipeline.simulations.simulation_engine import simulate_player_props

logger = logging.getLogger(__name__)


def run(conn):
    """Run Monte Carlo simulations."""
    logger.info("[Stage 6] Simulations...")
    simulate_player_props(conn=conn)
