# SportsBetting App — AI Assistant Guidelines

## Before Modifying Code

1. Read [`AI_CONTEXT.md`](AI_CONTEXT.md) for system architecture
2. Read the relevant module `CONTEXT.md` file
3. Verify database columns in [`backend/database/SCHEMA.md`](backend/database/SCHEMA.md)
4. **Never invent tables or fields** — only use what exists in the schema
5. Update context documentation when architecture changes

## SportsGameOdds API — CONSERVE REQUESTS

**The SGO API key has a limited credit budget. Do NOT make live API calls for debugging.**

Rules:
- Never call `scripts/ingest_props.py` or `fetch_props()` to test/debug API behavior
- Never use `curl` against `api.sportsgameodds.com` to explore the API structure
- To debug props ingestion, inspect existing DB data or use mock/cached responses
- If API structure needs to be verified, ask the user to check the SGO dashboard or docs
- The cooldown (`PROPS_COOLDOWN_MINUTES`) exists precisely to prevent accidental over-calling — respect it

API key is in `config/.env` as `SPORTSGAMEODDS_API_KEY`.

## Documentation Maintenance Policy

**Whenever code changes modify architecture, data flow, or database schema, the relevant context documentation must be updated.**

| Change | Update |
|--------|--------|
| New ingestion source | `backend/data_sources/` (relevant subdirectory) |
| New feature group | `backend/features/CONTEXT.md` + `backend/models/CONTEXT.md` |
| Table schema change | `backend/database/SCHEMA.md` |
| New/changed API endpoint | `backend/api/CONTEXT.md` |
| Pipeline step added/reordered | `PIPELINE.md` |
| Pipeline stage module change | `backend/pipeline/stages/` + `PIPELINE.md` |
| New module or directory | `REPO_MAP.md` + `AI_CONTEXT.md` |
| Simulation line changes | `backend/models/CONTEXT.md` (PROP_LINES) |
| New frontend component | `frontend/CONTEXT.md` |
| Schema contract change | `backend/contracts/` (relevant YAML file) |

## Context Documentation Style

Context files describe **architecture**, not implementation details.

**Do:**
> "This module generates player projections using LightGBM models with heuristic fallback."

**Do not:**
> "This function loops through players and calls `model.predict()` on each row."

Keep context files concise, structured, and accurate. Tables over prose.

## Critical Technical Constraints

- **Prop lines use half-point values** (e.g., 24.5 not 25). `PROP_LINES` in `simulation_engine.py` must match what DraftKings/FanDuel post.
- **Edge calculation requires exact line matching** — `player_simulations.line = sportsbook_props.line`. No interpolation.
- **DuckDB is the database** — not all MySQL/Postgres syntax works. Uses `INSERT OR REPLACE`, `QUALIFY`, window functions.
- **NBA API rate limit:** 3-second delay between calls. Box score ingestion is slow (1 call per game).
