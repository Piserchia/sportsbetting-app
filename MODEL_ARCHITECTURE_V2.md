# PropModel — Architecture v2

## What Changed

Version 2 replaces every heuristic in the prediction pipeline with trained ML models and statistically-appropriate distributions. The data pipeline and API are unchanged.

---

## 1. Minutes Model (LightGBM)

**File:** `backend/models/minutes_model.py`

The heuristic formula `0.5×L10 + 0.3×L5 + 0.2×trend` is replaced with a LightGBM regressor trained on historical minutes data. The model learns which features actually predict playing time rather than using fixed weights.

**Training:** Fit on all completed games in `player_game_logs` where actual minutes > 0 (DNPs excluded). Requires ≥ 200 training rows; falls back to heuristic otherwise.

**Features:**
| Feature | Description |
|---|---|
| `minutes_l5` | Rolling 5-game average minutes |
| `minutes_l10` | Rolling 10-game average minutes |
| `minutes_trend` | Linear slope over last 10 games |
| `games_started` | Games started in last 5 (proxy: mins ≥ 28) |
| `spread` | Absolute sportsbook spread for the game |
| `pace` | Average team points allowed (pace proxy) |
| `is_home` | 1 if player's team is home |
| `days_rest` | Days since last game (capped at 10) |
| `back_to_back` | 1 if days_rest ≤ 1 |

**Blowout adjustment:** Applied post-prediction — spread ≥ 10 → ×0.92, spread ≥ 15 → ×0.85.

---

## 2. ML Stat Projections (LightGBM)

**File:** `backend/models/stat_models.py`

Three independent LightGBM models — one each for points, rebounds, and assists. Each model is trained on `player_features` joined with actual outcomes from `player_game_logs`, using early stopping to prevent overfitting.

**Algorithm:** LightGBM with MAE objective (`regression_l1`), 400 rounds, early stopping at 40.

**Training data:** All completed games in `player_features` × `player_game_logs`. Minimum 300 rows required; falls back to heuristic weighted average otherwise.

**Features per model:**

*Points:* `minutes_projection`, `usage_proxy`, `usage_trend_last_5`, rolling pts (L5/L10/season), `pace_adjustment_factor`, `defense_adj_pts`, `spread`, `team_total`, `is_home`, `days_rest`, `is_back_to_back`, `games_started_last_5`

*Rebounds:* Same minus `usage_trend_last_5`, `team_total` — uses `defense_adj_reb`

*Assists:* Same as points minus `games_started_last_5` — uses `defense_adj_ast`

**Model cache:** Models are cached in-memory for the duration of a pipeline run. Call `reset_stat_models()` to force retraining.

---

## 3. Improved Simulation Distributions

**File:** `backend/models/simulation_engine.py`

### Points → Lognormal

Points are right-skewed (you can score 50, you can't score -10). The lognormal distribution matches this naturally.

```
mu    = log(mean) - σ²/2
sigma = sqrt(log(1 + variance/mean²))
sim   ~ LogNormal(mu, sigma)
```

### Rebounds & Assists → Negative Binomial

Both are non-negative count statistics with overdispersion (variance > mean). The negative binomial is the canonical distribution for overdispersed count data.

```
n = mean² / (variance - mean)
p = n / (n + mean)
λ ~ Gamma(n, (1-p)/p)     # gamma-Poisson mixture for speed
sim ~ Poisson(λ)
```

Falls back to normal if variance ≤ mean (rare for NBA players with sufficient history).

### Combo Props → Correlated Multivariate Normal

PRA, PR, PA still use the correlated multivariate normal draw to preserve statistical correlation between the three stats. The covariance matrix is computed per-player from historical game logs and enforced positive semi-definite via eigenvalue clipping.

---

## 4. Positional Defense Features

**File:** `backend/models/positional_defense.py`

Supplements team-level defensive adjustments with position-group-specific adjustments.

**Position groups:**
- `GUARD`: PG, SG, G, G-F
- `FORWARD`: SF, PF, F, F-G, F-C (default)
- `CENTER`: C, C-F

**Method:** For each defending team, computes rolling 10-game averages of pts/reb/ast allowed to each position group. Divides by league average for that position group to produce an adjustment factor, clamped to [0.75, 1.30].

**Output columns added to `player_features`:**
- `pos_defense_adj_pts` — position-specific defensive multiplier for points
- `pos_defense_adj_reb` — position-specific defensive multiplier for rebounds
- `pos_defense_adj_ast` — position-specific defensive multiplier for assists
- `position_group` — GUARD / FORWARD / CENTER

These are passed as features to the LightGBM stat models.

---

## 5. Distribution Improvement: Recent-Form Std Dev

**File:** `backend/models/projection_model.py` (`build_distributions`)

Standard deviations are now computed as a weighted blend of recent variance (last 20 games) and full-season variance:

```
std = 0.6 × recent_std (last 20 games) + 0.4 × full_season_std
```

This makes the distribution width more responsive to current form — a player who has been consistent recently will have a tighter distribution even if they were volatile early in the season.

---

## 6. Backtesting Framework

**File:** `scripts/backtest_model.py`

Evaluates model accuracy by comparing predicted probabilities against binary outcomes (did the player hit the line?).

**Metrics:**
- **Brier Score** — mean squared error between predicted prob and outcome. Lower = better. A naive model predicting the base rate scores ~0.25; a good model scores < 0.20.
- **Log Loss** — cross-entropy. Penalises confident wrong predictions more than uncertain ones.
- **Hit Rate** — fraction of times players exceeded the line.
- **Simulated ROI** — flat-bet ROI at -110 vig, only betting when model edge exceeds 5%.

**Usage:**
```bash
# Full backtest
python scripts/backtest_model.py --season 2025-26

# Single stat
python scripts/backtest_model.py --season 2025-26 --stat points

# With calibration report
python scripts/backtest_model.py --season 2025-26 --calibration
```

Results written to `model_backtests` table.

---

## 7. Pipeline Execution (Updated)

```bash
# Data ingestion (incremental)
python scripts/ingest_nba.py --season 2025-26

# Feature pipeline (full rebuild each run)
python scripts/build_features.py       # includes positional defense

# ML projections (trains + predicts in one pass)
python scripts/run_projections.py      # LightGBM minutes + stat models

# Simulation (lognormal/negbinom distributions)
python scripts/simulate_props.py

# Edge detection
python scripts/calculate_edges.py

# Backtesting (run after pipeline)
python scripts/backtest_model.py --season 2025-26 --calibration
```

---

## Model Inputs → Outputs Flow

```
player_game_stats (raw)
        ↓ game_log_sync.py
player_game_logs (normalised)
        ↓ feature_builder.py
player_features (29 columns: rolling stats, pace, defense, positional defense, usage, minutes)
        ↓ stat_models.py (LightGBM × 3)
player_projections (points_mean, rebounds_mean, assists_mean, minutes_projection)
        ↓ projection_model.py → player_distributions (std devs, recent-weighted)
        ↓ simulation_engine.py (lognormal/negbinom/MVN × 10,000)
player_simulations (probability ladders per player per stat per line)
        ↓ calculate_edges.py
prop_edges (model prob vs book implied prob → edge_pct)
        ↓ backtest_model.py
model_backtests (Brier, log loss, ROI per stat per line)
```

---

## Known Remaining Limitations

- No real-time injury or lineup feeds — projections do not update for same-day scratches
- Position data comes from `player_game_stats.position` which is sometimes blank/inconsistent
- LightGBM models retrain on every pipeline run (no model persistence to disk yet)
- Correlation structure in combo props still uses full-history covariance, not recent-form covariance
