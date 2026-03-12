# AI Task Template

Use this template when prompting AI assistants to modify this codebase.

---

## Context files to read:

```
AI_CONTEXT.md                    # System architecture overview
REPO_MAP.md                      # Repository file structure
PIPELINE.md                      # Pipeline execution order
backend/db/SCHEMA.md             # All 21 database table schemas
backend/<module>/CONTEXT.md      # Relevant module documentation
CLAUDE.md                        # Rules and constraints
```

## Task:

[Describe the feature, bug fix, or change]

## Relevant modules:

[List which modules are involved — ingestion, features, models, api, frontend]

## Constraints:

- Do not change database schema unless necessary
- If schema changes, update `backend/db/SCHEMA.md`
- If pipeline order changes, update `PIPELINE.md`
- If adding new modules/files, update `REPO_MAP.md`
- Do not make live SportsGameOdds API calls for debugging
- Prop lines must use half-point values (e.g., 24.5 not 25)
- Edge calculation requires exact line matching between `player_simulations` and `sportsbook_props`

## Expected output:

[Describe what you expect the AI to produce — code changes, new files, etc.]
