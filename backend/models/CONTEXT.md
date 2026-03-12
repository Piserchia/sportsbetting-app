# Models Module

## Purpose

ML projections, Monte Carlo simulations, feature orchestration, and performance tracking. This is the core analytics engine.

## Key Modules

| File | Purpose | Tables Written |
|------|---------|---------------|
| `feature_builder.py` | Orchestrates all feature groups | `player_features` |
| `projection_model.py` | LightGBM stat projections | `player_projections`, `player_distributions` |
| `stat_models.py` | Position-specific LightGBM models | (used by projection_model) |
| `simulation_engine.py` | Monte Carlo simulations | `player_simulations` |
| `game_simulator.py` | Game-level correlated simulation | (experimental) |
| `minutes_model.py` | LightGBM minutes projection | (used by feature_builder) |
| `clv_tracker.py` | Closing Line Value + bet tracking | `bet_results` |

## Simulation Engine Details

- **10,000 Monte Carlo samples** per player per stat
- **Distributions:** Gamma (points), Negative Binomial (rebounds, assists, steals, blocks)
- **Combo props:** Gaussian copula preserving Spearman rank correlations
- **Minimum std_dev:** 1.5 (prevents degenerate distributions)

### PROP_LINES (half-point values matching sportsbook conventions)

```
points:   9.5, 10.5, 11.5, ..., 32.5, 34.5, 39.5, 44.5  (27 lines)
rebounds: 1.5, 2.5, ..., 11.5, 14.5                       (12 lines)
assists:  1.5, 2.5, ..., 11.5                              (11 lines)
steals:   0.5, 1.5, 2.5, 3.5                               (4 lines)
blocks:   0.5, 1.5, 2.5, 3.5                               (4 lines)
```

### COMBO_LINES (integer values, model-only display)

```
PRA: 10, 15, 20, ..., 60    PR: 10, 15, ..., 45
PA:  10, 15, ..., 45         SB: 0.5, 1.5, ..., 5.5
```

## Tables Consumed

- `player_game_logs` (feature building, correlation estimation)
- `player_features` (projections)
- `player_projections` + `player_distributions` (simulations)
- `prop_edges` + `player_game_logs` (CLV tracking)

## Important Constraints

- **PROP_LINES must use half-point values** — edge calculation requires exact line match with `sportsbook_props`
- Simulation falls back to clipped Normal if Gamma/NegBin parameter fitting fails
- Correlation matrix falls back to 0.3 default if insufficient historical data
- Projections use LightGBM with heuristic fallback for players with limited data
