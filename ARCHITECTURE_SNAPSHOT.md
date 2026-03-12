# Architecture Snapshot
> Generated 2026-03-12. Use this as reference before any structural refactor.

---

## 1. Repository Tree (depth 4)

```
sportsbetting-app/
├── backend/
│   ├── api/
│   │   ├── __init__.py
│   │   └── app.py
│   ├── analysis/
│   │   ├── __init__.py
│   │   └── queries.py
│   ├── contracts/
│   │   ├── database_schema.yaml
│   │   ├── feature_schema.yaml
│   │   └── projection_schema.yaml
│   ├── data_sources/
│   │   ├── nba/
│   │   │   ├── nba_ingestor.py
│   │   │   └── game_log_sync.py
│   │   ├── sportsbooks/
│   │   │   ├── odds_ingestor.py
│   │   │   └── props_ingestor.py
│   │   └── injuries/
│   │       └── injury_lineup_ingestor.py
│   ├── database/
│   │   ├── __init__.py
│   │   ├── connection.py
│   │   └── SCHEMA.md
│   ├── features/
│   │   ├── __init__.py
│   │   ├── defense_features.py
│   │   ├── lineup_features.py
│   │   ├── minutes_features.py
│   │   ├── pace_features.py
│   │   ├── rolling_stats.py
│   │   └── usage_features.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── advanced_defense_features.py
│   │   ├── clv_tracker.py
│   │   ├── defense_features.py
│   │   ├── edges_query.py
│   │   ├── feature_builder.py
│   │   ├── lineup_features.py
│   │   ├── pace_features.py
│   │   ├── positional_defense_features.py
│   │   ├── usage_features.py
│   │   ├── minutes_model/
│   │   │   ├── minutes_model.py
│   │   │   └── minutes_model_trainer.py
│   │   └── stat_models/
│   │       ├── stat_models.py
│   │       └── projection_model.py
│   ├── pipeline/
│   │   ├── stages/
│   │   │   ├── stage_01_ingestion.py
│   │   │   ├── stage_02_game_logs.py
│   │   │   ├── stage_03_features.py
│   │   │   ├── stage_04_projections.py
│   │   │   ├── stage_05_simulations.py
│   │   │   ├── stage_06_edges.py
│   │   │   └── stage_07_edges.py
│   │   └── simulations/
│   │       ├── simulation_engine.py
│   │       └── game_simulator.py
│   ├── ingestion/                       ← compat shim (re-exports from data_sources/)
│   ├── db/                              ← compat shim (re-exports from database/)
│   └── __init__.py
├── config/
│   ├── .env
│   ├── .env.example
│   └── logging_config.py
├── data/
│   └── sportsbetting.db          ← DuckDB (gitignored)
├── frontend/
│   ├── public/
│   └── src/
│       ├── assets/
│       ├── components/
│       │   ├── EdgesDashboard.jsx
│       │   ├── EdgesDashboard2.jsx
│       │   ├── PipelineStatus.jsx
│       │   └── PropDashboard.jsx
│       └── main.jsx
├── scripts/
│   ├── backtest_model.py
│   ├── build_features.py
│   ├── calculate_edges.py
│   ├── ingest_nba.py
│   ├── ingest_odds.py
│   ├── ingest_props.py
│   ├── init_db.py
│   ├── run_pipeline.py
│   ├── run_projections.py
│   ├── simulate_props.py
│   ├── start_api.py
│   ├── track_clv.py
│   └── train_minutes_model.py
├── AI_CONTEXT.md
├── AI_TASK_TEMPLATE.md
├── ARCHITECTURE_SNAPSHOT.md      ← this file
├── CLAUDE.md
├── MODEL_ARCHITECTURE_V2.md
├── PIPELINE.md
├── PROJECT_CONTEXT.md
├── README.md
├── REPO_MAP.md
└── requirements.txt
```

---

## 2. Module Responsibilities

**backend/data_sources/**
- Purpose: Fetch raw data from external APIs and normalize into DuckDB
- Subdirectories: `nba/` (nba_ingestor, game_log_sync), `sportsbooks/` (props_ingestor, odds_ingestor), `injuries/` (injury_lineup_ingestor)
- Dependencies: nba_api, SportsGameOdds API v2, The Odds API, DuckDB

**backend/features/**
- Purpose: Individual feature-engineering sub-modules (consumed by `backend/models/feature_builder.py`)
- Key files: `rolling_stats.py`, `minutes_features.py`, `pace_features.py`, `defense_features.py`, `usage_features.py`, `lineup_features.py`
- Dependencies: `player_game_logs`, `team_game_stats`, `games` tables

**backend/models/**
- Purpose: ML projections, feature orchestration, edge aggregation, performance tracking
- Key files: `feature_builder.py`, `edges_query.py`, `clv_tracker.py`
- Subdirectories: `minutes_model/` (minutes_model, trainer), `stat_models/` (stat_models, projection_model)
- Dependencies: `player_features`, `player_game_logs`, `player_projections`, `player_distributions`, `prop_edges`

**backend/pipeline/**
- Purpose: Pipeline orchestration and simulation engine
- Subdirectories: `stages/` (stage_01 through stage_07), `simulations/` (simulation_engine, game_simulator)
- Dependencies: all backend modules

**backend/contracts/**
- Purpose: Schema contract definitions (YAML) for database tables, features, and projections
- Key files: `database_schema.yaml`, `feature_schema.yaml`, `projection_schema.yaml`
- Dependencies: none (definitional)

**backend/api/**
- Purpose: FastAPI REST server — bridges DuckDB to the React frontend (read-only queries)
- Key files: `app.py`
- Dependencies: all DB tables, `backend/models/edges_query.py`, `backend/database/connection.py`

**backend/database/**
- Purpose: DuckDB connection management and schema initialization (21 tables)
- Key files: `connection.py`, `SCHEMA.md`
- Dependencies: none (foundational)

**backend/analysis/**
- Purpose: Ad-hoc reusable analytical SQL queries
- Key files: `queries.py`
- Dependencies: DuckDB

**backend/ingestion/** (compat shim)
- Re-exports from `backend/data_sources/` for backward compatibility

**backend/db/** (compat shim)
- Re-exports from `backend/database/` for backward compatibility

**scripts/**
- Purpose: CLI entry points for each pipeline step + full orchestration
- Key files: `run_pipeline.py` (orchestrator, calls stage modules), `calculate_edges.py`, `build_features.py`, `run_projections.py`, `simulate_props.py`
- Dependencies: all backend modules

**frontend/src/components/**
- Purpose: React dashboard (player props, edges, pipeline status)
- Key files: `PropDashboard.jsx`, `EdgesDashboard.jsx`, `EdgesDashboard2.jsx`, `PipelineStatus.jsx`
- Dependencies: FastAPI at `http://localhost:8000`

---

## 3. Pipeline Flow

From `scripts/run_pipeline.py` (calls `backend/pipeline/stages/` modules):

```
INGESTION PHASE
1.  ingest_teams()                  → teams
2.  ingest_players()                → players
3.  ingest_games()                  → games (completed results)
4.  ingest_schedule()               → games (full season + upcoming)
5.  ingest_box_scores(season)       → player_game_stats, team_game_stats
6.  ingest_odds()                   → odds
7.  ingest_props()                  → prop_line_history, sportsbook_props
8.  ingest_injuries_and_lineups()   → player_injuries, starting_lineups

MODEL PHASE
9.  sync_game_logs()                → player_game_logs
10. build_player_features()         → player_features
11. generate_projections()          → player_projections, player_distributions
12. simulate_player_props()         → player_simulations
13. calculate_edges()               → prop_edges
```

**Scheduling (--schedule flag):**
- Daily 6:00 AM: full pipeline
- Every 2 hours: odds refresh only (step 6)
- 6am / 12pm / 4pm / 7pm: props refresh (step 7)

---

## 4. Database Tables (21 total)

**Core data (init_schema)**

| Table | PK | Purpose |
|---|---|---|
| teams | team_id (INTEGER) | NBA team metadata |
| players | player_id (INTEGER) | NBA player metadata |
| games | game_id (VARCHAR) | Schedule + results |
| player_game_stats | stat_id (game_id+player_id) | Box score per player/game |
| team_game_stats | stat_id (game_id+team_id) | Box score per team/game |
| odds | odds_id (game+book+market) | Game-level odds (ML/spread/total) |
| ingestion_log | log_id (VARCHAR) | Pipeline run audit log |

**Model pipeline (init_model_schema)**

| Table | PK | Purpose |
|---|---|---|
| player_game_logs | (game_id, player_id) | Normalized per-game stats |
| player_features | (game_id, player_id) | 50+ engineered features |
| player_projections | (game_id, player_id) | Predicted stat means |
| player_distributions | (game_id, player_id, stat) | Distribution params (mean, std_dev) |
| player_simulations | (game_id, player_id, stat, line) | P(stat >= line) from 10k MC |
| prop_edges | (game_id, player_id, stat, line, book) | Model vs sportsbook edge % |
| player_injuries | injury_id (TEXT) | Injury reports |
| starting_lineups | lineup_id (TEXT) | Confirmed starters |
| model_backtests | backtest_id (TEXT) | Historical model performance |
| team_advanced_stats | (game_id, team_id) | Off/def ratings, pace |
| player_onoff_splits | (player_id, teammate_id, stat) | Teammate impact splits |

**Sportsbook / tracking**

| Table | PK | Purpose |
|---|---|---|
| sportsbook_props | prop_id (TEXT) | Latest prop line snapshot |
| prop_line_history | history_id (TEXT) | Append-only prop line log |
| bet_results | bet_id (TEXT) | Bet outcomes + CLV tracking |

---

## 5. Data Flow Map

```
NBA API
  └─→ player_game_stats, team_game_stats, games, teams, players
        │
        ▼
  game_log_sync
        └─→ player_game_logs
                │
                ▼
        feature_builder
                └─→ player_features
                        │
                        ▼
                projection_model
                        └─→ player_projections
                             player_distributions
                                    │
                                    ▼
                            simulation_engine
                                    └─→ player_simulations
                                               │
SportsGameOdds API                             │
  └─→ sportsbook_props ──────────────────────→ calculate_edges
  └─→ prop_line_history                              └─→ prop_edges
                                                           │
                                                           ▼
                                                    FastAPI /edges/today
                                                    FastAPI /edges/best
                                                           │
                                                           ▼
                                                     React Dashboard
```

---

## 6. External APIs Used

| API | Module | Auth | Rate Limit |
|---|---|---|---|
| nba_api (NBA stats) | `backend/data_sources/nba/nba_ingestor.py` | None | 3s delay enforced |
| SportsGameOdds v2 | `backend/data_sources/sportsbooks/props_ingestor.py` | `SPORTSGAMEODDS_API_KEY` | 60-min cooldown, credit budget |
| The Odds API | `backend/data_sources/sportsbooks/odds_ingestor.py` | `ODDS_API_KEY` | Per-request billing |
| ESPN / NBA.com | `backend/data_sources/injuries/injury_lineup_ingestor.py` | None | Scraped |

---

## 7. Import Dependencies

```
run_pipeline.py
  ├── backend/pipeline/stages/stage_01_ingestion
  │     ├── data_sources/nba/nba_ingestor    (teams, players, games, box scores)
  │     ├── data_sources/sportsbooks/odds_ingestor
  │     ├── data_sources/sportsbooks/props_ingestor
  │     └── data_sources/injuries/injury_lineup_ingestor
  ├── backend/pipeline/stages/stage_02_game_logs
  │     └── data_sources/nba/game_log_sync
  ├── backend/pipeline/stages/stage_03_features
  │     └── feature_builder
  │           ├── models/minutes_model/minutes_model
  │           ├── models/pace_features
  │           ├── models/defense_features
  │           ├── models/advanced_defense_features
  │           ├── models/positional_defense_features
  │           ├── models/usage_features
  │           └── models/lineup_features
  ├── backend/pipeline/stages/stage_04_projections
  │     └── models/stat_models/projection_model
  │           └── models/stat_models/stat_models
  ├── backend/pipeline/stages/stage_05_simulations
  │     └── pipeline/simulations/simulation_engine
  └── backend/pipeline/stages/stage_06_edges + stage_07_edges

app.py (FastAPI)
  ├── database/connection.py
  └── models/edges_query.py
```

---

## 8. Risk Areas for Refactor

| File | Risk | Reason |
|---|---|---|
| `scripts/run_pipeline.py` | HIGH | Orchestrates entire pipeline; step order matters |
| `backend/database/connection.py` | HIGH | Initializes all 21 table schemas; changes break everything downstream |
| `backend/models/feature_builder.py` | HIGH | Orchestrates all 8 feature groups; wide output schema |
| `backend/pipeline/simulations/simulation_engine.py` | HIGH | PROP_LINES must stay half-point (.5) to match sportsbook lines; changes break edge join |
| `scripts/calculate_edges.py` | HIGH | game_id must come from `sportsbook_props` not `player_simulations`; exact line match required |
| `backend/data_sources/sportsbooks/props_ingestor.py` | MEDIUM | SGO API credit-limited; game matching logic fragile (team abbr map) |
| `backend/models/stat_models/projection_model.py` | MEDIUM | Uses last completed game_id as key; projections are for upcoming games via player history |
| `backend/api/app.py` | MEDIUM | Single 900-line file; all endpoints; CORS config |
