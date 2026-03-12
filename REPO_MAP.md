# Repository Map

```
sportsbetting-app/
│
├── backend/
│   ├── ingestion/
│   │   ├── nba_ingestor.py          # Teams, players, games, box scores from nba_api
│   │   ├── props_ingestor.py        # Player prop lines from SportsGameOdds API v2
│   │   ├── odds_ingestor.py         # Game odds (ML/spread/total) from The Odds API
│   │   ├── game_log_sync.py         # Normalize box scores → player_game_logs
│   │   └── injury_lineup_ingestor.py # Injury reports + starting lineups
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
│   │   ├── feature_builder.py       # Orchestrates all feature groups → player_features
│   │   ├── projection_model.py      # LightGBM stat projections → player_projections
│   │   ├── stat_models.py           # Position-specific LightGBM models
│   │   ├── simulation_engine.py     # Monte Carlo (Gamma/NegBin/Copula) → player_simulations
│   │   ├── game_simulator.py        # Game-level correlated simulation
│   │   ├── minutes_model.py         # LightGBM minutes projection
│   │   ├── minutes_model_trainer.py # Minutes model training script
│   │   ├── clv_tracker.py           # Closing Line Value + bet result tracking
│   │   ├── pace_features.py         # Pace context (duplicate of features/)
│   │   ├── defense_features.py      # Defense context (duplicate of features/)
│   │   ├── advanced_defense_features.py  # Off/def ratings per game
│   │   ├── positional_defense_features.py # Defense by position
│   │   ├── usage_features.py        # Usage proxy (duplicate of features/)
│   │   └── lineup_features.py       # Lineup impact (duplicate of features/)
│   │
│   ├── api/
│   │   └── app.py                   # FastAPI server (all REST endpoints)
│   │
│   ├── db/
│   │   └── connection.py            # DuckDB connection + schema init (21 tables)
│   │
│   └── analysis/
│       └── queries.py               # Reusable analytical SQL queries
│
├── scripts/
│   ├── run_pipeline.py              # Full pipeline orchestrator (scheduling support)
│   ├── ingest_nba.py                # CLI: NBA data ingestion
│   ├── ingest_odds.py               # CLI: Odds ingestion
│   ├── ingest_props.py              # CLI: Props ingestion
│   ├── build_features.py            # CLI: Feature engineering
│   ├── run_projections.py           # CLI: ML projections
│   ├── simulate_props.py            # CLI: Monte Carlo simulations
│   ├── calculate_edges.py           # CLI: Edge detection
│   ├── backtest_model.py            # Model backtesting (Brier, log loss, hit rate)
│   ├── track_clv.py                 # CLV evaluation
│   ├── train_minutes_model.py       # Minutes model training
│   ├── init_db.py                   # Database schema initialization
│   └── start_api.py                 # Start FastAPI server
│
├── frontend/
│   └── src/
│       ├── main.jsx                 # React entry point
│       └── components/
│           ├── PropDashboard.jsx     # Player search, props, simulations, edges
│           ├── EdgesDashboard.jsx    # Best +EV edges across today's slate
│           └── PipelineStatus.jsx    # Pipeline monitoring dashboard
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
├── CLAUDE.md                        # Rules for AI assistants
├── AI_TASK_TEMPLATE.md              # Template for AI task prompts
├── PROJECT_CONTEXT.md               # Detailed project context
├── MODEL_ARCHITECTURE_V2.md         # PropModel v2 specifications
├── README.md                        # Setup and usage
└── requirements.txt                 # Python dependencies
```
