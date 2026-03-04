#!/usr/bin/env python3
"""
scripts/run_projections.py
Step 3 of the modeling pipeline.
Generates stat projections and distributions for all players.

Usage:
    python scripts/run_projections.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.logging_config import setup_logging
from backend.db.connection import get_connection
from backend.models.projection_model import generate_projections

setup_logging()

if __name__ == "__main__":
    conn = get_connection()
    count = generate_projections(conn=conn)
    conn.close()
    print(f"✅ Projections complete — {count:,} rows written to player_projections.")
