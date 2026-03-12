# Frontend Module

## Purpose

React dashboard consuming the FastAPI backend. Three main views: player props analysis, edges dashboard, and pipeline monitoring.

## Key Components

| File | Purpose |
|------|---------|
| `src/main.jsx` | Entry point, renders PropDashboard |
| `src/components/PropDashboard.jsx` | Player search, stat selection, prop lines, simulations, sportsbook data |
| `src/components/EdgesDashboard.jsx` | Best +EV edges across today's slate |
| `src/components/PipelineStatus.jsx` | Pipeline run timestamps and DB record counts |

## API Endpoints Consumed

- `GET /players?q=` — Player search
- `GET /players/{id}/profile` — Player stats + projections
- `GET /players/{id}/game-log` — Historical performance
- `GET /players/{id}/simulations?stat=` — Monte Carlo probability ladder + distribution curve
- `GET /players/{id}/props?stat=` — Sportsbook lines with edge%
- `GET /edges/today?min_probability=&stat=` — Today's best edges
- `GET /games/today` — Today's game slate
- `GET /pipeline/status` — Pipeline health

## Tech Stack

- React 19, Recharts (charts), Vite (build)
- Backend assumed at `http://localhost:8000`

## Important Constraints

- Edges dashboard shows warning banner when `source === "model_only"` (no sportsbook data)
- Edge coloring: >=7% green, >=4% light green, <=-5% red, <=-2% orange
- Client-side filter removes lines with fair_odds < -1000
- PropDashboard supports stat tabs: points, rebounds, assists, steals, blocks, PRA, PR, PA, SB
