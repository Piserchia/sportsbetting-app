#!/usr/bin/env python3
"""
scripts/train_minutes_model.py
Train a LightGBM model to predict player minutes played.

Delegates to backend.models.minutes_model_trainer for the enhanced v2 trainer
with expanded features and tuned hyperparameters.

Usage:
    python scripts/train_minutes_model.py
    python scripts/train_minutes_model.py --force   # retrain even if model exists
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.logging_config import setup_logging
from backend.database.connection import get_connection
from backend.models.minutes_model.minutes_model_trainer import train, MODEL_PATH

setup_logging()
logger = logging.getLogger(__name__)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Retrain even if model exists")
    args = parser.parse_args()

    conn = get_connection()
    success = train(conn=conn, force=args.force)
    conn.close()
    if success:
        print(f"Minutes model trained and saved to {MODEL_PATH}")
    else:
        print("Model not trained — check logs for details.")
