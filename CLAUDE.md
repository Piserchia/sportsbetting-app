# SportsBetting App — Claude Guidelines

## SportsGameOdds API — CONSERVE REQUESTS

**The SGO API key has a limited credit budget. Do NOT make live API calls for debugging.**

Rules:
- Never call `scripts/ingest_props.py` or `fetch_props()` to test/debug API behavior
- Never use `curl` against `api.sportsgameodds.com` to explore the API structure
- To debug props ingestion, inspect existing DB data or use mock/cached responses
- If API structure needs to be verified, ask the user to check the SGO dashboard or docs
- The cooldown (`PROPS_COOLDOWN_MINUTES`) exists precisely to prevent accidental over-calling — respect it

API key is in `config/.env` as `SPORTSGAMEODDS_API_KEY`.
