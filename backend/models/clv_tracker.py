"""
models/clv_tracker.py
Closing Line Value (CLV) tracking and bet result evaluation.

Tracks bet outcomes and evaluates model performance against closing lines.

Metrics tracked:
    ROI, CLV, Brier score, log loss
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from backend.db.connection import get_connection, init_model_schema

logger = logging.getLogger(__name__)


def _init_bet_results_schema(conn):
    """Create bet_results table if not exists."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bet_results (
            bet_id              TEXT PRIMARY KEY,
            player_id           TEXT,
            game_id             TEXT,
            stat                TEXT,
            line                DOUBLE,
            direction           TEXT,        -- 'over' or 'under'
            model_probability   DOUBLE,
            book_odds           DOUBLE,
            closing_line        DOUBLE,
            actual_value        DOUBLE,
            result              TEXT,        -- 'win', 'loss', 'push'
            profit              DOUBLE,
            brier_score         DOUBLE,
            created_at          TIMESTAMP DEFAULT current_timestamp
        )
    """)


def record_bet_result(
    conn,
    player_id: str,
    game_id: str,
    stat: str,
    line: float,
    direction: str,
    model_probability: float,
    book_odds: float,
    actual_value: float,
    closing_line: float = None,
) -> str:
    """
    Record a single bet result.

    Returns the bet_id.
    """
    _init_bet_results_schema(conn)

    # Determine result
    if direction == "over":
        if actual_value > line:
            result = "win"
        elif actual_value == line:
            result = "push"
        else:
            result = "loss"
    else:  # under
        if actual_value < line:
            result = "win"
        elif actual_value == line:
            result = "push"
        else:
            result = "loss"

    # Calculate profit (assuming $100 bet at given odds)
    if result == "win":
        if book_odds > 0:
            profit = book_odds
        else:
            profit = (100.0 / abs(book_odds)) * 100
    elif result == "push":
        profit = 0.0
    else:
        profit = -100.0

    # Brier score: (forecast_probability - actual_outcome)^2
    actual_outcome = 1.0 if result == "win" else 0.0
    brier = (model_probability - actual_outcome) ** 2

    bet_id = str(uuid.uuid4())

    conn.execute("""
        INSERT INTO bet_results (
            bet_id, player_id, game_id, stat, line, direction,
            model_probability, book_odds, closing_line, actual_value,
            result, profit, brier_score, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,current_timestamp)
    """, [
        bet_id, player_id, game_id, stat, line, direction,
        model_probability, book_odds, closing_line, actual_value,
        result, profit, brier,
    ])

    return bet_id


def evaluate_completed_games(conn=None) -> int:
    """
    Evaluate all prop edges against actual results for completed games.
    Pulls from prop_edges + player_game_logs + prop_line_history.

    Returns number of bet results recorded.
    """
    close = conn is None
    conn = conn or get_connection()
    init_model_schema(conn)
    _init_bet_results_schema(conn)

    try:
        # Get prop edges that have corresponding actual results
        edges = conn.execute("""
            SELECT
                pe.game_id,
                pe.player_id,
                pe.stat,
                pe.line,
                pe.model_probability,
                pe.sportsbook_odds AS book_odds,
                pe.edge_percent,
                pe.book
            FROM prop_edges pe
            WHERE pe.edge_percent > 0
              AND pe.game_id NOT IN (SELECT DISTINCT game_id FROM bet_results)
        """).df()

        if edges.empty:
            logger.info("  No new edges to evaluate")
            return 0

        # Get actuals
        actuals = conn.execute("""
            SELECT
                player_id,
                game_id,
                points,
                rebounds,
                assists,
                steals,
                blocks
            FROM player_game_logs
        """).df()
        actuals["player_id"] = actuals["player_id"].astype(str)

        actual_lookup = {}
        for _, row in actuals.iterrows():
            key = (str(row["player_id"]), str(row["game_id"]))
            actual_lookup[key] = {
                "points": float(row["points"] or 0),
                "rebounds": float(row["rebounds"] or 0),
                "assists": float(row["assists"] or 0),
                "steals": float(row["steals"] or 0),
                "blocks": float(row["blocks"] or 0),
            }

        # Get closing lines from prop_line_history (last entry before game)
        closing_lines = {}
        try:
            closing = conn.execute("""
                SELECT
                    player_id,
                    game_id,
                    stat,
                    line,
                    book,
                    fetched_at
                FROM prop_line_history
                ORDER BY fetched_at DESC
            """).df()
            for _, row in closing.iterrows():
                key = (str(row["player_id"]), str(row["game_id"]), row["stat"], row["book"])
                if key not in closing_lines:
                    closing_lines[key] = float(row["line"])
        except Exception:
            pass

        count = 0
        for _, edge in edges.iterrows():
            pid = str(edge["player_id"])
            gid = str(edge["game_id"])
            stat = edge["stat"]
            actual = actual_lookup.get((pid, gid), {}).get(stat)

            if actual is None:
                continue

            # Determine direction from model probability
            # If model_probability > 0.5, we think over is likely
            direction = "over" if edge["model_probability"] > 0.5 else "under"

            closing_key = (pid, gid, stat, edge.get("book", ""))
            closing = closing_lines.get(closing_key)

            record_bet_result(
                conn,
                player_id=pid,
                game_id=gid,
                stat=stat,
                line=float(edge["line"]),
                direction=direction,
                model_probability=float(edge["model_probability"]),
                book_odds=float(edge["book_odds"]),
                actual_value=actual,
                closing_line=closing,
            )
            count += 1

        logger.info(f"  → {count} bet results recorded")
        return count

    finally:
        if close:
            conn.close()


def get_performance_summary(conn=None) -> dict:
    """
    Calculate overall model performance metrics from bet_results.

    Returns dict with: total_bets, wins, losses, roi, avg_clv, brier_score, log_loss
    """
    close = conn is None
    conn = conn or get_connection()
    _init_bet_results_schema(conn)

    try:
        df = conn.execute("SELECT * FROM bet_results").df()

        if df.empty:
            return {"total_bets": 0}

        total = len(df)
        wins = len(df[df["result"] == "win"])
        losses = len(df[df["result"] == "loss"])
        pushes = len(df[df["result"] == "push"])

        total_profit = float(df["profit"].sum())
        total_wagered = total * 100.0
        roi = (total_profit / total_wagered * 100) if total_wagered > 0 else 0.0

        avg_brier = float(df["brier_score"].mean())

        # Log loss
        eps = 1e-15
        actual = (df["result"] == "win").astype(float)
        prob = df["model_probability"].clip(eps, 1 - eps)
        log_loss_val = float(-np.mean(actual * np.log(prob) + (1 - actual) * np.log(1 - prob)))

        # CLV: compare model line to closing line
        clv_rows = df[df["closing_line"].notna()]
        avg_clv = 0.0
        if len(clv_rows) > 0:
            avg_clv = float((clv_rows["line"] - clv_rows["closing_line"]).mean())

        return {
            "total_bets": total,
            "wins": wins,
            "losses": losses,
            "pushes": pushes,
            "roi": round(roi, 2),
            "avg_clv": round(avg_clv, 2),
            "brier_score": round(avg_brier, 4),
            "log_loss": round(log_loss_val, 4),
        }

    finally:
        if close:
            conn.close()
