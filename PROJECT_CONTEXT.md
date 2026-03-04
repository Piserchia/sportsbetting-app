# Sports Betting App — Project Context & Continuity Doc

Last updated: 2026-03-04
Repository: https://github.com/Piserchia/sportsbetting-app

---

## 1. Project Goal

Build a sports betting analytics engine focused on identifying **positive expected value (+EV) NBA player prop bets**, particularly alternate prop ladders (e.g. points 25+, 30+, 35+).

Core workflow:
```
NBA stats → features → projections → simulations → probabilities → EV
```

---

## 2. Current Status

### ✅ Done
- DuckDB local database with full schema (see Section 4)
- NBA data ingestion via `nba_api` (teams, players, games, box scores)
- The Odds API integration scaffolded (game lines: spreads, moneylines, totals)
- Model pipeline: feature builder → projections → Monte Carlo simulation → edge detection
- Retry logic + exponential backoff on NBA.com rate limiting
- Full pipeline runner with optional scheduling

### 🔲 Next Up
- **SportsGameOdds API integration** for player prop lines (decided over The Odds API for props)
- **FastAPI REST layer** (`backend/api/app.py` is empty placeholder)
- **Frontend dashboard** (not started)
- **Deployment / scheduling** on a server (not started)

### 🔲 Future / Planned
- Rotation modeling (injury adjustments, blowout probability)
- Opponent defensive rating / pace matchup features
- Gradient boosting model to replace weighted average projections
- Usage rate / true shooting features in `player_features`

---

## 3. Repository Structure

```
sportsbetting-app/
│
├── data/
│   └── sportsbetting.db          # DuckDB local database (gitignored)
│
├── config/
│   ├── .env.example              # Copy to .env and fill in keys
│   ├── .env                      # Gitignored — actual secrets
│   └── logging_config.py         # Colored logging setup
│
├── backend/
│   ├── db/
│   │   └── connection.py         # DuckDB connection + init_schema() + init_model_schema()
│   │
│   ├── ingestion/
│   │   ├── nba_ingestor.py       # nba_api: teams, players, games, box scores
│   │   ├── odds_ingestor.py      # The Odds API: spreads, moneylines, totals
│   │   └── game_log_sync.py      # Bridges player_game_stats → player_game_logs
│   │
│   ├── models/
│   │   ├── feature_builder.py    # Rolling window features from game logs
│   │   ├── projection_model.py   # Weighted avg projections + std dev distributions
│   │   └── simulation_engine.py  # Monte Carlo simulation, prob ladders, odds helpers
│   │
│   └── analysis/
│       └── queries.py            # Analytical queries (ATS, O/U, player logs, splits)
│
├── scripts/
│   ├── init_db.py                # One-time DB setup
│   ├── ingest_nba.py             # Pull NBA data (run with --season 2025-26)
│   ├── ingest_odds.py            # Pull game odds (requires ODDS_API_KEY)
│   ├── build_features.py         # Sync logs + compute rolling features
│   ├── run_projections.py        # Weighted avg projections + distributions
│   ├── simulate_props.py         # Monte Carlo sims → probability ladders
│   ├── calculate_edges.py        # EV calculation vs sportsbook (model-only until props added)
│   └── run_pipeline.py           # Full pipeline runner (all stages, optional --schedule)
│
└── api/
    └── app.py                    # Placeholder — FastAPI layer not yet built
```

---

## 4. Database Schema

### Raw / Ingestion Tables
| Table | Source | Description |
|-------|--------|-------------|
| `teams` | nba_api | 30 NBA teams |
| `players` | nba_api | All active + historical players |
| `games` | nba_api | Game schedule + scores |
| `player_game_stats` | nba_api | Per-player box scores (raw) |
| `team_game_stats` | nba_api | Per-team box scores (raw) |
| `odds` | The Odds API | Game lines: spreads, moneylines, totals |
| `ingestion_log` | internal | Tracks every pipeline run |

### Model Pipeline Tables
| Table | Populated By | Description |
|-------|-------------|-------------|
| `player_game_logs` | `game_log_sync.py` | Normalized game logs (bridge from raw) |
| `player_features` | `feature_builder.py` | Rolling 5/10 game averages, minutes trend |
| `player_projections` | `projection_model.py` | Weighted avg stat projections |
| `player_distributions` | `projection_model.py` | Mean + std dev per player/stat |
| `player_simulations` | `simulation_engine.py` | Probability ladders (10k Monte Carlo sims) |
| `prop_edges` | `calculate_edges.py` | Model prob vs book odds, EV, edge % |

### Planned Tables (not yet built)
| Table | Description |
|-------|-------------|
| `sportsbook_odds` (props) | Player prop lines from SportsGameOdds |

---

## 5. Pipeline Execution Order

```bash
# One-time
python scripts/init_db.py

# Daily / ongoing
python scripts/ingest_nba.py --season 2025-26   # incremental — skips existing box scores
python scripts/build_features.py                 # sync logs + rolling features
python scripts/run_projections.py                # projections + distributions
python scripts/simulate_props.py                 # Monte Carlo sims
python scripts/calculate_edges.py               # EV (model-only until props odds added)

# Or run everything at once
python scripts/run_pipeline.py
python scripts/run_pipeline.py --schedule        # runs daily 6am + odds refresh every 2hrs
```

---

## 6. Environment Variables (`config/.env`)

```
DB_PATH=data/sportsbetting.db
ODDS_API_KEY=your_key_here         # https://the-odds-api.com — free tier 500 req/mo
NBA_API_DELAY=3.0                  # seconds between nba_api calls (increase if timeouts)
NBA_API_MAX_RETRIES=5              # retries with exponential backoff on timeout
NBA_SEASONS=2025-26,2024-25,2023-24
LOG_LEVEL=INFO
```

---

## 7. Key Technical Decisions & Rationale

| Decision | Choice | Reason |
|----------|--------|--------|
| Database | DuckDB | Local, zero-config, columnar — great for analytical queries |
| NBA data | `nba_api` | Free, no key needed, comprehensive |
| Game odds | The Odds API | Free tier sufficient for spreads/moneylines/totals |
| **Prop odds** | **SportsGameOdds** (planned) | Better bulk prop querying vs The Odds API's per-event model |
| Simulation | NumPy vectorized Monte Carlo | 10k sims × 500 players in <5s |
| Projection formula | Weighted avg (0.5×L10 + 0.3×L5 + 0.2×season) | Simple baseline, easy to replace with ML later |
| Std dev floor | 1.5 | Prevents distribution collapse for low-variance players |

---

## 8. Known Issues / Bugs Fixed

| Issue | Fix | Commit |
|-------|-----|--------|
| DuckDB parameter mismatch on box score INSERT | Switched to explicit column names in INSERT | `52dcede` |
| NBA.com rate limiting / timeouts | Increased delay to 3s, added exponential backoff retry | `6077747` |

---

## 9. Data Source Notes

### nba_api
- Unofficial wrapper around NBA.com stats API — no key required
- Rate limits aggressively; use `NBA_API_DELAY=3.0` minimum
- Box score fetch = 1 API call per game (~650 games/season = ~35 min full pull)
- Subsequent runs are incremental (skips already-ingested games)
- Current season: **2025-26**

### The Odds API
- Free tier: 500 requests/month
- Used for: game spreads, moneylines, totals
- **Not used for player props** (per-event only, burns quota fast)
- Sign up: https://the-odds-api.com

### SportsGameOdds (planned — not yet integrated)
- Better for player props: bulk queryable by market type
- Supports: points O/U, rebounds O/U, assists O/U, alternate ladders
- Charges per event not per market (efficient)
- Sign up: https://sportsgameodds.com
- Integration file to create: `backend/ingestion/props_ingestor.py`

---

## 10. Next Session — Immediate Next Steps

When picking this up in a new context window, the next things to build are:

1. **SportsGameOdds props ingestor** (`backend/ingestion/props_ingestor.py`)
   - Fetch player prop lines per game
   - Map to `player_id` via player name matching
   - Write to `sportsbook_odds` table (or extend existing `odds` table)
   - Wire into `calculate_edges.py` (already scaffolded and waiting)

2. **FastAPI REST layer** (`backend/api/app.py`)
   - Endpoints needed:
     - `GET /players/{player_id}/simulations` — prob ladder for a player
     - `GET /edges` — top +EV bets today
     - `GET /players/{player_id}/game-log` — recent game log
     - `GET /games/today` — today's slate with projections

3. **Frontend dashboard**
   - Stack not decided yet
   - Should display: today's slate, player prop probabilities, top edges

---

## 11. Spec Documents (summarized)

Two spec docs were provided by the user:

**Doc 1 — Implementation Specification**
- Defined exact table schemas for model pipeline
- Specified feature formulas, projection weights, simulation logic
- Defined prop ladders: points [15,20,25,30,35,40], etc.
- Defined EV formula: `EV = (probability * payout) - (1 - probability)`

**Doc 2 — Development Specification (Next Phase)**
- Broader architecture overview
- Emphasized minutes projection as most critical variable
- Described staged pipeline architecture
- Outlined future: rotation modeling, injury adjustments, blowout probability
- Gradient boosting as future replacement for weighted avg projections
