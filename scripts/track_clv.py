#!/usr/bin/env python3
"""
scripts/track_clv.py
Evaluate completed games and track CLV/bet performance.

Usage:
    python scripts/track_clv.py           # evaluate + show summary
    python scripts/track_clv.py --summary # show summary only
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.logging_config import setup_logging
from backend.database.connection import get_connection
from backend.models.clv_tracker import evaluate_completed_games, get_performance_summary

setup_logging()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true", help="Show summary only (no evaluation)")
    args = parser.parse_args()

    conn = get_connection()

    if not args.summary:
        count = evaluate_completed_games(conn)
        print(f"Evaluated {count} new bet results.")

    summary = get_performance_summary(conn)
    conn.close()

    if summary["total_bets"] == 0:
        print("No bet results recorded yet.")
    else:
        print(f"\nModel Performance Summary:")
        print(f"  Total bets:   {summary['total_bets']}")
        print(f"  Wins:         {summary['wins']}")
        print(f"  Losses:       {summary['losses']}")
        print(f"  Pushes:       {summary.get('pushes', 0)}")
        print(f"  ROI:          {summary['roi']}%")
        print(f"  Avg CLV:      {summary['avg_clv']}")
        print(f"  Brier Score:  {summary['brier_score']}")
        print(f"  Log Loss:     {summary['log_loss']}")
