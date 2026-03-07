# Frontend — Sports Betting Dashboard

Built with React + Recharts. Dark terminal aesthetic.

## Components

### `PropDashboard.jsx`
Main player prop analysis view. Displays:
- Monte Carlo distribution curve with selected line marker
- Last 10 games bar chart (colored by hit/miss vs selected line)
- Full game log table with opponent pace + def rating
- Alternate prop ladder with model probability, fair odds, and edge % per book
- Matchup intelligence flags (pace, defensive rating, rest, historical matchup)
- Model confidence indicators (sample size, minutes stability, usage)

## Running locally (once FastAPI is ready)

```bash
npm install
npm run dev
```

## Wiring to the backend

The component uses `MOCK_*` constants at the top of `PropDashboard.jsx`.
Replace these with API calls to the FastAPI endpoints (to be built):

| Mock constant       | API endpoint                              |
|---------------------|-------------------------------------------|
| `MOCK_PLAYER`       | `GET /players/{player_id}`                |
| `MOCK_GAME_LOG`     | `GET /players/{player_id}/game-log`       |
| `MOCK_SIMULATION`   | `GET /players/{player_id}/simulations`    |
| `MOCK_PROP_LINES`   | `GET /players/{player_id}/props`          |
| `MOCK_OPPONENT_FLAGS` | `GET /games/{game_id}/matchup-flags`   |
