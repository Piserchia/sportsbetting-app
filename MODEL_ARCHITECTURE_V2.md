# PropModel — Model Architecture v2

## Overview

PropModel v2 replaces the heuristic projection system with trained ML models,
statistically appropriate simulation distributions, and a backtesting framework.
The pipeline architecture and DuckDB schema are unchanged — every upgrade is
a drop-in replacement that falls back gracefully when training data is thin.

---

## 1. Minutes Model (LightGBM)

**File:** `backend/models/minutes_model.py`

### v1 → v2
v1 used a heuristic: `0.5 * L10 + 0.3 * L5 + 0.2 * (L10 + slope*2)`

v2 trains a LightGBM regression model on all historical player-game rows.

**Features:** `minutes_avg_last_5/10`, `minutes_trend`, `games_started_last_5`,
`season_avg_minutes`, `spread`, `expected_game_pace`, `is_home`, `days_rest`,
`is_back_to_back`

**Config:** `objective=regression_l1` (MAE — robust to DNP outliers), 300 rounds.

**Blowout adjustment** is applied multiplicatively on top of model output:
spread >= 10 → ×0.92, spread >= 15 → ×0.85

**Fallback:** < 200 training rows → original heuristic formula.

---

## 2. ML Stat Projections (LightGBM)

**File:** `backend/models/stat_models.py`

Separate LightGBM regressors for **points**, **rebounds**, and **assists**,
trained on `player_features` joined with `player_game_logs` actuals.

Points features include: `minutes_projection`, EWMA recent adjusted (`points_recent_adj`),
L10/season averages, `usage_proxy`, `pace_adjustment_factor`, `defense_adj_pts`, `spread`,
`team_total`, `is_home`, `days_rest`, `is_back_to_back`, `games_started_last_5`.

Rebounds and assists use equivalent stat-appropriate feature sets.

### Recent Performance Feature Engineering

Raw last-5 rolling averages (`*_avg_last_5`) were replaced with EWMA-based
regression-to-mean features (`*_recent_adj`) to reduce streak overfitting:

1. **EWMA** — weights `[0.40, 0.25, 0.15, 0.10, 0.06, 0.04]` over up to 6 **prior** games (excludes current game)
2. **Regression-to-mean** — `recent_adj = season_avg + clip(ewma - season_avg, -6, +6)`

This prevents the model from overreacting to 2-3 game hot/cold streaks while
still capturing genuine trend shifts via exponential decay.

### Hierarchical Bayesian Shrinkage

**File:** `backend/models/bayesian_shrinkage.py`

Player stat baselines are stabilized via Bayesian shrinkage toward position-group priors:

```
posterior_mean = (n * player_mean + k * prior_mean) / (n + k)
```

- **k = 20** (shrinkage strength — configurable)
- **prior_mean** = average stat for the player's position group (Guard/Forward/Center)
- Players with < 3 games use the prior entirely
- Players with 60+ games are barely affected (~75% own mean)

The `*_posterior` features replace raw `season_avg_*` as the baseline input to LightGBM models, reducing overfitting to small-sample noise for role players and rookies.

### Feature Leakage Prevention

All rolling features (EWMA, L10, season avg) **exclude the current game** to prevent
target leakage during training. The feature for game X uses only games before X.

- EWMA window: `series.iloc[start:idx]` (not `idx+1`)
- L10 / season avg: computed on `series.shift(1)` (shifts values forward, making current game NaN)
- First game per player: all features are 0.0 (no prior data available)
- **Guardrail**: feature builder asserts first-game `recent_adj == 0.0`; raises `RuntimeError` if violated

### Projection Game Mapping

Projections are keyed to the **upcoming game_id** (not the last completed game):
- Feature builder computes features from completed games
- Projection model looks up each player's next upcoming game via team roster
- API joins projections to edges by `(player_id, game_id)` ensuring consistency

**Fallback:** < 300 training rows → v1 weighted-average formula.

---

## 3. Simulation Distributions (v2)

**File:** `backend/models/simulation_engine.py`

| Stat | v1 | v2 |
|------|----|----|
| Points | Normal | **Log-normal** (right-skewed, bounded at 0) |
| Rebounds | Normal | **Negative Binomial** (count data, overdispersed) |
| Assists | Normal | **Negative Binomial** (count data, overdispersed) |

**Combo props (PRA/PR/PA)** use a **Gaussian copula** with Spearman rank
correlations, applying each stat's proper marginal distribution via PPF inversion.
This correctly captures the correlation structure without forcing normal marginals.

---

## 4. Positional Defense Features

**File:** `backend/models/positional_defense_features.py`

Extends team-level defense adjustments to 5 position groups (PG/SG/SF/PF/C).
Position is inferred from stat ratios (rebounds → big, assists → guard).

Rolling 10-game allowed stats per team per position produce:
`defense_vs_pg`, `defense_vs_sg`, `defense_vs_sf`, `defense_vs_pf`, `defense_vs_c`,
`positional_defense_adj_pts/reb/ast` (clamped to [0.75, 1.30])

---

## 5. Injury & Lineup Context

**File:** `backend/ingestion/injury_lineup_ingestor.py`
**New tables:** `player_injuries`, `starting_lineups`

Fetches from ESPN public API. When a key teammate is Out/Doubtful,
usage is redistributed to active teammates (capped at +20% per player).

---

## 6. Backtesting Framework

**File:** `scripts/backtest_model.py`
**New table:** `model_backtests`

Compares model probabilities against actual outcomes. Metrics:
Brier Score, Log Loss, Hit Rate, ROI (at -110), Expected Calibration Error.

```bash
python scripts/backtest_model.py
python scripts/backtest_model.py --stat points --threshold 0.60 --calibration
```

---

## 7. Incremental Pipeline

`build_player_features(incremental=True)` — only processes new game_ids,
uses `INSERT OR REPLACE`. Full rebuild: `python scripts/build_features.py --full`.

---

## Pipeline (v2)

```bash
python scripts/ingest_nba.py --season 2025-26
python scripts/build_features.py           # incremental by default
python scripts/run_projections.py          # ML models with fallback
python scripts/simulate_props.py           # lognormal/negbin/copula
python scripts/calculate_edges.py
python scripts/backtest_model.py
```

## Fallback Chain

```
LightGBM minutes  →(< 200 rows)→  heuristic formula
LightGBM stats    →(< 300 rows)→  weighted average + context adjustments
Copula/negbin     →(fit failure)→  independent normal draws
Positional def    →(no data)→     team-level adjustments
Injury context    →(API down)→    neutral multipliers
```
