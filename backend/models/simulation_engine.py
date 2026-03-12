"""Backward-compatible re-export. Canonical location: backend/pipeline/simulations/simulation_engine.py"""
from backend.pipeline.simulations.simulation_engine import *
from backend.pipeline.simulations.simulation_engine import simulate_player_props
try:
    from backend.pipeline.simulations.simulation_engine import probability_to_american_odds, american_odds_to_probability
except ImportError:
    pass
