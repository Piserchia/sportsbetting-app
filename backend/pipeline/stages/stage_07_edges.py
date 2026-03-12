"""
Stage 07 — Edge Detection
Compares model probabilities against sportsbook odds → prop_edges.
"""

import logging
import sys
import os

# calculate_edges lives in scripts/ — import it
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'scripts'))
from calculate_edges import calculate_edges

logger = logging.getLogger(__name__)


def run(conn):
    """Calculate edges against sportsbook props."""
    logger.info("[Stage 7] Edge detection...")
    calculate_edges(conn=conn)
