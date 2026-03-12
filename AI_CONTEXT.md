# AI Context — NBA Prop Betting Analytics Platform

> **For AI assistants:** Read this file first. Then read the relevant module `CONTEXT.md` and `backend/database/SCHEMA.md` before modifying any code.

## System Overview

Full-stack NBA player prop betting analytics platform. Ingests game data and sportsbook odds, engineers contextual features, generates ML projections, runs Monte Carlo simulations, and detects +EV edges against sportsbook lines.

## Data Flow

```
NBA API + SportsGameOdds API
        │
        ▼
   Raw Ingestion
  (teams, players, games, box scores, odds, props, injuries)
        │
        ▼
   Game Log Sync
  (normalize box scores → player_game_logs)
        │
        ▼
   Feature Engineering
  (rolling stats, minutes, pace, defense, usage, lineup context → player_features)
        │
        ▼
   ML Projections
  (LightGBM models → player_projections + player_distributions)
        │
        ▼
   Monte Carlo Simulation
  (10k samples per player/stat with Gamma/NegBin/Copula → player_simulations)
        │
        ▼
   Edge Detection
  (model probability vs sportsbook implied probability → prop_edges)
        │
        ▼
   FastAPI → React Dashboard
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Database | DuckDB (embedded, file-based) |
| Backend | Python, FastAPI, pandas, scipy, LightGBM |
| Frontend | React 19, Recharts, Vite |
| Data Sources | nba_api (free), SportsGameOdds API v2 (paid, limited credits) |
| Scheduling | Python `schedule` library in `run_pipeline.py` |

## Database

- **Location:** `data/sportsbetting.db`
- **Engine:** DuckDB (embedded SQL, no server)
- **Schema docs:** [`backend/database/SCHEMA.md`](backend/database/SCHEMA.md)
- **21 tables** across raw data, features, simulations, and edge detection

## Directory Structure

```
backend/
  data_sources/        → Data fetching from external APIs
    nba/               → NBA API ingestion (teams, players, games, box scores, game logs)
    sportsbooks/       → Odds and props from SportsGameOdds / The Odds API
    injuries/          → Injury reports and starting lineups
  features/            → Feature engineering sub-modules
  models/              → ML models and feature orchestration
    minutes_model/     → LightGBM minutes projection model + trainer
    stat_models/       → Position-specific stat models + projection model
  pipeline/            → Pipeline orchestration
    stages/            → Stage modules (stage_01_ingestion through stage_07_edges)
    simulations/       → Monte Carlo simulation engine + game simulator
  api/                 → FastAPI REST server
  database/            → DuckDB connection + schema initialization
  contracts/           → Schema contracts (database, feature, projection YAML definitions)
  analysis/            → Ad-hoc analytical queries
  ingestion/           → (compat shim — re-exports from data_sources/)
  db/                  → (compat shim — re-exports from database/)

scripts/               → CLI entry points for pipeline steps

frontend/src/
  components/          → React dashboard components

config/                → Environment variables, logging config
data/                  → DuckDB database file (gitignored)
```

> **Note:** The pipeline is organized into numbered stage modules under `backend/pipeline/stages/` (stage_01 through stage_07). `run_pipeline.py` calls these stage modules in sequence.

See [`REPO_MAP.md`](REPO_MAP.md) for the full file listing.

## Module Documentation

| Module | Context File | Purpose |
|--------|-------------|---------|
| Data Sources | `backend/data_sources/` | Fetch data from NBA API + SportsGameOdds |
| Features | [`backend/features/CONTEXT.md`](backend/features/CONTEXT.md) | Rolling stats, pace, defense, usage, lineup features |
| Models | [`backend/models/CONTEXT.md`](backend/models/CONTEXT.md) | Projections, simulations, feature orchestration |
| API | [`backend/api/CONTEXT.md`](backend/api/CONTEXT.md) | REST endpoints serving the React frontend |
| Frontend | [`frontend/CONTEXT.md`](frontend/CONTEXT.md) | React dashboard for props, edges, pipeline status |
| Database | [`backend/database/SCHEMA.md`](backend/database/SCHEMA.md) | All 21 table schemas |
| Pipeline | [`PIPELINE.md`](PIPELINE.md) | Full pipeline execution order |
| Contracts | `backend/contracts/` | Schema contracts for database, features, and projections |

## Projection Explanation System

SHAP-based projection debugging. When projections are generated via LightGBM, SHAP feature contributions are computed and stored in `projection_explanations`. This allows users to understand why the model produced a specific projection.

- **Backend:** `backend/models/stat_models/stat_models.py` computes SHAP values after prediction
- **Table:** `projection_explanations` (game_id, player_id, stat, feature, contribution)
- **API:** `GET /players/{id}/projection_explanation?stat=points` returns ranked contributions
- **Frontend:** `ProjectionDebugger.jsx` — bar chart + top positive/negative drivers

## Instructions for AI Assistants

Before modifying code:

1. Read `AI_CONTEXT.md` (this file)
2. Read the relevant module `CONTEXT.md` file
3. Verify database columns in `backend/database/SCHEMA.md`
4. **Never invent tables or fields** — only use what exists in the schema
5. **Update context documentation** when architecture changes

### Critical Constraints

- **SportsGameOdds API has limited credits.** Never make live API calls for debugging. See `CLAUDE.md` for rules.
- **Prop lines use half-point values** (e.g., 24.5 not 25). Both DraftKings and FanDuel post .5 lines exclusively. The simulation engine's `PROP_LINES` must match.
- **Edge calculation requires exact line matching** between `player_simulations` and `sportsbook_props` — there is no interpolation.
- **DuckDB syntax** — uses `INSERT OR REPLACE`, `QUALIFY`, window functions. Not all MySQL/Postgres syntax works.
