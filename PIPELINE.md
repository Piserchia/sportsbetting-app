# Pipeline Execution Order

Orchestrated by `scripts/run_pipeline.py`, which calls stage modules in `backend/pipeline/stages/`. Each step depends on the previous.

## Ingestion Phase

| Step | Function | Script | Stage Module | Tables Written | Purpose |
|------|----------|--------|-------------|---------------|---------|
| 1 | `ingest_teams()` | `ingest_nba.py` | `stage_01_ingestion` | `teams` | Static NBA team roster (30 teams) |
| 2 | `ingest_players()` | `ingest_nba.py` | `stage_01_ingestion` | `players` | All NBA players (active/inactive) |
| 3 | `ingest_games()` | `ingest_nba.py` | `stage_01_ingestion` | `games` | Completed game results via LeagueGameLog |
| 4 | `ingest_schedule()` | `ingest_nba.py` | `stage_01_ingestion` | `games` | Full season schedule (upcoming + status updates) |
| 5 | `ingest_box_scores(season)` | `ingest_nba.py` | `stage_01_ingestion` | `player_game_stats`, `team_game_stats` | Per-player/team box scores (1 API call per game, slow) |
| 6 | `ingest_odds()` | `ingest_odds.py` | `stage_01_ingestion` | `odds` | Pre-game moneylines, spreads, totals |
| 7 | `ingest_props()` | `ingest_props.py` | `stage_01_ingestion` | `prop_line_history`, `sportsbook_props` | Player prop lines from SportsGameOdds (today's games only) |
| 8 | `ingest_injuries_and_lineups()` | — | `stage_01_ingestion` | `player_injuries`, `starting_lineups` | Injury reports + confirmed starters |

## Model Phase

| Step | Function | Script | Stage Module | Tables Written | Purpose |
|------|----------|--------|-------------|---------------|---------|
| 9 | `sync_game_logs()` | `build_features.py` | `stage_02_game_logs` | `player_game_logs` | Normalize box scores into clean game log format |
| 10 | `build_player_features()` | `build_features.py` | `stage_03_features` | `player_features`, `player_stat_posteriors` | 50+ EWMA/context features per (game, player) — all features exclude current game (no leakage); `*_recent_adj` = EWMA + regression-to-mean clipping; `*_posterior` = Bayesian shrinkage toward position-group priors (k=20) |
| 11 | `generate_projections()` | `run_projections.py` | `stage_04_projections` | `player_projections`, `player_distributions`, `projection_explanations`, `model_feature_importance` | LightGBM stat predictions keyed to upcoming game_ids + distribution params + SHAP explanations; feature importance persisted to DB per (stat, position_group); `generated_at` timestamp set on all projections |
| 12 | `simulate_player_props()` | `simulate_props.py` | `stage_06_simulations` | `player_simulations` | 10k Monte Carlo sims with minutes-conditioned variance → P(stat >= line). Minutes drawn from Normal(proj, 18% CV) with projection-relative clamp [65%-135%]. Mean fixed from LightGBM; only std scaled by sqrt(min_sim/min_proj). Post-simulation validation checks run automatically. |
| 13 | `calculate_edges()` | `calculate_edges.py` | `stage_06_edges` / `stage_07_edges` | `prop_edges`, `model_recommendations` | Compare model probability vs sportsbook implied probability; logs qualifying edges as tracked bets in `model_recommendations` |

## Bet Result Resolution

| Script | Tables Written | Purpose |
|--------|---------------|---------|
| `scripts/update_bet_results.py` | `model_recommendations` | Resolves pending bets by comparing recommended lines against actual box score stats; updates `actual_stat`, `result`, `closing_line`, `closing_odds` |

## NBA Data Integrity Guard

`ingest_box_scores()` enforces two conditions before fetching any game's box score:

1. **`status = 'Final'`** — only completed games are eligible
2. **`game_date < today`** — same-day games are excluded even if they appear Final (prevents live or partially-completed data from entering `player_game_stats`)

Games are skipped for these logged reasons:
- `game_not_final` — status is Live or Upcoming
- `game_today` — game_date is today or later
- `already_ingested` — player stats for this game_id already exist (idempotency guard)

After ingestion, a safety check queries for any `player_game_stats` rows joined to non-Final games. If found, a `DATA INTEGRITY WARNING` is logged. This prevents mid-game stats (partial minutes, low shot counts) from corrupting rolling-average features and LightGBM training targets.

## Scheduling (via `--schedule` flag)

- **Daily at 6:00 AM:** Full pipeline (steps 1-13)
- **Every 2 hours:** Odds refresh only (step 6)
- **4x daily (6am, 12pm, 4pm, 7pm):** Props refresh (step 7) with 60-min cooldown

## Running

```bash
# Full pipeline (one-shot)
python scripts/run_pipeline.py

# With scheduling
python scripts/run_pipeline.py --schedule

# Individual steps
python scripts/ingest_nba.py
python scripts/ingest_props.py
python scripts/build_features.py
python scripts/run_projections.py
python scripts/simulate_props.py
python scripts/calculate_edges.py
```
