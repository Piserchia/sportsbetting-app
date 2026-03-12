"""Backward-compatible re-export. Canonical location: backend/data_sources/injuries/injury_lineup_ingestor.py"""
from backend.data_sources.injuries.injury_lineup_ingestor import *
from backend.data_sources.injuries.injury_lineup_ingestor import ingest_injuries_and_lineups
try:
    from backend.data_sources.injuries.injury_lineup_ingestor import get_teammate_injury_multipliers
except ImportError:
    pass
