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
| GET | `/edges/today?min_probability=&stat=` | Best +EV edges (top 3 per player/stat) — legacy |
| GET | `/edges/best?min_edge=&min_line=&max_line=` | Today's edges grouped by prop — all books nested, supports line range filters |
| GET | `/debug/shap/{player_id}?stat=` | On-demand SHAP recomputation with full diagnostics (base value, prediction, feature values) |
| GET | `/games/{id}/matchup-flags` | Contextual intelligence (rest, defense, pace, H2H) |
| GET | `/pipeline/status` | Ingestion timestamps + DB record counts |
| GET | `/model/backtests` | Aggregated backtest metrics (hit rate, Brier, ROI) by stat |
| GET | `/model/performance` | Live betting performance from CLV tracker |
| GET | `/model/feature-importance?stat=` | LightGBM gain-based feature importance (top 15) — reads from `model_feature_importance` table |
| GET | `/model/projection-accuracy` | MAE/RMSE of projections vs actuals per stat |
| GET | `/model/calibration?stat=` | Calibration curve bins + ECE score |
| GET | `/model/drift?stat=` | Projection error over time (actual - predicted), grouped by game date |
| GET | `/model/edge-realization` | ROI bucketed by model probability bands from bet_results |
| GET | `/model/projection-distribution?stat=` | Histogram of projected stat means across all players |
| GET | `/model/global-drivers?stat=` | Top features by average absolute SHAP contribution |
| GET | `/model/shrinkage-diagnostics?stat=` | Players with largest Bayesian shrinkage adjustments |
| GET | `/bets/recent` | Recent tracked bets (limit 200) — supports `?stat=` and `?position=` filters |
| GET | `/bets/performance` | Aggregate performance metrics (win rate, ROI, CLV) |
| GET | `/bets/by-model` | Performance grouped by model version |
| GET | `/bets/by-type` | Performance grouped by stat type (points, rebounds, etc.) |
| GET | `/bets/by-position` | Performance grouped by player position (PG, SG, SF, PF, C) |
| GET | `/bets/type-position-matrix` | Win rates by stat type AND position (powers heatmap) |
| POST | `/bets/reset` | Delete all tracked bet history from `model_recommendations` |

## Tables Consumed

- All tables (read-only)
- Primary joins: `player_simulations` ↔ `sportsbook_props` ↔ `prop_edges`

## Edge Calculation

```python
implied_prob = abs(odds) / (abs(odds) + 100)  # for negative odds
edge_percent = (model_probability - implied_prob) * 100
```

- `/edges/today` queries `prop_edges` table (pre-computed by `calculate_edges.py`) — legacy endpoint
- `/edges/best` queries `prop_edges` for today, returns all sportsbook rows grouped by (player, stat, line) with a nested `books` array; ranked by `bet_score = (edge_percent * 0.6) + (model_probability * 25)`; response includes `home_team`, `away_team`, and `game_status` for client-side team filtering
- `/players/{id}/props` computes edges inline via JOIN
- Falls back to model-only mode if no sportsbook data exists

## Projection Consistency

- Projections displayed in the UI must match the same game_id used for edge calculations
- `/players/{id}/profile` only returns projections for upcoming games (`game_date >= CURRENT_DATE AND status != 'Final'`)
- `/edges/today` and `/edges/best` join projections by `(player_id, game_id)` — never by latest historical game
- If no upcoming projection exists, the UI shows "—" (not a stale historical projection)

## Important Constraints

- CORS allows localhost:5173-5177 and :3000
- Server runs on port 8000 (configurable)
- `/edges/today` limits to top 3 edges per player/stat, filters fair_odds > -1000
- Edges endpoints strictly show CURRENT_DATE only — never fall back to previous dates
