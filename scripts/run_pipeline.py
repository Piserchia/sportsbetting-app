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
from backend.database.connection import get_connection, init_schema, init_model_schema
from backend.data_sources.sportsbooks.odds_ingestor import ingest_odds
from backend.data_sources.sportsbooks.props_ingestor import ingest_props

from backend.pipeline.stages import (
    stage_01_ingestion,
    stage_02_game_logs,
    stage_03_features,
    stage_04_projections,
    stage_05_distributions,
    stage_06_simulations,
    stage_07_edges,
)

PIPELINE = [
    stage_01_ingestion,
    stage_02_game_logs,
    stage_03_features,
    stage_04_projections,
    stage_05_distributions,
    stage_06_simulations,
    stage_07_edges,
]

setup_logging()
logger = logging.getLogger(__name__)


def run_pipeline(skip_box_scores: bool = False, full_rebuild: bool = False):
    logger.info("=" * 60)
    logger.info("Starting full ingestion pipeline...")
    logger.info("=" * 60)

    conn = get_connection()
    init_schema(conn)

    try:
        # Stage 1: Ingestion
        stage_01_ingestion.run(conn, skip_box_scores=skip_box_scores)

        # Stage 2: Game log sync
        stage_02_game_logs.run(conn)

        # Stage 3: Feature engineering
        stage_03_features.run(conn, incremental=not full_rebuild)

        # Stage 4: Projections
        stage_04_projections.run(conn)

        # Stage 5: Distributions
        stage_05_distributions.run(conn)

        # Stage 6: Simulations
        stage_06_simulations.run(conn)

        # Stage 7: Edge detection
        stage_07_edges.run(conn)

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
