#!/usr/bin/env python3
"""
scripts/ingest_nba.py
Pull NBA teams, players, games, and box scores into DuckDB.

Usage:
    python scripts/ingest_nba.py                    # Full ingest
    python scripts/ingest_nba.py --box-scores-limit 10  # Limit box score fetches (for testing)
    python scripts/ingest_nba.py --season 2024-25   # Specific season only
"""

import sys
import os
import argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.logging_config import setup_logging
from backend.db.connection import get_connection, init_schema
from backend.ingestion.nba_ingestor import (
    ingest_teams, ingest_players, ingest_games, ingest_box_scores
)

setup_logging()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=str, help="Specific season (e.g. 2024-25)")
    parser.add_argument("--box-scores-limit", type=int, default=None,
                        help="Max box scores to fetch per season (for testing)")
    parser.add_argument("--skip-box-scores", action="store_true",
                        help="Skip box score ingestion (faster)")
    parser.add_argument("--force", action="store_true",
                        help="Re-fetch ALL box scores for the season, ignoring already-ingested games")
    args = parser.parse_args()

    conn = get_connection()
    init_schema(conn)

    ingest_teams(conn=conn)
    ingest_players(conn=conn)

    seasons = [args.season] if args.season else None
    ingest_games(seasons=seasons, conn=conn)

    if not args.skip_box_scores:
        target_seasons = [args.season] if args.season else os.getenv("NBA_SEASONS", "2025-26").split(",")
        for season in target_seasons:
            ingest_box_scores(season.strip(), limit=args.box_scores_limit, conn=conn, force=args.force)

    conn.close()
    print("✅ NBA ingestion complete.")
