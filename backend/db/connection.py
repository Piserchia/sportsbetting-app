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

DB_PATH = os.getenv("DB_PATH", "data/sportsbetting.db")


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
            game_id             TEXT,
            player_id           TEXT,
            points_avg_last_5   DOUBLE,
            points_avg_last_10  DOUBLE,
            rebounds_avg_last_10 DOUBLE,
            assists_avg_last_10 DOUBLE,
            minutes_avg_last_10 DOUBLE,
            minutes_trend       DOUBLE,
            season_avg_points   DOUBLE,
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

    logger.info("Model schema initialization complete.")
