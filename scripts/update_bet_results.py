#!/usr/bin/env python3
"""
scripts/update_bet_results.py
Resolves pending model_recommendations by checking actual game results.

For each unresolved bet:
  1. Joins with player_game_logs to get actual stat value
  2. Only processes games where status = 'Final'
  3. Computes win/loss/push
  4. Optionally updates closing line from prop_line_history

Usage:
    python scripts/update_bet_results.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
from config.logging_config import setup_logging
from backend.database.connection import get_connection, init_model_schema

setup_logging()
logger = logging.getLogger(__name__)

STAT_COL = {
    "points": "points",
    "rebounds": "rebounds",
    "assists": "assists",
    "steals": "steals",
    "blocks": "blocks",
}


def update_bet_results(conn=None) -> int:
    """Resolve pending bets against actual game results."""
    close = conn is None
    conn = conn or get_connection()
    init_model_schema(conn)

    # Find unresolved bets for finished games
    pending = conn.execute("""
        SELECT mr.bet_id, mr.game_id, mr.player_id, mr.stat, mr.line,
               mr.sportsbook
        FROM model_recommendations mr
        JOIN games g ON mr.game_id = g.game_id
        WHERE mr.result IS NULL
          AND g.status = 'Final'
    """).fetchall()

    if not pending:
        logger.info("No pending bets to resolve.")
        if close:
            conn.close()
        return 0

    logger.info(f"Resolving {len(pending)} pending bets...")

    # Load game logs for lookup
    game_logs = conn.execute("""
        SELECT game_id, player_id, points, rebounds, assists, steals, blocks
        FROM player_game_logs
    """).df()

    log_lookup = {}
    for _, row in game_logs.iterrows():
        key = (str(row["game_id"]), str(row["player_id"]))
        log_lookup[key] = row

    resolved = 0
    for bet_id, game_id, player_id, stat, line, sportsbook in pending:
        key = (str(game_id), str(player_id))
        log_row = log_lookup.get(key)

        if log_row is None:
            continue

        stat_col = STAT_COL.get(stat)
        if stat_col is None:
            continue

        actual = float(log_row[stat_col])

        if actual > line:
            result = "win"
        elif actual < line:
            result = "loss"
        else:
            result = "push"

        conn.execute("""
            UPDATE model_recommendations
            SET actual_stat = ?, result = ?
            WHERE bet_id = ?
        """, [actual, result, bet_id])
        resolved += 1

    # Update closing lines from prop_line_history (latest snapshot before game)
    try:
        conn.execute("""
            UPDATE model_recommendations mr
            SET closing_line = cl.line,
                closing_odds = CAST(cl.over_odds AS INTEGER)
            FROM (
                SELECT plh.game_id, plh.player_id, plh.stat, plh.book,
                       plh.line, plh.over_odds,
                       ROW_NUMBER() OVER (
                           PARTITION BY plh.game_id, plh.player_id, plh.stat, plh.book
                           ORDER BY plh.fetched_at DESC
                       ) AS rn
                FROM prop_line_history plh
            ) cl
            WHERE cl.rn = 1
              AND mr.game_id = cl.game_id
              AND CAST(mr.player_id AS TEXT) = cl.player_id
              AND mr.stat = cl.stat
              AND mr.sportsbook = cl.book
              AND mr.closing_line IS NULL
        """)
    except Exception as e:
        logger.debug(f"  Closing line update error: {e}")

    logger.info(f"  → {resolved} bets resolved.")

    if close:
        conn.close()
    return resolved


if __name__ == "__main__":
    count = update_bet_results()
    print(f"Resolved {count} bet results.")
