"""Backward-compatible re-export. Canonical location: backend/data_sources/sportsbooks/props_ingestor.py"""
from backend.data_sources.sportsbooks.props_ingestor import *
from backend.data_sources.sportsbooks.props_ingestor import ingest_props
try:
    from backend.data_sources.sportsbooks.props_ingestor import get_available_markets
except ImportError:
    pass
