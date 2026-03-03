# 🏀 Sports Betting Analysis App

A Python backend for NBA sports betting analysis using DuckDB, nba_api, and The Odds API.

## Project Structure

```
sportsbetting-app/
├── backend/
│   ├── db/             # Database schema and connection management
│   ├── ingestion/      # Data ingestion scripts (NBA stats + odds)
│   ├── analysis/       # Betting analysis utilities
│   └── api/            # (Future) REST API layer
├── config/             # Configuration and environment variables
├── scripts/            # CLI runner scripts
└── data/               # Local DuckDB database files (gitignored)
```

## Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure environment
```bash
cp config/.env.example config/.env
# Edit config/.env and add your API keys
```

### 3. Initialize the database
```bash
python scripts/init_db.py
```

### 4. Run data ingestion
```bash
# Ingest NBA game schedule + team stats
python scripts/ingest_nba.py

# Ingest odds (requires Odds API key)
python scripts/ingest_odds.py
```

### 5. Run full pipeline
```bash
python scripts/run_pipeline.py
```

## Data Sources

| Source | Library/API | Cost | Data |
|--------|------------|------|------|
| NBA Stats | `nba_api` | Free | Games, players, teams, box scores |
| Odds | The Odds API | Free tier (500 req/mo) | Spreads, moneylines, totals |

## Getting an Odds API Key
Sign up at [the-odds-api.com](https://the-odds-api.com) — free tier is sufficient to start.

## Database
Uses **DuckDB** — a local, high-performance analytical database. The `.db` file lives in `data/` (gitignored).
