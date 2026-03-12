#!/usr/bin/env python3
"""
scripts/run_pipeline.py
Run the full ingestion pipeline (NBA + Odds).
Optionally schedule it to run on a recurring basis.

Usage:
    python scripts/run_pipeline.py                  # Run once
    python scripts/run_pipeline.py --schedule       # Run daily at 6am + every 2hrs during day
    python scripts/run_pipeline.py --skip-box-scores  # Fast run (no box scores)
"""

import sys
import os
import argparse
import logging
import schedule
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.logging_config import setup_logging
from backend.db.connection import get_connection, init_schema
from backend.ingestion.nba_ingestor import (
    ingest_teams, ingest_players, ingest_games, ingest_schedule, ingest_box_scores
)
from backend.ingestion.odds_ingestor import ingest_odds
from backend.ingestion.props_ingestor import ingest_props
from backend.ingestion.game_log_sync import sync_game_logs
from backend.ingestion.injury_lineup_ingestor import ingest_injuries_and_lineups
from backend.models.feature_builder import build_player_features
from backend.models.projection_model import generate_projections
from backend.models.simulation_engine import simulate_player_props

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from calculate_edges import calculate_edges

setup_logging()
logger = logging.getLogger(__name__)


def run_pipeline(skip_box_scores: bool = False, full_rebuild: bool = False):
    logger.info("=" * 60)
    logger.info("Starting full ingestion pipeline...")
    logger.info("=" * 60)

    conn = get_connection()
    init_schema(conn)

    try:
        ingest_teams(conn=conn)
        ingest_players(conn=conn)
        ingest_games(conn=conn)
        ingest_schedule(conn=conn)

        if not skip_box_scores:
            seasons = os.getenv("NBA_SEASONS", "2024-25").split(",")
            for season in seasons:
                ingest_box_scores(season.strip(), conn=conn)

        ingest_odds(conn=conn)
        ingest_props(conn=conn)
        ingest_injuries_and_lineups(conn=conn)

        # Model pipeline
        logger.info("Running model pipeline...")
        sync_game_logs(conn=conn)
        build_player_features(conn=conn, incremental=not full_rebuild)
        generate_projections(conn=conn)
        simulate_player_props(conn=conn)
        calculate_edges(conn=conn)

    except Exception as e:
        logger.error(f"Pipeline error: {e}")
    finally:
        conn.close()

    logger.info("Pipeline complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--schedule", action="store_true",
                        help="Run on a schedule (daily 6am + odds every 2hrs)")
    parser.add_argument("--skip-box-scores", action="store_true")
    parser.add_argument("--full-rebuild", action="store_true",
                        help="Clear and rebuild player_features from scratch")
    args = parser.parse_args()

    skip    = args.skip_box_scores
    rebuild = args.full_rebuild

    if args.schedule:
        logger.info("Running in scheduled mode...")

        # Full pipeline daily at 6am
        schedule.every().day.at("06:00").do(run_pipeline, skip_box_scores=False, full_rebuild=False)

        # Odds-only refresh every 2 hours during game windows
        def odds_only():
            conn = get_connection()
            init_schema(conn)
            ingest_odds(conn=conn)
            conn.close()

        schedule.every(2).hours.do(odds_only)

        # Props fetch at fixed daily times (free-tier optimized)
        def props_only():
            from backend.db.connection import init_model_schema
            conn = get_connection()
            init_schema(conn)
            init_model_schema(conn)
            ingest_props(conn=conn)
            conn.close()

        for t in ["06:00", "12:00", "16:00", "19:00"]:
            schedule.every().day.at(t).do(props_only)
        logger.info("Props schedule: 6am, 12pm, 4pm, 7pm")

        # Run once immediately on start
        run_pipeline(skip_box_scores=skip, full_rebuild=rebuild)

        while True:
            schedule.run_pending()
            time.sleep(60)
    else:
        run_pipeline(skip_box_scores=skip, full_rebuild=rebuild)
