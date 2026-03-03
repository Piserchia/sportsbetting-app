#!/usr/bin/env python3
"""
scripts/init_db.py
Initialize the DuckDB database and create all tables.
Run this once before any ingestion.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.logging_config import setup_logging
from backend.db.connection import get_connection, init_schema

setup_logging()

if __name__ == "__main__":
    conn = get_connection()
    init_schema(conn)
    conn.close()
    print("✅ Database initialized successfully.")
