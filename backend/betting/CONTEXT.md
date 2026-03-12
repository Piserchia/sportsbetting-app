# Betting Module

## Purpose

Reserved for future bet selection and bankroll management logic. Currently, edge detection lives in `scripts/calculate_edges.py` and bet tracking in `backend/models/clv_tracker.py`.

## Current State

This directory does not yet contain code. Betting-related functionality is currently distributed across:

- **Edge detection:** `scripts/calculate_edges.py` → `prop_edges` table
- **Bet tracking:** `backend/models/clv_tracker.py` → `bet_results` table
- **Edge display:** `backend/api/app.py` → `/edges/today` endpoint

## Tables Related to Betting

- `prop_edges` — Model vs sportsbook comparison (written by `calculate_edges.py`)
- `bet_results` — Historical bet outcomes and performance (written by `clv_tracker.py`)
- `sportsbook_props` — Current sportsbook lines (written by `props_ingestor.py`)
- `prop_line_history` — All historical line snapshots (written by `props_ingestor.py`)
