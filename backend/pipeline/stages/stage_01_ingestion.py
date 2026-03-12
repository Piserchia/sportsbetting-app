"""
Stage 01 — Data Ingestion
Fetches teams, players, games, schedule from NBA API.
Fetches odds and props from sportsbook APIs.
Fetches injuries and lineups.
"""

import os
import logging

from backend.database.connection import get_connection, init_schema
from backend.data_sources.nba.nba_ingestor import (
    ingest_teams, ingest_players, ingest_games, ingest_schedule, ingest_box_scores
)
from backend.data_sources.sportsbooks.odds_ingestor import ingest_odds
from backend.data_sources.sportsbooks.props_ingestor import ingest_props
from backend.data_sources.injuries.injury_lineup_ingestor import ingest_injuries_and_lineups

logger = logging.getLogger(__name__)


def run(conn, skip_box_scores: bool = False):
    """Run all ingestion steps."""
    logger.info("[Stage 1] Ingestion...")

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
