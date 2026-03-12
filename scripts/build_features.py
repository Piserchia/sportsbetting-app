#!/usr/bin/env python3
"""
scripts/build_features.py
Step 2 of the modeling pipeline.
Syncs raw game logs and computes rolling player features.

Usage:
    python scripts/build_features.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.logging_config import setup_logging
from backend.database.connection import get_connection, init_model_schema
from backend.data_sources.nba.game_log_sync import sync_game_logs
from backend.models.feature_builder import build_player_features

setup_logging()

if __name__ == "__main__":
    conn = get_connection()
    init_model_schema(conn)
    sync_game_logs(conn=conn)
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true",
                        help="Full rebuild (default: incremental)")
    args, _ = parser.parse_known_args()
    count = build_player_features(conn=conn, incremental=not args.full)
    conn.close()
    print(f"✅ Features built — {count:,} rows written to player_features.")
