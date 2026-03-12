#!/usr/bin/env python3
"""
scripts/ingest_props.py
Fetch NBA player prop lines from SportsGameOdds and write to sportsbook_props.

Requires SPORTSGAMEODDS_API_KEY in config/.env
Sign up at https://sportsgameodds.com

Usage:
    python scripts/ingest_props.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.logging_config import setup_logging
from backend.db.connection import get_connection
from backend.ingestion.props_ingestor import ingest_props, get_available_markets

setup_logging()

if __name__ == "__main__":
    conn  = get_connection()
    count = ingest_props(conn=conn)

    if count > 0:
        print(f"\n✅ Props ingestion complete — {count:,} rows written to sportsbook_props.")
        print("\nMarkets in DB:")
        print(get_available_markets(conn=conn).to_string(index=False))
    else:
        print("⚠️  No props written. Check SPORTSGAMEODDS_API_KEY in config/.env")
