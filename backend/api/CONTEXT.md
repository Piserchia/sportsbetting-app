# API Module

## Purpose

FastAPI REST server providing data to the React frontend. All endpoints are read-only queries against DuckDB.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | DB connection check |
| GET | `/players` | Search players by name, filter active |
| GET | `/players/{id}/profile` | Full stats: season avg, L10, L5, projections, next game |
| GET | `/players/{id}/game-log` | Last N games with all stat lines |
| GET | `/players/{id}/simulations?stat=` | Probability ladder + distribution curve |
| GET | `/players/{id}/props?stat=` | Sportsbook lines + model probs + edge% per book |
| GET | `/games/today` | Today's NBA slate |
| GET | `/edges/today?min_probability=&stat=` | Best +EV edges (top 3 per player/stat) |
| GET | `/games/{id}/matchup-flags` | Contextual intelligence (rest, defense, pace, H2H) |
| GET | `/pipeline/status` | Ingestion timestamps + DB record counts |

## Tables Consumed

- All tables (read-only)
- Primary joins: `player_simulations` ↔ `sportsbook_props` ↔ `prop_edges`

## Edge Calculation

```python
implied_prob = abs(odds) / (abs(odds) + 100)  # for negative odds
edge_percent = (model_probability - implied_prob) * 100
```

- `/edges/today` queries `prop_edges` table (pre-computed by `calculate_edges.py`)
- `/players/{id}/props` computes edges inline via JOIN
- Falls back to model-only mode if no sportsbook data exists

## Important Constraints

- CORS allows localhost:5173-5177 and :3000
- Server runs on port 8000 (configurable)
- `/edges/today` limits to top 3 edges per player/stat, filters fair_odds > -1000
- Falls back to most recent date with edges if today has none
