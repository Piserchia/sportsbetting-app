# Pipeline Execution Order

Orchestrated by `scripts/run_pipeline.py`. Each step depends on the previous.

## Ingestion Phase

| Step | Function | Script | Tables Written | Purpose |
|------|----------|--------|---------------|---------|
| 1 | `ingest_teams()` | `ingest_nba.py` | `teams` | Static NBA team roster (30 teams) |
| 2 | `ingest_players()` | `ingest_nba.py` | `players` | All NBA players (active/inactive) |
| 3 | `ingest_games()` | `ingest_nba.py` | `games` | Completed game results via LeagueGameLog |
| 4 | `ingest_schedule()` | `ingest_nba.py` | `games` | Full season schedule (upcoming + status updates) |
| 5 | `ingest_box_scores(season)` | `ingest_nba.py` | `player_game_stats`, `team_game_stats` | Per-player/team box scores (1 API call per game, slow) |
| 6 | `ingest_odds()` | `ingest_odds.py` | `odds` | Pre-game moneylines, spreads, totals |
| 7 | `ingest_props()` | `ingest_props.py` | `prop_line_history`, `sportsbook_props` | Player prop lines from SportsGameOdds (today's games only) |
| 8 | `ingest_injuries_and_lineups()` | — | `player_injuries`, `starting_lineups` | Injury reports + confirmed starters |

## Model Phase

| Step | Function | Script | Tables Written | Purpose |
|------|----------|--------|---------------|---------|
| 9 | `sync_game_logs()` | `build_features.py` | `player_game_logs` | Normalize box scores into clean game log format |
| 10 | `build_player_features()` | `build_features.py` | `player_features` | 50+ rolling/context features per (game, player) |
| 11 | `generate_projections()` | `run_projections.py` | `player_projections`, `player_distributions` | LightGBM stat predictions + distribution params |
| 12 | `simulate_player_props()` | `simulate_props.py` | `player_simulations` | 10k Monte Carlo sims → P(stat >= line) for each prop line |
| 13 | `calculate_edges()` | `calculate_edges.py` | `prop_edges` | Compare model probability vs sportsbook implied probability |

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
