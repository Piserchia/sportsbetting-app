# Database Schema

**Engine:** DuckDB (embedded)
**Location:** `data/sportsbetting.db`
**Schema init:** `backend/db/connection.py` → `init_schema()` + `init_model_schema()`

---

## Core Data Tables

### teams
| Column | Type | Notes |
|--------|------|-------|
| **team_id** | INTEGER | **PK** |
| full_name | VARCHAR | e.g., "Los Angeles Lakers" |
| abbreviation | VARCHAR | e.g., "LAL" |
| nickname | VARCHAR | e.g., "Lakers" |
| city | VARCHAR | |
| state | VARCHAR | |
| conference | VARCHAR | |
| division | VARCHAR | |
| updated_at | TIMESTAMP | DEFAULT current_timestamp |

### players
| Column | Type | Notes |
|--------|------|-------|
| **player_id** | INTEGER | **PK** |
| full_name | VARCHAR | |
| first_name | VARCHAR | |
| last_name | VARCHAR | |
| is_active | BOOLEAN | |
| updated_at | TIMESTAMP | DEFAULT current_timestamp |

### games
| Column | Type | Notes |
|--------|------|-------|
| **game_id** | VARCHAR | **PK** (e.g., "0022500953") |
| season | VARCHAR | e.g., "2024-25" |
| game_date | DATE | |
| home_team_id | INTEGER | FK → teams |
| away_team_id | INTEGER | FK → teams |
| home_team_abbr | VARCHAR | |
| away_team_abbr | VARCHAR | |
| home_score | INTEGER | NULL if upcoming |
| away_score | INTEGER | NULL if upcoming |
| status | VARCHAR | 'Final', 'Live', 'Upcoming' |
| updated_at | TIMESTAMP | DEFAULT current_timestamp |

### player_game_stats
| Column | Type | Notes |
|--------|------|-------|
| **stat_id** | VARCHAR | **PK** (game_id + player_id) |
| game_id | VARCHAR | |
| player_id | INTEGER | |
| team_id | INTEGER | |
| season | VARCHAR | |
| min | VARCHAR | e.g., "34:22" |
| pts | INTEGER | |
| reb | INTEGER | |
| ast | INTEGER | |
| stl | INTEGER | |
| blk | INTEGER | |
| tov | INTEGER | |
| fgm, fga | INTEGER | |
| fg_pct | DOUBLE | |
| fg3m, fg3a | INTEGER | |
| fg3_pct | DOUBLE | |
| ftm, fta | INTEGER | |
| ft_pct | DOUBLE | |
| plus_minus | INTEGER | |
| updated_at | TIMESTAMP | DEFAULT current_timestamp |

### team_game_stats
| Column | Type | Notes |
|--------|------|-------|
| **stat_id** | VARCHAR | **PK** (game_id + team_id) |
| game_id | VARCHAR | |
| team_id | INTEGER | |
| season | VARCHAR | |
| is_home | BOOLEAN | |
| *(same stat columns as player_game_stats)* | | |
| updated_at | TIMESTAMP | DEFAULT current_timestamp |

### odds
| Column | Type | Notes |
|--------|------|-------|
| **odds_id** | VARCHAR | **PK** (game_id + bookmaker + market) |
| game_id | VARCHAR | |
| bookmaker | VARCHAR | |
| market | VARCHAR | 'h2h', 'spreads', 'totals' |
| home_price | DOUBLE | Moneyline or spread price |
| away_price | DOUBLE | |
| home_point | DOUBLE | Spread or total line |
| away_point | DOUBLE | |
| fetched_at | TIMESTAMP | DEFAULT current_timestamp |

### ingestion_log
| Column | Type | Notes |
|--------|------|-------|
| **log_id** | VARCHAR | **PK** |
| source | VARCHAR | 'nba_api', 'odds_api', 'sportsgameodds' |
| entity | VARCHAR | 'games', 'players', 'props', etc. |
| records_written | INTEGER | |
| status | VARCHAR | 'success', 'error', 'skipped' |
| message | VARCHAR | |
| ran_at | TIMESTAMP | DEFAULT current_timestamp |

---

## Model Pipeline Tables

### player_game_logs
| Column | Type | Notes |
|--------|------|-------|
| **game_id** | TEXT | **PK** (composite with player_id) |
| **player_id** | TEXT | **PK** |
| game_date | DATE | |
| team | TEXT | |
| minutes | DOUBLE | |
| points | DOUBLE | |
| rebounds | DOUBLE | |
| assists | DOUBLE | |
| steals | DOUBLE | |
| blocks | DOUBLE | |
| turnovers | DOUBLE | |
| fg_attempts | DOUBLE | |
| three_attempts | DOUBLE | |
| free_throw_attempts | DOUBLE | |

### player_features
| Column | Type | Notes |
|--------|------|-------|
| **game_id** | TEXT | **PK** (composite with player_id) |
| **player_id** | TEXT | **PK** |
| points_avg_last_5 | DOUBLE | Rolling averages |
| points_avg_last_10 | DOUBLE | |
| rebounds_avg_last_5 | DOUBLE | |
| rebounds_avg_last_10 | DOUBLE | |
| assists_avg_last_5 | DOUBLE | |
| assists_avg_last_10 | DOUBLE | |
| season_avg_points | DOUBLE | |
| season_avg_rebounds | DOUBLE | |
| season_avg_assists | DOUBLE | |
| steals_avg_last_5 | DOUBLE | |
| steals_avg_last_10 | DOUBLE | |
| blocks_avg_last_5 | DOUBLE | |
| blocks_avg_last_10 | DOUBLE | |
| season_avg_steals | DOUBLE | |
| season_avg_blocks | DOUBLE | |
| minutes_avg_last_5 | DOUBLE | Minutes model |
| minutes_avg_last_10 | DOUBLE | |
| minutes_trend | DOUBLE | |
| games_started_last_5 | INTEGER | |
| minutes_projection | DOUBLE | |
| blowout_risk | VARCHAR | NONE/LOW_RISK/MODERATE_RISK/HIGH_RISK |
| blowout_adjustment_factor | DOUBLE | |
| team_pace | DOUBLE | Pace context |
| opponent_pace | DOUBLE | |
| expected_game_pace | DOUBLE | |
| pace_adjustment_factor | DOUBLE | |
| opponent_points_allowed | DOUBLE | Defense context |
| opponent_rebounds_allowed | DOUBLE | |
| opponent_assists_allowed | DOUBLE | |
| defense_adj_pts | DOUBLE | |
| defense_adj_reb | DOUBLE | |
| defense_adj_ast | DOUBLE | |
| opponent_steals_allowed | DOUBLE | |
| opponent_blocks_allowed | DOUBLE | |
| defense_adj_stl | DOUBLE | |
| defense_adj_blk | DOUBLE | |
| usage_proxy | DOUBLE | Usage context |
| usage_trend_last_5 | DOUBLE | |
| positional_defense_adj_pts | DOUBLE | Positional defense |
| positional_defense_adj_reb | DOUBLE | |
| positional_defense_adj_ast | DOUBLE | |
| defense_vs_pg | DOUBLE | |
| defense_vs_sg | DOUBLE | |
| defense_vs_sf | DOUBLE | |
| defense_vs_pf | DOUBLE | |
| defense_vs_c | DOUBLE | |
| player_position | VARCHAR | |
| team_off_rating | DOUBLE | Advanced ratings |
| opponent_def_rating | DOUBLE | |
| rating_matchup_factor | DOUBLE | |
| usage_delta_teammate_out | DOUBLE | Lineup impact |
| assist_delta_teammate_out | DOUBLE | |
| rebound_delta_teammate_out | DOUBLE | |

### player_projections
| Column | Type | Notes |
|--------|------|-------|
| **game_id** | TEXT | **PK** (composite with player_id) |
| **player_id** | TEXT | **PK** |
| points_mean | DOUBLE | |
| rebounds_mean | DOUBLE | |
| assists_mean | DOUBLE | |
| steals_mean | DOUBLE | |
| blocks_mean | DOUBLE | |
| minutes_projection | DOUBLE | |

### player_distributions
| Column | Type | Notes |
|--------|------|-------|
| **game_id** | TEXT | **PK** (composite) |
| **player_id** | TEXT | **PK** |
| **stat** | TEXT | **PK** — 'points', 'rebounds', 'assists', 'steals', 'blocks' |
| mean | DOUBLE | |
| std_dev | DOUBLE | |

### player_simulations
| Column | Type | Notes |
|--------|------|-------|
| **game_id** | TEXT | **PK** (composite) |
| **player_id** | TEXT | **PK** |
| **stat** | TEXT | **PK** — individual or combo stat |
| **line** | DOUBLE | **PK** — half-point values (e.g., 24.5) |
| probability | DOUBLE | P(stat >= line) from 10k Monte Carlo sims |

### prop_edges
| Column | Type | Notes |
|--------|------|-------|
| **game_id** | TEXT | **PK** (composite) |
| **player_id** | TEXT | **PK** |
| **stat** | TEXT | **PK** |
| **line** | DOUBLE | **PK** |
| **book** | TEXT | **PK** — 'draftkings', 'fanduel', or 'model_only' |
| sportsbook_odds | DOUBLE | American odds (NULL if model_only) |
| model_probability | DOUBLE | |
| fair_odds | DOUBLE | What the line should pay |
| expected_value | DOUBLE | Profit per $1 wagered (NULL if model_only) |
| edge_percent | DOUBLE | (model_prob - implied_prob) * 100 |

---

## Sportsbook Tables

### sportsbook_props
| Column | Type | Notes |
|--------|------|-------|
| **prop_id** | TEXT | **PK** (game_id + player_id + stat + line + book) |
| game_id | TEXT | |
| player_id | TEXT | |
| sgo_player_id | TEXT | |
| player_name | TEXT | |
| stat | TEXT | |
| line | DOUBLE | Half-point values |
| over_odds | DOUBLE | American odds |
| under_odds | DOUBLE | American odds |
| book | TEXT | |
| market | TEXT | |
| is_alternate | BOOLEAN | |
| fetched_at | TIMESTAMP | DEFAULT current_timestamp |

*Rebuilt from `prop_line_history` on each fetch — latest snapshot only.*

### prop_line_history
| Column | Type | Notes |
|--------|------|-------|
| **history_id** | TEXT | **PK** (md5 hash) |
| fetched_at | TIMESTAMP | |
| book | TEXT | |
| player_id | TEXT | |
| player_name | TEXT | |
| game_id | TEXT | |
| stat | TEXT | |
| line | DOUBLE | |
| over_odds | DOUBLE | |
| under_odds | DOUBLE | |

*Append-only. Never deleted. Used for CLV tracking.*

---

## Tracking & Context Tables

### bet_results
| Column | Type | Notes |
|--------|------|-------|
| **bet_id** | TEXT | **PK** |
| player_id | TEXT | |
| game_id | TEXT | |
| stat | TEXT | |
| line | DOUBLE | |
| direction | TEXT | 'over' or 'under' |
| model_probability | DOUBLE | |
| book_odds | DOUBLE | |
| closing_line | DOUBLE | |
| actual_value | DOUBLE | |
| result | TEXT | 'win', 'loss', 'push' |
| profit | DOUBLE | |
| brier_score | DOUBLE | |
| created_at | TIMESTAMP | DEFAULT current_timestamp |

### player_injuries
| Column | Type | Notes |
|--------|------|-------|
| **injury_id** | TEXT | **PK** |
| player_id | TEXT | |
| player_name | TEXT | |
| team_abbr | TEXT | |
| status | TEXT | 'Out', 'Doubtful', 'Questionable', 'Probable' |
| injury_type | TEXT | |
| report_date | DATE | |
| game_id | TEXT | |
| source | TEXT | |
| fetched_at | TIMESTAMP | DEFAULT current_timestamp |

### starting_lineups
| Column | Type | Notes |
|--------|------|-------|
| **lineup_id** | TEXT | **PK** |
| game_id | TEXT | |
| team_id | INTEGER | |
| player_id | TEXT | |
| is_starter | BOOLEAN | |
| position | TEXT | |
| report_date | DATE | |
| source | TEXT | |
| fetched_at | TIMESTAMP | DEFAULT current_timestamp |

### model_backtests
| Column | Type | Notes |
|--------|------|-------|
| **backtest_id** | TEXT | **PK** |
| run_date | TEXT | |
| model_version | TEXT | |
| stat | TEXT | |
| line | DOUBLE | |
| n_predictions | INTEGER | |
| hit_rate | DOUBLE | |
| brier_score | DOUBLE | |
| log_loss | DOUBLE | |
| roi | DOUBLE | |
| avg_edge | DOUBLE | |
| created_at | TEXT | |

### team_advanced_stats
| Column | Type | Notes |
|--------|------|-------|
| **game_id** | TEXT | **PK** (composite with team_id) |
| **team_id** | INTEGER | **PK** |
| off_rating | DOUBLE | |
| def_rating | DOUBLE | |
| pace | DOUBLE | |
| possessions | DOUBLE | |

### player_onoff_splits
| Column | Type | Notes |
|--------|------|-------|
| **player_id** | TEXT | **PK** (composite) |
| **teammate_id** | TEXT | **PK** |
| **stat** | TEXT | **PK** |
| mean_with | DOUBLE | |
| mean_without | DOUBLE | |
| delta | DOUBLE | |
| sample_size | INTEGER | |
