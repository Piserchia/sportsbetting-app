# Models Module

## Purpose

ML projections, Monte Carlo simulations, feature orchestration, and performance tracking. This is the core analytics engine.

## Key Modules

| File | Purpose | Tables Written |
|------|---------|---------------|
| `bayesian_shrinkage.py` | Hierarchical Bayesian shrinkage toward position priors (k=20) | `player_stat_posteriors` |
| `feature_builder.py` | Orchestrates all feature groups including Bayesian posteriors | `player_features` |
| `projection_model.py` | LightGBM stat projections; `std_dev` in distributions is scaled to projected mean to preserve CV | `player_projections`, `player_distributions` |
| `stat_models.py` | Position-specific LightGBM models | (used by projection_model) |
| `simulation_engine.py` | Monte Carlo simulations | `player_simulations` |
| `game_simulator.py` | Game-level correlated simulation | (experimental) |
| `minutes_model.py` | LightGBM minutes projection | (used by feature_builder) |
| `clv_tracker.py` | Closing Line Value + bet tracking | `bet_results` |

## Simulation Engine Details

- **10,000 Monte Carlo samples** per player per stat
- **Minutes-conditioned variance:** For each draw, minutes are sampled from `Normal(minutes_projection, max(proj * 0.18, 2.0))`, clamped to `[max(12, proj*0.65), min(42, proj*1.35)]`. Only the **standard deviation** is scaled per-draw: `stat_std = base_std × sqrt(minutes_sim / minutes_proj)`. The **mean is fixed** from the LightGBM projection (not rescaled by minutes, since LightGBM already uses minutes as an input feature).
- **Distributions:** Gamma (points), Negative Binomial (rebounds, assists, steals, blocks)
- **Combo props:** Gaussian copula preserving Spearman rank correlations (uses projected mean/std directly, not minutes-adjusted)
- **Minimum std_dev:** 1.5 (prevents degenerate distributions)
- **Distribution table:** `player_distributions.std_dev` stores raw historical std (60% recent + 40% full-season). No projection-based scaling — avoids compounding with minutes-conditioning.
- **Fallback:** If `minutes_projection` is 0 or missing, falls back to direct single-distribution sampling
- **Validation:** Post-simulation checks verify mean consistency (<10% drift), std bounds, probability range [0.001, 0.999], and tail behavior. Results logged to `ingestion_log`.

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
