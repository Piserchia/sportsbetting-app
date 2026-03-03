#!/usr/bin/env python3
"""
scripts/ingest_odds.py
Pull current NBA odds from The Odds API into DuckDB.
Requires ODDS_API_KEY in config/.env

Usage:
    python scripts/ingest_odds.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.logging_config import setup_logging
from backend.db.connection import get_connection, init_schema
from backend.ingestion.odds_ingestor import ingest_odds

setup_logging()

if __name__ == "__main__":
    conn = get_connection()
    init_schema(conn)
    ingest_odds(conn=conn)
    conn.close()
    print("✅ Odds ingestion complete.")
