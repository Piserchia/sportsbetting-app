"""
features/
Modular feature engineering modules for the player projection pipeline.

Each module computes a set of features independently and writes columns
to the player_features table via the feature_builder orchestrator.

Modules:
    rolling_stats    — L5, L10, season averages for pts/reb/ast/stl/blk
    minutes_features — Minutes projection via LightGBM
    pace_features    — Team pace context
    defense_features — Opponent defensive strength
    usage_features   — Usage rate proxy
    lineup_features  — On/off splits for injury impact
"""

from backend.models.pace_features import build_pace_features
from backend.models.defense_features import build_defense_features
from backend.models.minutes_model import build_minutes_features
from backend.models.usage_features import build_usage_features
from backend.models.positional_defense_features import build_positional_defense_features
from backend.models.advanced_defense_features import build_advanced_defense_features
from backend.models.lineup_features import build_lineup_features

__all__ = [
    "build_pace_features",
    "build_defense_features",
    "build_minutes_features",
    "build_usage_features",
    "build_positional_defense_features",
    "build_advanced_defense_features",
    "build_lineup_features",
]
