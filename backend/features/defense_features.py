"""features/defense_features.py — Re-export from backend.models.defense_features."""
from backend.models.defense_features import build_defense_features
from backend.models.advanced_defense_features import build_advanced_defense_features

__all__ = ["build_defense_features", "build_advanced_defense_features"]
