# Repository Map

```
sportsbetting-app/
│
├── backend/
│   ├── data_sources/
│   │   ├── nba/
│   │   │   ├── nba_ingestor.py          # Teams, players, games, box scores from nba_api
│   │   │   └── game_log_sync.py         # Normalize box scores → player_game_logs
│   │   ├── sportsbooks/
│   │   │   ├── props_ingestor.py        # Player prop lines from SportsGameOdds API v2
│   │   │   └── odds_ingestor.py         # Game odds (ML/spread/total) from The Odds API
│   │   └── injuries/
│   │       └── injury_lineup_ingestor.py # Injury reports + starting lineups
│   │
│   ├── features/
│   │   ├── rolling_stats.py         # L5/L10/season rolling averages
│   │   ├── minutes_features.py      # Minutes projection, blowout risk
│   │   ├── pace_features.py         # Team/opponent pace context
│   │   ├── defense_features.py      # Opponent defensive strength
│   │   ├── usage_features.py        # Usage rate proxy and trend
│   │   └── lineup_features.py       # Teammate on/off impact
│   │
│   ├── models/
│   │   ├── bayesian_shrinkage.py    # Hierarchical Bayesian shrinkage → player_stat_posteriors
│   │   ├── feature_builder.py       # Orchestrates all feature groups → player_features
│   │   ├── clv_tracker.py           # Closing Line Value + bet result tracking
│   │   ├── edges_query.py           # Edge aggregation queries
│   │   ├── advanced_defense_features.py  # Off/def ratings per game
│   │   ├── positional_defense_features.py # Defense by position
│   │   ├── pace_features.py         # Pace context (duplicate of features/)
│   │   ├── defense_features.py      # Defense context (duplicate of features/)
│   │   ├── usage_features.py        # Usage proxy (duplicate of features/)
│   │   ├── lineup_features.py       # Lineup impact (duplicate of features/)
│   │   ├── minutes_model/
│   │   │   ├── minutes_model.py         # LightGBM minutes projection
│   │   │   └── minutes_model_trainer.py # Minutes model training script
│   │   └── stat_models/
│   │       ├── stat_models.py           # Position-specific LightGBM models
│   │       └── projection_model.py      # LightGBM stat projections → player_projections
│   │
│   ├── pipeline/
│   │   ├── stages/
│   │   │   ├── stage_01_ingestion.py    # NBA data + odds + props ingestion
│   │   │   ├── stage_02_game_logs.py    # Game log sync
│   │   │   ├── stage_03_features.py     # Feature engineering
│   │   │   ├── stage_04_projections.py  # ML projections
│   │   │   ├── stage_05_simulations.py  # Monte Carlo simulations
│   │   │   ├── stage_06_edges.py        # Edge detection
│   │   │   └── stage_07_edges.py        # Edge post-processing / aggregation
│   │   └── simulations/
│   │       ├── simulation_engine.py     # Monte Carlo (Gamma/NegBin/Copula) → player_simulations
│   │       ├── simulation_validation.py # Post-simulation sanity checks (mean drift, std bounds, tail checks)
│   │       └── game_simulator.py        # Game-level correlated simulation (experimental, unused)
│   │
│   ├── contracts/
│   │   ├── database_schema.yaml     # Database table schema contracts
│   │   ├── feature_schema.yaml      # Feature engineering output contracts
│   │   └── projection_schema.yaml   # Projection output contracts
│   │
│   ├── api/
│   │   └── app.py                   # FastAPI server (all REST endpoints + projection explanations + bet analytics by type/position)
│   │
│   ├── database/
│   │   ├── connection.py            # DuckDB connection + schema init (26 tables)
│   │   └── SCHEMA.md               # Database schema documentation
│   │
│   ├── analysis/
│   │   ├── queries.py               # Reusable analytical SQL queries
│   │   └── calibration.py           # Probability calibration evaluation (bucket hit rates)
│   │
│   ├── ingestion/                   # (compat shim — re-exports from data_sources/)
│   │
│   ├── db/                          # (compat shim — re-exports from database/)
│   │
│   └── __init__.py
│
├── scripts/
│   ├── run_pipeline.py              # Full pipeline orchestrator (calls stage modules)
│   ├── ingest_nba.py                # CLI: NBA data ingestion
│   ├── ingest_odds.py               # CLI: Odds ingestion
│   ├── ingest_props.py              # CLI: Props ingestion
│   ├── build_features.py            # CLI: Feature engineering
│   ├── run_projections.py           # CLI: ML projections
│   ├── simulate_props.py            # CLI: Monte Carlo simulations
│   ├── calculate_edges.py           # CLI: Edge detection
│   ├── backtest_model.py            # Model backtesting (Brier, log loss, hit rate)
│   ├── track_clv.py                 # CLV evaluation
│   ├── update_bet_results.py        # Resolve pending bets against actual game results
│   ├── train_minutes_model.py       # Minutes model training
│   ├── init_db.py                   # Database schema initialization
│   └── start_api.py                 # Start FastAPI server
│
├── frontend/
│   └── src/
│       ├── main.jsx                 # React entry point
│       └── components/
│           ├── PropDashboard.jsx     # Player search, props, simulations, edges
│           ├── ProjectionDebugger.jsx # SHAP feature contribution explainer
│           ├── PipelineExplorer.jsx  # Visual pipeline education page
│           ├── EdgesDashboard.jsx    # Best +EV edges across today's slate
│           ├── PipelineStatus.jsx    # Pipeline monitoring dashboard
│           ├── BetPerformanceDashboard.jsx # Bet tracking: performance cards, recent bets, model comparison
│           ├── ModelHealthDashboard.jsx # Model health monitoring and diagnostics
│           └── EdgesDashboard2.jsx  # Alternate edges dashboard view
│
├── config/
│   ├── .env                         # API keys, DB path, ingestion settings
│   ├── .env.example                 # Template
│   └── logging_config.py            # Colored logging setup
│
├── data/
│   └── sportsbetting.db             # DuckDB database (gitignored)
│
├── AI_CONTEXT.md                    # System architecture overview (start here)
├── REPO_MAP.md                      # This file
├── PIPELINE.md                      # Pipeline execution order
├── ARCHITECTURE_SNAPSHOT.md         # Detailed architecture reference
├── CLAUDE.md                        # Rules for AI assistants
├── AI_TASK_TEMPLATE.md              # Template for AI task prompts
├── PROJECT_CONTEXT.md               # Detailed project context
├── MODEL_ARCHITECTURE_V2.md         # PropModel v2 specifications
├── README.md                        # Setup and usage
└── requirements.txt                 # Python dependencies
```
