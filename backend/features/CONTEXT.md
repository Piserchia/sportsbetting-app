# Features Module

## Purpose

Sub-modules that compute individual feature groups. Called by `backend/models/feature_builder.py` which orchestrates all groups and writes the final `player_features` table.

## Key Modules

| File | Feature Group | Output Columns |
|------|--------------|---------------|
| `rolling_stats.py` | EWMA recent adj / L10 / season averages | `*_recent_adj`, `*_avg_last_10`, `season_avg_*` |
| `minutes_features.py` | Minutes model | `minutes_projection`, `blowout_risk`, `blowout_adjustment_factor` |
| `pace_features.py` | Pace context | `team_pace`, `opponent_pace`, `pace_adjustment_factor` |
| `defense_features.py` | Opponent defense | `opponent_*_allowed`, `defense_adj_*` |
| `usage_features.py` | Usage proxy | `usage_proxy`, `usage_trend_last_5` |
| `lineup_features.py` | Teammate impact | `*_delta_teammate_out` |

### Additional Feature Modules (in `backend/models/`)

These modules live in `backend/models/` and are called directly by `feature_builder.py`:

| File | Feature Group | Output Columns |
|------|--------------|---------------|
| `bayesian_shrinkage.py` | Bayesian posteriors | `*_posterior` (k=20 shrinkage toward position-group priors) |
| `positional_defense_features.py` | Positional defense | `defense_vs_pg/sg/sf/pf/c`, `positional_defense_adj_*` |
| `advanced_defense_features.py` | Advanced ratings | `team_off_rating`, `opponent_def_rating`, `rating_matchup_factor` |

## Tables Consumed

- `player_game_logs` (primary input)
- `team_game_stats` (for pace, defense)
- `games` (for opponent/matchup lookup)
- `player_injuries` (for teammate injury multipliers)

## Tables Written

- `player_features` (via feature_builder.py orchestrator)
- `player_onoff_splits` (via lineup_features.py)
- `team_advanced_stats` (via advanced_defense_features.py)

## Important Constraints

- Feature builder supports incremental mode (default) and full rebuild
- **All rolling features exclude the current game** — EWMA, L10, and season averages use only prior games to prevent target leakage during model training
- First game per player has `*_recent_adj = 0.0` (no prior data)
- A leakage guardrail asserts first-game features are zero; raises RuntimeError if violated
- All sub-modules degrade gracefully with defaults if data is missing:
  - Pace → 100.0 (league average)
  - Defense → 110 pts / 44 reb / 25 ast allowed
  - Adjustment factors → 1.0 (no change)
- Note: some feature modules exist in both `backend/features/` and `backend/models/` — the `models/` versions are the ones actively called by `feature_builder.py`
