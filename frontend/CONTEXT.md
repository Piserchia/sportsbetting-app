# Frontend Module

## Purpose

React dashboard consuming the FastAPI backend. Six main views: player props analysis, edges dashboard, pipeline monitoring, model health diagnostics, bet performance tracking, and how-it-works explorer.

## Key Components

| File | Purpose |
|------|---------|
| `src/main.jsx` | Entry point, renders PropDashboard |
| `src/components/PropDashboard.jsx` | Player search, stat selection, prop lines, simulations, sportsbook data |
| `src/components/EdgesDashboard2.jsx` | Best +EV edges across today's slate — per-book odds, team/stat/line filters, game status |
| `src/components/PipelineStatus.jsx` | Pipeline run timestamps and DB record counts |
| `src/components/ModelHealthDashboard.jsx` | Model health: backtests, ROI, feature importance, calibration, projection accuracy, drift, edge realization, projection distribution, global SHAP drivers |
| `src/components/BetPerformanceDashboard.jsx` | Bet tracking: performance summary cards, recent bets with opponent/position columns, stat/position filters, performance by type & position tables, stat-vs-position win rate heatmap, model version comparison, reset button |

## API Endpoints Consumed

- `GET /players?q=` — Player search
- `GET /players/{id}/profile` — Player stats + projections
- `GET /players/{id}/game-log` — Historical performance
- `GET /players/{id}/simulations?stat=` — Monte Carlo probability ladder + distribution curve
- `GET /players/{id}/props?stat=` — Sportsbook lines with edge%
- `GET /edges/best?min_edge=&min_line=&max_line=` — Today's best edges with all books
- `GET /games/today` — Today's game slate
- `GET /pipeline/status` — Pipeline health
- `GET /model/backtests` — Backtest metrics by stat
- `GET /model/performance` — Live betting ROI/CLV
- `GET /model/feature-importance?stat=` — Feature importance
- `GET /model/projection-accuracy` — MAE/RMSE per stat
- `GET /model/calibration?stat=` — Calibration curve
- `GET /model/drift?stat=` — Projection error over time
- `GET /model/edge-realization` — ROI by probability band
- `GET /model/projection-distribution?stat=` — Projection histogram
- `GET /model/global-drivers?stat=` — Global SHAP drivers
- `GET /bets/recent?stat=&position=` — Recent tracked bets with optional stat/position filters
- `GET /bets/performance` — Aggregate bet performance (win rate, ROI, CLV)
- `GET /bets/by-model` — Performance by model version
- `GET /bets/by-type` — Performance by stat type
- `GET /bets/by-position` — Performance by player position
- `GET /bets/type-position-matrix` — Win rate heatmap data (stat x position)
- `POST /bets/reset` — Clear all bet history

## Tech Stack

- React 19, Recharts (charts), Vite (build)
- Backend assumed at `http://localhost:8000`

## Important Constraints

- Edge coloring: >=7% green, >=4% light green, <=-5% red, <=-2% orange
- EdgesDashboard2 derives book columns dynamically from response data (DK/FD/MGM show as column per book)
- Team filter matches either team in the matchup (home or away)
- Game status badge: Live (red), Today/Upcoming (green), Final (grey)
- Projection blank = data issue (pipeline not run for today), not a code bug
- PropDashboard supports stat tabs: points, rebounds, assists, steals, blocks
