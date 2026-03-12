"""
db/connection.py
Manages the DuckDB connection and schema initialization.
"""

import os
import duckdb
import logging
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / "config" / ".env")

logger = logging.getLogger(__name__)

# Always resolve DB path relative to the project root (parent of backend/)
# This prevents ghost DBs being created when scripts are run from subdirectories
_PROJECT_ROOT = Path(__file__).parent.parent.parent
_DB_PATH_RAW  = os.getenv("DB_PATH", "data/sportsbetting.db")
DB_PATH       = str(_PROJECT_ROOT / _DB_PATH_RAW) if not os.path.isabs(_DB_PATH_RAW) else _DB_PATH_RAW


def get_connection(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Return a DuckDB connection, creating the data directory if needed."""
    db_path = Path(DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(db_path), read_only=read_only)
    return conn


def init_schema(conn: duckdb.DuckDBPyConnection):
    """Create all tables if they don't already exist."""
    logger.info("Initializing database schema...")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS teams (
            team_id         INTEGER PRIMARY KEY,
            full_name       VARCHAR,
            abbreviation    VARCHAR,
            nickname        VARCHAR,
            city            VARCHAR,
            state           VARCHAR,
            conference      VARCHAR,
            division        VARCHAR,
            updated_at      TIMESTAMP DEFAULT current_timestamp
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS players (
            player_id       INTEGER PRIMARY KEY,
            full_name       VARCHAR,
            first_name      VARCHAR,
            last_name       VARCHAR,
            is_active       BOOLEAN,
            updated_at      TIMESTAMP DEFAULT current_timestamp
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS games (
            game_id         VARCHAR PRIMARY KEY,
            season          VARCHAR,
            game_date       DATE,
            home_team_id    INTEGER,
            away_team_id    INTEGER,
            home_team_abbr  VARCHAR,
            away_team_abbr  VARCHAR,
            home_score      INTEGER,
            away_score      INTEGER,
            status          VARCHAR,   -- 'Final', 'Live', 'Upcoming'
            updated_at      TIMESTAMP DEFAULT current_timestamp
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS player_game_stats (
            stat_id         VARCHAR PRIMARY KEY,   -- game_id + player_id
            game_id         VARCHAR,
            player_id       INTEGER,
            team_id         INTEGER,
            season          VARCHAR,
            min             VARCHAR,
            pts             INTEGER,
            reb             INTEGER,
            ast             INTEGER,
            stl             INTEGER,
            blk             INTEGER,
            tov             INTEGER,
            fgm             INTEGER,
            fga             INTEGER,
            fg_pct          DOUBLE,
            fg3m            INTEGER,
            fg3a            INTEGER,
            fg3_pct         DOUBLE,
            ftm             INTEGER,
            fta             INTEGER,
            ft_pct          DOUBLE,
            plus_minus      INTEGER,
            updated_at      TIMESTAMP DEFAULT current_timestamp
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS team_game_stats (
            stat_id         VARCHAR PRIMARY KEY,   -- game_id + team_id
            game_id         VARCHAR,
            team_id         INTEGER,
            season          VARCHAR,
            is_home         BOOLEAN,
            min             VARCHAR,
            pts             INTEGER,
            reb             INTEGER,
            ast             INTEGER,
            stl             INTEGER,
            blk             INTEGER,
            tov             INTEGER,
            fgm             INTEGER,
            fga             INTEGER,
            fg_pct          DOUBLE,
            fg3m            INTEGER,
            fg3a            INTEGER,
            fg3_pct         DOUBLE,
            ftm             INTEGER,
            fta             INTEGER,
            ft_pct          DOUBLE,
            plus_minus      INTEGER,
            updated_at      TIMESTAMP DEFAULT current_timestamp
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS odds (
            odds_id         VARCHAR PRIMARY KEY,   -- game_id + bookmaker + market
            game_id         VARCHAR,
            bookmaker       VARCHAR,
            market          VARCHAR,   -- 'h2h', 'spreads', 'totals'
            home_price      DOUBLE,    -- moneyline or spread price
            away_price      DOUBLE,
            home_point      DOUBLE,    -- spread or total line
            away_point      DOUBLE,
            fetched_at      TIMESTAMP DEFAULT current_timestamp
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS ingestion_log (
            log_id          VARCHAR PRIMARY KEY,
            source          VARCHAR,   -- 'nba_api', 'odds_api'
            entity          VARCHAR,   -- 'games', 'players', etc.
            records_written INTEGER,
            status          VARCHAR,   -- 'success', 'error'
            message         VARCHAR,
            ran_at          TIMESTAMP DEFAULT current_timestamp
        )
    """)

    logger.info("Schema initialization complete.")


def init_model_schema(conn: duckdb.DuckDBPyConnection):
    """Create model pipeline tables if they don't already exist."""
    logger.info("Initializing model schema...")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS player_game_logs (
            game_id             TEXT,
            player_id           TEXT,
            game_date           DATE,
            team                TEXT,
            minutes             DOUBLE,
            points              DOUBLE,
            rebounds            DOUBLE,
            assists             DOUBLE,
            steals              DOUBLE,
            blocks              DOUBLE,
            turnovers           DOUBLE,
            fg_attempts         DOUBLE,
            three_attempts      DOUBLE,
            free_throw_attempts DOUBLE,
            PRIMARY KEY (game_id, player_id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS player_features (
            game_id                     TEXT,
            player_id                   TEXT,
            -- Rolling stat averages
            points_avg_last_5           DOUBLE,
            points_avg_last_10          DOUBLE,
            rebounds_avg_last_5         DOUBLE,
            rebounds_avg_last_10        DOUBLE,
            assists_avg_last_5          DOUBLE,
            assists_avg_last_10         DOUBLE,
            season_avg_points           DOUBLE,
            season_avg_rebounds         DOUBLE,
            season_avg_assists          DOUBLE,
            -- Improved minutes model
            minutes_avg_last_5          DOUBLE,
            minutes_avg_last_10         DOUBLE,
            minutes_trend               DOUBLE,
            games_started_last_5        INTEGER,
            minutes_projection          DOUBLE,
            blowout_risk                VARCHAR,
            blowout_adjustment_factor   DOUBLE,
            -- Pace context
            team_pace                   DOUBLE,
            opponent_pace               DOUBLE,
            expected_game_pace          DOUBLE,
            pace_adjustment_factor      DOUBLE,
            -- Opponent defense context
            opponent_points_allowed     DOUBLE,
            opponent_rebounds_allowed   DOUBLE,
            opponent_assists_allowed    DOUBLE,
            defense_adj_pts             DOUBLE,
            defense_adj_reb             DOUBLE,
            defense_adj_ast             DOUBLE,
            -- Usage
            usage_proxy                 DOUBLE,
            usage_trend_last_5          DOUBLE,
            PRIMARY KEY (game_id, player_id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS player_projections (
            game_id             TEXT,
            player_id           TEXT,
            points_mean         DOUBLE,
            rebounds_mean       DOUBLE,
            assists_mean        DOUBLE,
            minutes_projection  DOUBLE,
            PRIMARY KEY (game_id, player_id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS player_distributions (
            game_id     TEXT,
            player_id   TEXT,
            stat        TEXT,
            mean        DOUBLE,
            std_dev     DOUBLE,
            PRIMARY KEY (game_id, player_id, stat)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS player_simulations (
            game_id     TEXT,
            player_id   TEXT,
            stat        TEXT,
            line        DOUBLE,
            probability DOUBLE,
            PRIMARY KEY (game_id, player_id, stat, line)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS prop_edges (
            game_id             TEXT,
            player_id           TEXT,
            stat                TEXT,
            line                DOUBLE,
            sportsbook_odds     DOUBLE,
            model_probability   DOUBLE,
            fair_odds           DOUBLE,
            expected_value      DOUBLE,
            edge_percent        DOUBLE,
            book                TEXT,
            PRIMARY KEY (game_id, player_id, stat, line, book)
        )
    """)

    # ── Migrate existing player_features tables ────────────────────────────
    # Drop and recreate if the schema has changed (blowout_risk type fix)
    try:
        col_type = conn.execute(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'player_features' AND column_name = 'blowout_risk'"
        ).fetchone()
        if col_type and col_type[0].upper() not in ("VARCHAR", "TEXT"):
            conn.execute("DROP TABLE IF EXISTS player_features")
            logger.info("  Dropped player_features for schema migration (blowout_risk type fix).")
    except Exception:
        pass
    # Re-run CREATE TABLE after potential drop
    conn.execute("""
        CREATE TABLE IF NOT EXISTS player_features (
            game_id                     TEXT,
            player_id                   TEXT,
            points_avg_last_5           DOUBLE,
            points_avg_last_10          DOUBLE,
            rebounds_avg_last_5         DOUBLE,
            rebounds_avg_last_10        DOUBLE,
            assists_avg_last_5          DOUBLE,
            assists_avg_last_10         DOUBLE,
            season_avg_points           DOUBLE,
            season_avg_rebounds         DOUBLE,
            season_avg_assists          DOUBLE,
            minutes_avg_last_5          DOUBLE,
            minutes_avg_last_10         DOUBLE,
            minutes_trend               DOUBLE,
            games_started_last_5        INTEGER,
            minutes_projection          DOUBLE,
            blowout_risk                VARCHAR,
            blowout_adjustment_factor   DOUBLE,
            team_pace                   DOUBLE,
            opponent_pace               DOUBLE,
            expected_game_pace          DOUBLE,
            pace_adjustment_factor      DOUBLE,
            opponent_points_allowed     DOUBLE,
            opponent_rebounds_allowed   DOUBLE,
            opponent_assists_allowed    DOUBLE,
            defense_adj_pts             DOUBLE,
            defense_adj_reb             DOUBLE,
            defense_adj_ast             DOUBLE,
            usage_proxy                 DOUBLE,
            usage_trend_last_5          DOUBLE,
            PRIMARY KEY (game_id, player_id)
        )
    """)

    # Add new columns to existing tables without dropping them
    new_feature_cols = [
        ("rebounds_avg_last_5",         "DOUBLE",  "0.0"),
        ("assists_avg_last_5",           "DOUBLE",  "0.0"),
        ("season_avg_rebounds",          "DOUBLE",  "0.0"),
        ("season_avg_assists",           "DOUBLE",  "0.0"),
        ("minutes_avg_last_5",           "DOUBLE",  "0.0"),
        ("games_started_last_5",         "INTEGER", "0"),
        ("blowout_risk",                 "VARCHAR", "'NONE'"),
        ("blowout_adjustment_factor",    "DOUBLE",  "1.0"),
        ("team_pace",                    "DOUBLE",  "100.0"),
        ("opponent_pace",                "DOUBLE",  "100.0"),
        ("expected_game_pace",           "DOUBLE",  "100.0"),
        ("pace_adjustment_factor",       "DOUBLE",  "1.0"),
        ("opponent_points_allowed",      "DOUBLE",  "110.0"),
        ("opponent_rebounds_allowed",    "DOUBLE",  "44.0"),
        ("opponent_assists_allowed",     "DOUBLE",  "25.0"),
        ("defense_adj_pts",              "DOUBLE",  "1.0"),
        ("defense_adj_reb",              "DOUBLE",  "1.0"),
        ("defense_adj_ast",              "DOUBLE",  "1.0"),
        ("usage_proxy",                  "DOUBLE",  "0.2"),
        ("usage_trend_last_5",           "DOUBLE",  "0.0"),
        ("minutes_projection",           "DOUBLE",  "0.0"),
        ("pos_defense_adj_pts",          "DOUBLE",  "1.0"),
        ("pos_defense_adj_reb",          "DOUBLE",  "1.0"),
        ("pos_defense_adj_ast",          "DOUBLE",  "1.0"),
        ("position_group",               "VARCHAR", "'FORWARD'"),
    ]
    existing_cols = {
        row[0]: row[1] for row in conn.execute(
            "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'player_features'"
        ).fetchall()
    }
    for col_name, col_type, col_default in new_feature_cols:
        if col_name not in existing_cols:
            try:
                conn.execute(f"ALTER TABLE player_features ADD COLUMN {col_name} {col_type} DEFAULT {col_default}")
            except Exception:
                pass  # column may already exist in some form

    # Fix blowout_risk if it was created as DOUBLE instead of VARCHAR
    if existing_cols.get("blowout_risk", "").upper() in ("DOUBLE", "FLOAT", "REAL"):
        try:
            conn.execute("ALTER TABLE player_features DROP COLUMN blowout_risk")
            conn.execute("ALTER TABLE player_features ADD COLUMN blowout_risk VARCHAR DEFAULT 'NONE'")
        except Exception:
            pass

    conn.execute("""
        CREATE TABLE IF NOT EXISTS player_injuries (
            injury_id       TEXT PRIMARY KEY,
            player_id       TEXT,
            player_name     TEXT,
            team_abbr       TEXT,
            status          TEXT,   -- 'Out', 'Doubtful', 'Questionable', 'Probable'
            injury_type     TEXT,
            report_date     DATE,
            game_id         TEXT,
            source          TEXT,
            fetched_at      TIMESTAMP DEFAULT current_timestamp
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS starting_lineups (
            lineup_id       TEXT PRIMARY KEY,
            game_id         TEXT,
            team_id         INTEGER,
            player_id       TEXT,
            is_starter      BOOLEAN,
            position        TEXT,
            report_date     DATE,
            source          TEXT,
            fetched_at      TIMESTAMP DEFAULT current_timestamp
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS model_backtests (
            season          TEXT,
            stat            TEXT,
            line            DOUBLE,
            n_samples       INTEGER,
            hit_rate        DOUBLE,
            avg_model_prob  DOUBLE,
            brier_score     DOUBLE,
            log_loss        DOUBLE,
            simulated_bets  INTEGER,
            simulated_roi   DOUBLE,
            simulated_profit DOUBLE,
            PRIMARY KEY (season, stat, line)
        )
    """)

    logger.info("Model schema initialization complete.")
