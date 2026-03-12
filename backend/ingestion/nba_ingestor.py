"""Backward-compatible re-export. Canonical location: backend/data_sources/nba/nba_ingestor.py"""
from backend.data_sources.nba.nba_ingestor import *
from backend.data_sources.nba.nba_ingestor import (
    ingest_teams, ingest_players, ingest_games, ingest_schedule, ingest_box_scores
)
