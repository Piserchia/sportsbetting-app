#!/usr/bin/env python3
"""
scripts/simulate_props.py
Step 4 of the modeling pipeline.
Runs Monte Carlo simulations and generates probability ladders for all players.

Usage:
    python scripts/simulate_props.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.logging_config import setup_logging
from backend.db.connection import get_connection
from backend.models.simulation_engine import simulate_player_props

setup_logging()

if __name__ == "__main__":
    conn = get_connection()
    count = simulate_player_props(conn=conn)
    conn.close()
    print(f"✅ Simulations complete — {count:,} probability rows written to player_simulations.")
