# AI Context — NBA Prop Betting Analytics Platform

> **For AI assistants:** Read this file first. Then read the relevant module `CONTEXT.md` and `backend/db/SCHEMA.md` before modifying any code.

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
- **Schema docs:** [`backend/db/SCHEMA.md`](backend/db/SCHEMA.md)
- **21 tables** across raw data, features, simulations, and edge detection

## Directory Structure

```
backend/
  ingestion/     → Data fetching from external APIs
  features/      → Feature engineering sub-modules
  models/        → ML models, simulation engine, feature orchestration
  api/           → FastAPI REST server
  db/            → DuckDB connection + schema initialization
  analysis/      → Ad-hoc analytical queries

scripts/         → CLI entry points for pipeline steps

frontend/src/
  components/    → React dashboard components

config/          → Environment variables, logging config
data/            → DuckDB database file (gitignored)
```

See [`REPO_MAP.md`](REPO_MAP.md) for the full file listing.

## Module Documentation

| Module | Context File | Purpose |
|--------|-------------|---------|
| Ingestion | [`backend/ingestion/CONTEXT.md`](backend/ingestion/CONTEXT.md) | Fetch data from NBA API + SportsGameOdds |
| Features | [`backend/features/CONTEXT.md`](backend/features/CONTEXT.md) | Rolling stats, pace, defense, usage, lineup features |
| Models | [`backend/models/CONTEXT.md`](backend/models/CONTEXT.md) | Projections, simulations, feature orchestration |
| API | [`backend/api/CONTEXT.md`](backend/api/CONTEXT.md) | REST endpoints serving the React frontend |
| Frontend | [`frontend/CONTEXT.md`](frontend/CONTEXT.md) | React dashboard for props, edges, pipeline status |
| Database | [`backend/db/SCHEMA.md`](backend/db/SCHEMA.md) | All 21 table schemas |
| Pipeline | [`PIPELINE.md`](PIPELINE.md) | Full pipeline execution order |

## Instructions for AI Assistants

Before modifying code:

1. Read `AI_CONTEXT.md` (this file)
2. Read the relevant module `CONTEXT.md` file
3. Verify database columns in `backend/db/SCHEMA.md`
4. **Never invent tables or fields** — only use what exists in the schema
5. **Update context documentation** when architecture changes

### Critical Constraints

- **SportsGameOdds API has limited credits.** Never make live API calls for debugging. See `CLAUDE.md` for rules.
- **Prop lines use half-point values** (e.g., 24.5 not 25). Both DraftKings and FanDuel post .5 lines exclusively. The simulation engine's `PROP_LINES` must match.
- **Edge calculation requires exact line matching** between `player_simulations` and `sportsbook_props` — there is no interpolation.
- **DuckDB syntax** — uses `INSERT OR REPLACE`, `QUALIFY`, window functions. Not all MySQL/Postgres syntax works.
