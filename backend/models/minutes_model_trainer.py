"""Backward-compatible re-export. Canonical location: backend/models/minutes_model/minutes_model_trainer.py"""
from backend.models.minutes_model.minutes_model_trainer import *
try:
    from backend.models.minutes_model.minutes_model_trainer import train, MODEL_PATH
except ImportError:
    pass
