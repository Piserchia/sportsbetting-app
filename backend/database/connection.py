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
    if not read_only:
        _run_migrations(conn)
    return conn


def _run_migrations(conn: duckdb.DuckDBPyConnection):
    """Lightweight migrations for schema additions."""
    try:
        conn.execute("ALTER TABLE games ADD COLUMN game_time_et VARCHAR")
    except Exception:
        pass

    # Migrate player_features: replace *_avg_last_5 with *_recent_adj
    try:
        cols = [r[0] for r in conn.execute("SELECT column_name FROM information_schema.columns WHERE table_name='player_features'").fetchall()]
        if "points_avg_last_5" in cols:
            logger.info("Migrating player_features: dropping *_avg_last_5, adding *_recent_adj...")
            conn.execute("DROP TABLE IF EXISTS player_features")
    except Exception:
        pass


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
            game_time_et    VARCHAR,   -- e.g. '7:30 PM ET'
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
            -- Rolling stat averages (EWMA + regression-to-mean adjusted)
            points_recent_adj           DOUBLE,
            points_avg_last_10          DOUBLE,
            rebounds_recent_adj         DOUBLE,
            rebounds_avg_last_10        DOUBLE,
            assists_recent_adj          DOUBLE,
            assists_avg_last_10         DOUBLE,
            season_avg_points           DOUBLE,
            season_avg_rebounds         DOUBLE,
            season_avg_assists          DOUBLE,
            -- Steals / Blocks (EWMA + regression-to-mean adjusted)
            steals_recent_adj           DOUBLE,
            steals_avg_last_10          DOUBLE,
            blocks_recent_adj           DOUBLE,
            blocks_avg_last_10          DOUBLE,
            season_avg_steals           DOUBLE,
            season_avg_blocks           DOUBLE,
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
            -- Steals / Blocks defensive context
            opponent_steals_allowed     DOUBLE,
            opponent_blocks_allowed     DOUBLE,
            defense_adj_stl             DOUBLE,
            defense_adj_blk             DOUBLE,
            -- Usage
            usage_proxy                 DOUBLE,
            usage_trend_last_5          DOUBLE,
            -- Bayesian shrinkage posteriors
            points_posterior            DOUBLE,
            rebounds_posterior           DOUBLE,
            assists_posterior            DOUBLE,
            steals_posterior             DOUBLE,
            blocks_posterior             DOUBLE,
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
            steals_mean         DOUBLE,
            blocks_mean         DOUBLE,
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
            points_recent_adj           DOUBLE,
            points_avg_last_10          DOUBLE,
            rebounds_recent_adj         DOUBLE,
            rebounds_avg_last_10        DOUBLE,
            assists_recent_adj          DOUBLE,
            assists_avg_last_10         DOUBLE,
            season_avg_points           DOUBLE,
            season_avg_rebounds         DOUBLE,
            season_avg_assists          DOUBLE,
            steals_recent_adj           DOUBLE,
            steals_avg_last_10          DOUBLE,
            blocks_recent_adj           DOUBLE,
            blocks_avg_last_10          DOUBLE,
            season_avg_steals           DOUBLE,
            season_avg_blocks           DOUBLE,
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
            opponent_steals_allowed     DOUBLE,
            opponent_blocks_allowed     DOUBLE,
            defense_adj_stl             DOUBLE,
            defense_adj_blk             DOUBLE,
            usage_proxy                 DOUBLE,
            usage_trend_last_5          DOUBLE,
            points_posterior            DOUBLE,
            rebounds_posterior           DOUBLE,
            assists_posterior            DOUBLE,
            steals_posterior             DOUBLE,
            blocks_posterior             DOUBLE,
            PRIMARY KEY (game_id, player_id)
        )
    """)

    # Add new columns to existing tables without dropping them
    new_feature_cols = [
        ("rebounds_recent_adj",         "DOUBLE",  "0.0"),
        ("assists_recent_adj",           "DOUBLE",  "0.0"),
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
        ("positional_defense_adj_pts",    "DOUBLE",  "1.0"),
        ("positional_defense_adj_reb",    "DOUBLE",  "1.0"),
        ("positional_defense_adj_ast",    "DOUBLE",  "1.0"),
        ("defense_vs_pg",                 "DOUBLE",  "8.0"),
        ("defense_vs_sg",                 "DOUBLE",  "8.0"),
        ("defense_vs_sf",                 "DOUBLE",  "8.0"),
        ("defense_vs_pf",                 "DOUBLE",  "8.0"),
        ("defense_vs_c",                  "DOUBLE",  "8.0"),
        ("player_position",               "VARCHAR", "'SF'"),
        ("steals_avg_last_5",             "DOUBLE",  "0.0"),
        ("steals_avg_last_10",            "DOUBLE",  "0.0"),
        ("blocks_avg_last_5",             "DOUBLE",  "0.0"),
        ("blocks_avg_last_10",            "DOUBLE",  "0.0"),
        ("season_avg_steals",             "DOUBLE",  "0.0"),
        ("season_avg_blocks",             "DOUBLE",  "0.0"),
        ("opponent_steals_allowed",       "DOUBLE",  "8.0"),
        ("opponent_blocks_allowed",       "DOUBLE",  "5.0"),
        ("defense_adj_stl",               "DOUBLE",  "1.0"),
        ("defense_adj_blk",               "DOUBLE",  "1.0"),
        ("team_off_rating",               "DOUBLE",  "110.0"),
        ("opponent_def_rating",           "DOUBLE",  "110.0"),
        ("rating_matchup_factor",         "DOUBLE",  "1.0"),
        ("usage_delta_teammate_out",      "DOUBLE",  "0.0"),
        ("assist_delta_teammate_out",     "DOUBLE",  "0.0"),
        ("rebound_delta_teammate_out",    "DOUBLE",  "0.0"),
        ("points_posterior",              "DOUBLE",  "0.0"),
        ("rebounds_posterior",            "DOUBLE",  "0.0"),
        ("assists_posterior",             "DOUBLE",  "0.0"),
        ("steals_posterior",              "DOUBLE",  "0.0"),
        ("blocks_posterior",              "DOUBLE",  "0.0"),
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

    # Add steals_mean / blocks_mean to player_projections if missing
    try:
        proj_cols = {
            row[0] for row in conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'player_projections'"
            ).fetchall()
        }
        for col_name in ["steals_mean", "blocks_mean"]:
            if col_name not in proj_cols:
                conn.execute(f"ALTER TABLE player_projections ADD COLUMN {col_name} DOUBLE DEFAULT 0.0")
    except Exception:
        pass

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
            backtest_id     TEXT PRIMARY KEY,
            run_date        TEXT,
            model_version   TEXT,
            stat            TEXT,
            line            DOUBLE,
            n_predictions   INTEGER,
            hit_rate        DOUBLE,
            brier_score     DOUBLE,
            log_loss        DOUBLE,
            roi             DOUBLE,
            avg_edge        DOUBLE,
            created_at      TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS prop_line_history (
            history_id      TEXT PRIMARY KEY,
            fetched_at      TIMESTAMP,
            book            TEXT,
            player_id       TEXT,
            player_name     TEXT,
            game_id         TEXT,
            stat            TEXT,
            line            DOUBLE,
            over_odds       DOUBLE,
            under_odds      DOUBLE
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS team_advanced_stats (
            game_id         TEXT,
            team_id         INTEGER,
            off_rating      DOUBLE,
            def_rating      DOUBLE,
            pace            DOUBLE,
            possessions     DOUBLE,
            PRIMARY KEY (game_id, team_id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS projection_explanations (
            game_id         TEXT,
            player_id       INTEGER,
            stat            TEXT,
            feature         TEXT,
            contribution    DOUBLE
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS model_feature_importance (
            stat            TEXT,
            position_group  TEXT,
            feature         TEXT,
            importance      DOUBLE,
            model_version   TEXT,
            created_at      TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (stat, position_group, feature)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS player_stat_posteriors (
            player_id       TEXT,
            stat            TEXT,
            posterior_mean  DOUBLE,
            player_mean     DOUBLE,
            prior_mean      DOUBLE,
            n_games         INTEGER,
            position_group  TEXT,
            created_at      TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (player_id, stat)
        )
    """)

    # Add generated_at to player_projections if missing
    try:
        conn.execute("ALTER TABLE player_projections ADD COLUMN generated_at TIMESTAMP")
    except Exception:
        pass

    conn.execute("""
        CREATE TABLE IF NOT EXISTS model_versions (
            version         TEXT PRIMARY KEY,
            created_at      TIMESTAMP DEFAULT current_timestamp,
            git_commit      TEXT,
            training_games  INTEGER,
            notes           TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS model_recommendations (
            bet_id                  TEXT PRIMARY KEY,
            timestamp_generated     TIMESTAMP,
            model_version           TEXT,
            game_id                 TEXT,
            player_id               INTEGER,
            player_name             TEXT,
            team                    TEXT,
            stat                    TEXT,
            line                    DOUBLE,
            sportsbook              TEXT,
            odds                    INTEGER,
            model_probability       DOUBLE,
            edge_percent            DOUBLE,
            confidence_score        DOUBLE,
            closing_line            DOUBLE,
            closing_odds            INTEGER,
            actual_stat             DOUBLE,
            result                  TEXT
        )
    """)
    # Add new columns if missing
    try:
        mr_cols = {
            row[0] for row in conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'model_recommendations'"
            ).fetchall()
        }
        for col_name, col_type in [("player_position", "TEXT"), ("opponent_team", "TEXT")]:
            if col_name not in mr_cols:
                conn.execute(f"ALTER TABLE model_recommendations ADD COLUMN {col_name} {col_type}")
    except Exception:
        pass

    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mr_game_id ON model_recommendations(game_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mr_player_id ON model_recommendations(player_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mr_timestamp ON model_recommendations(timestamp_generated)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mr_position ON model_recommendations(player_position)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mr_stat ON model_recommendations(stat)")
    except Exception:
        pass

    logger.info("Model schema initialization complete.")
