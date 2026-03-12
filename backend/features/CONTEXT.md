# Features Module

## Purpose

Sub-modules that compute individual feature groups. Called by `backend/models/feature_builder.py` which orchestrates all groups and writes the final `player_features` table.

## Key Modules

| File | Feature Group | Output Columns |
|------|--------------|---------------|
| `rolling_stats.py` | L5/L10/season averages | `*_avg_last_5`, `*_avg_last_10`, `season_avg_*` |
| `minutes_features.py` | Minutes model | `minutes_projection`, `blowout_risk`, `blowout_adjustment_factor` |
| `pace_features.py` | Pace context | `team_pace`, `opponent_pace`, `pace_adjustment_factor` |
| `defense_features.py` | Opponent defense | `opponent_*_allowed`, `defense_adj_*` |
| `usage_features.py` | Usage proxy | `usage_proxy`, `usage_trend_last_5` |
| `lineup_features.py` | Teammate impact | `*_delta_teammate_out` |

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
- All sub-modules degrade gracefully with defaults if data is missing:
  - Pace → 100.0 (league average)
  - Defense → 110 pts / 44 reb / 25 ast allowed
  - Adjustment factors → 1.0 (no change)
- Note: some feature modules exist in both `backend/features/` and `backend/models/` — the `models/` versions are the ones actively called by `feature_builder.py`
