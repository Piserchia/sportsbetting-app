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

Points features include: `minutes_projection`, rolling stats L5/L10/season,
`usage_proxy`, `pace_adjustment_factor`, `defense_adj_pts`, `spread`,
`team_total`, `is_home`, `days_rest`, `is_back_to_back`, `games_started_last_5`.

Rebounds and assists use equivalent stat-appropriate feature sets.

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
