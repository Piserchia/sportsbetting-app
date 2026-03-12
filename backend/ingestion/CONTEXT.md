# Ingestion Module

## Purpose

Fetch raw data from external APIs and write to DuckDB. All ingestion is idempotent (safe to re-run).

## Key Modules

| File | Data Source | Tables Written |
|------|-----------|---------------|
| `nba_ingestor.py` | nba_api (free) | `teams`, `players`, `games`, `player_game_stats`, `team_game_stats` |
| `props_ingestor.py` | SportsGameOdds API v2 (paid) | `prop_line_history`, `sportsbook_props` |
| `odds_ingestor.py` | The Odds API | `odds` |
| `game_log_sync.py` | Internal (box scores) | `player_game_logs` |
| `injury_lineup_ingestor.py` | ESPN, NBA.com | `player_injuries`, `starting_lineups` |

## External APIs

### nba_api
- Free, no authentication
- Rate limit: 3-second delay between calls (`NBA_API_DELAY`)
- Box score ingestion is slow (1 call per game) — use `limit` for testing
- Retry with exponential backoff (up to 5 attempts)

### SportsGameOdds API v2
- **Endpoint:** `GET /v2/events?leagueID=NBA&startsAfter=today&startsBefore=tomorrow&oddsPresent=true`
- **Authentication:** API key via `apiKey` query param
- **Credit-limited** — never call for debugging
- Odd keys follow format: `{stat}-{PLAYER_ID}-{period}-{market}-{side}`
- Per-book odds in `byBookmaker[bookID]`, alt lines in `byBookmaker[bookID].altLines[]`
- Under odds paired via `opposingOddID`

## Important Constraints

- `PROPS_COOLDOWN_MINUTES=60` prevents accidental over-calling
- Props only fetched for today's games (billing is per-event)
- Default books: DraftKings, FanDuel (configurable via `PROPS_BOOKS` env var)
- Modeled stats: points, rebounds, assists, steals, blocks
- Player matching: exact name → strip suffix (Jr./III) → unique last-name fallback
- `sportsbook_props` is a snapshot rebuilt from `prop_line_history` each fetch
- All operations logged to `ingestion_log`
