"""Backward-compatible re-export. Canonical location: backend/data_sources/"""
from backend.data_sources.nba.nba_ingestor import (
    ingest_teams, ingest_players, ingest_games, ingest_schedule, ingest_box_scores
)
from backend.data_sources.nba.game_log_sync import sync_game_logs
from backend.data_sources.sportsbooks.odds_ingestor import ingest_odds
from backend.data_sources.sportsbooks.props_ingestor import ingest_props
from backend.data_sources.injuries.injury_lineup_ingestor import ingest_injuries_and_lineups
