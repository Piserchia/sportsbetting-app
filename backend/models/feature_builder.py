"""
models/feature_builder.py
Builds all player features from game logs and writes to player_features.

Feature groups:
  - Rolling stat averages (pts/reb/ast L5, L10, season)
  - Improved minutes model (L5, L10, trend, blowout adjustment)
  - Team pace context (team_pace, opponent_pace, pace_adjustment_factor)
  - Opponent defensive strength (pts/reb/ast allowed, defense_adj factors)
  - Usage rate proxy (usage_proxy, usage_trend_last_5)

All feature groups are joined on (game_id, player_id) and written to
player_features as a single wide table. Missing context features
(pace, defense) default to 1.0 adjustment factors so the projection
model degrades gracefully when context data is unavailable.
"""

import uuid
import logging
import pandas as pd
import numpy as np

from backend.database.connection import get_connection, init_model_schema
from backend.models.pace_features    import build_pace_features
from backend.models.defense_features import build_defense_features
from backend.models.minutes_model    import build_minutes_features
from backend.models.usage_features   import build_usage_features
from backend.models.positional_defense_features import build_positional_defense_features
from backend.models.advanced_defense_features import build_advanced_defense_features
from backend.models.lineup_features import build_lineup_features
from backend.data_sources.injuries.injury_lineup_ingestor import get_teammate_injury_multipliers

logger = logging.getLogger(__name__)


def build_player_features(conn=None, incremental: bool = True) -> int:
    """
    Compute all rolling + context features for every player/game combination
    and write to player_features.

    Args:
        incremental: If True, only process game_ids not already in player_features.
                     If False, clears and rebuilds the full table.

    Returns number of rows written.
    """
    close = conn is None
    conn = conn or get_connection()
    # ── 1. Base game logs ────────────────────────────────────────────────────
    logger.info("Loading player_game_logs...")
    logs = conn.execute("""
        SELECT
            pgl.game_id,
            pgl.player_id,
            pgl.game_date,
            pgl.minutes,
            pgl.points,
            pgl.rebounds,
            pgl.assists,
            pgl.steals,
            pgl.blocks,
            pgl.fg_attempts,
            pgl.free_throw_attempts,
            pgl.turnovers
        FROM player_game_logs pgl
        ORDER BY pgl.player_id, pgl.game_date ASC
    """).df()

    # Incremental: skip game_ids already in player_features
    if incremental:
        try:
            existing = conn.execute(
                "SELECT DISTINCT game_id FROM player_features"
            ).df()["game_id"].tolist()
            if existing:
                logs = logs[~logs["game_id"].isin(existing)]
                logger.info(f"  Incremental mode: {len(logs)} new game-log rows to process "
                            f"({len(existing)} game_ids already built)")
                if logs.empty:
                    logger.info("  All games already in player_features — nothing to do.")
                    n_existing = len(existing)
                    conn.execute(
                        "INSERT OR REPLACE INTO ingestion_log VALUES (?,?,?,?,?,?,current_timestamp)",
                        [str(uuid.uuid4()), "feature_builder", "player_features", n_existing, "success", "incremental — up to date"]
                    )
                    if close:
                        conn.close()
                    return 0
        except Exception:
            pass  # table may not exist yet — full build

    if logs.empty:
        logger.warning("No player_game_logs found. Run ingest_nba first.")
        if close:
            conn.close()
        return 0

    n_players = logs["player_id"].nunique()
    logger.info(f"Building features for {n_players} players across {len(logs)} game logs...")

    # ── 2. Rolling stat features ─────────────────────────────────────────────
    logger.info("  Computing rolling stat features...")
    stat_records = []

    for player_id, player_logs in logs.groupby("player_id"):
        player_logs = player_logs.sort_values("game_date").reset_index(drop=True)

        pts  = player_logs["points"]
        reb  = player_logs["rebounds"]
        ast  = player_logs["assists"]
        stl  = player_logs["steals"].fillna(0)
        blk  = player_logs["blocks"].fillna(0)

        points_avg_last_5   = pts.rolling(5,  min_periods=1).mean()
        points_avg_last_10  = pts.rolling(10, min_periods=1).mean()
        rebounds_avg_last_5 = reb.rolling(5,  min_periods=1).mean()
        rebounds_avg_last_10 = reb.rolling(10, min_periods=1).mean()
        assists_avg_last_5  = ast.rolling(5,  min_periods=1).mean()
        assists_avg_last_10 = ast.rolling(10, min_periods=1).mean()
        steals_avg_last_5   = stl.rolling(5,  min_periods=1).mean()
        steals_avg_last_10  = stl.rolling(10, min_periods=1).mean()
        blocks_avg_last_5   = blk.rolling(5,  min_periods=1).mean()
        blocks_avg_last_10  = blk.rolling(10, min_periods=1).mean()
        season_avg_points   = pts.expanding().mean()
        season_avg_rebounds = reb.expanding().mean()
        season_avg_assists  = ast.expanding().mean()
        season_avg_steals   = stl.expanding().mean()
        season_avg_blocks   = blk.expanding().mean()

        for i, row in player_logs.iterrows():
            stat_records.append({
                "game_id":               row["game_id"],
                "player_id":             str(player_id),
                "points_avg_last_5":     round(float(points_avg_last_5.iloc[i]),   4),
                "points_avg_last_10":    round(float(points_avg_last_10.iloc[i]),  4),
                "rebounds_avg_last_5":   round(float(rebounds_avg_last_5.iloc[i]), 4),
                "rebounds_avg_last_10":  round(float(rebounds_avg_last_10.iloc[i]),4),
                "assists_avg_last_5":    round(float(assists_avg_last_5.iloc[i]),  4),
                "assists_avg_last_10":   round(float(assists_avg_last_10.iloc[i]), 4),
                "steals_avg_last_5":     round(float(steals_avg_last_5.iloc[i]),   4),
                "steals_avg_last_10":    round(float(steals_avg_last_10.iloc[i]),  4),
                "blocks_avg_last_5":     round(float(blocks_avg_last_5.iloc[i]),   4),
                "blocks_avg_last_10":    round(float(blocks_avg_last_10.iloc[i]),  4),
                "season_avg_points":     round(float(season_avg_points.iloc[i]),   4),
                "season_avg_rebounds":   round(float(season_avg_rebounds.iloc[i]), 4),
                "season_avg_assists":    round(float(season_avg_assists.iloc[i]),  4),
                "season_avg_steals":     round(float(season_avg_steals.iloc[i]),   4),
                "season_avg_blocks":     round(float(season_avg_blocks.iloc[i]),   4),
            })

    base_df = pd.DataFrame(stat_records)
    logger.info(f"  → {len(base_df)} base stat feature rows")

    # ── 3. Improved minutes features ─────────────────────────────────────────
    logger.info("  Computing minutes features...")
    try:
        mins_df = build_minutes_features(logs, conn=conn)
        logger.info(f"  → {len(mins_df)} minutes feature rows")
    except Exception as e:
        logger.warning(f"  Minutes features failed: {e} — using fallback")
        mins_df = pd.DataFrame()

    # ── 4. Pace features ─────────────────────────────────────────────────────
    logger.info("  Computing pace features...")
    try:
        pace_df = build_pace_features(conn=conn)
        logger.info(f"  → {len(pace_df)} pace feature rows")
    except Exception as e:
        logger.warning(f"  Pace features failed: {e} — skipping")
        pace_df = pd.DataFrame()

    # ── 5. Defense features ──────────────────────────────────────────────────
    logger.info("  Computing defense features...")
    try:
        def_df = build_defense_features(conn=conn)
        logger.info(f"  → {len(def_df)} defense feature rows")
    except Exception as e:
        logger.warning(f"  Defense features failed: {e} — skipping")
        def_df = pd.DataFrame()

    # ── 6. Usage features ────────────────────────────────────────────────────
    logger.info("  Computing usage features...")
    try:
        usage_df = build_usage_features(conn=conn)
        logger.info(f"  → {len(usage_df)} usage feature rows")
    except Exception as e:
        logger.warning(f"  Usage features failed: {e} — skipping")
        usage_df = pd.DataFrame()

    # ── 6b. Advanced defense features (possession-adjusted ratings) ────
    logger.info("  Computing advanced defense features...")
    try:
        adv_def_df = build_advanced_defense_features(conn=conn)
        logger.info(f"  → {len(adv_def_df)} advanced defense feature rows")
    except Exception as e:
        logger.warning(f"  Advanced defense features failed: {e} — skipping")
        adv_def_df = pd.DataFrame()

    # ── 6c. Positional defense features ─────────────────────────────────
    logger.info("  Computing positional defense features...")
    try:
        pos_def_df = build_positional_defense_features(conn=conn)
        logger.info(f"  → {len(pos_def_df)} positional defense rows")
    except Exception as e:
        logger.warning(f"  Positional defense features failed: {e} — skipping")
        pos_def_df = pd.DataFrame()

    # ── 7. Join all feature groups ───────────────────────────────────────────
    logger.info("  Joining all feature groups...")
    features = base_df

    key = ["game_id", "player_id"]

    if not mins_df.empty:
        features = features.merge(mins_df, on=key, how="left")
    else:
        # Fallback: use minutes_avg_last_10 from logs directly
        mins_fallback = []
        for player_id, group in logs.groupby("player_id"):
            group = group.sort_values("game_date").reset_index(drop=True)
            rolling = group["minutes"].rolling(10, min_periods=1).mean()
            for i, row in group.iterrows():
                mins_fallback.append({
                    "game_id":                   row["game_id"],
                    "player_id":                 str(player_id),
                    "minutes_avg_last_5":        round(float(group["minutes"].rolling(5, min_periods=1).mean().iloc[i]), 4),
                    "minutes_avg_last_10":       round(float(rolling.iloc[i]), 4),
                    "minutes_trend":             0.0,
                    "games_started_last_5":      0,
                    "minutes_projection":        round(float(rolling.iloc[i]), 4),
                    "blowout_risk":              "NONE",
                    "blowout_adjustment_factor": 1.0,
                })
        features = features.merge(pd.DataFrame(mins_fallback), on=key, how="left")

    if not pace_df.empty:
        features = features.merge(pace_df, on=key, how="left")
    # Defaults for missing pace context
    for col, default in [
        ("team_pace", 100.0), ("opponent_pace", 100.0),
        ("expected_game_pace", 100.0), ("pace_adjustment_factor", 1.0),
    ]:
        if col not in features.columns:
            features[col] = default
        else:
            features[col] = features[col].fillna(default)

    if not def_df.empty:
        features = features.merge(def_df, on=key, how="left")
    # Defaults for missing defense context
    league_avg_pts_allowed = 110.0
    league_avg_reb_allowed = 44.0
    league_avg_ast_allowed = 25.0
    for col, default in [
        ("opponent_points_allowed",  league_avg_pts_allowed),
        ("opponent_rebounds_allowed", league_avg_reb_allowed),
        ("opponent_assists_allowed", league_avg_ast_allowed),
        ("defense_adj_pts",          1.0),
        ("defense_adj_reb",          1.0),
        ("defense_adj_ast",          1.0),
        ("opponent_steals_allowed",  8.0),
        ("opponent_blocks_allowed",  5.0),
        ("defense_adj_stl",          1.0),
        ("defense_adj_blk",          1.0),
    ]:
        if col not in features.columns:
            features[col] = default
        else:
            features[col] = features[col].fillna(default)

    if not usage_df.empty:
        features = features.merge(usage_df, on=key, how="left")
    for col, default in [("usage_proxy", 0.2), ("usage_trend_last_5", 0.0)]:
        if col not in features.columns:
            features[col] = default
        else:
            features[col] = features[col].fillna(default)

    if not adv_def_df.empty:
        features = features.merge(adv_def_df, on=key, how="left")
    for col, default in [
        ("team_off_rating", 110.0),
        ("opponent_def_rating", 110.0),
        ("rating_matchup_factor", 1.0),
    ]:
        if col not in features.columns:
            features[col] = default
        else:
            features[col] = features[col].fillna(default)

    # ── 6d. Injury context — boost usage_proxy for players with injured teammates ──
    logger.info("  Applying injury context to usage_proxy...")
    try:
        injury_multipliers = get_teammate_injury_multipliers(conn=conn)
        if injury_multipliers:
            features["usage_proxy"] = features.apply(
                lambda row: round(
                    float(row["usage_proxy"]) * injury_multipliers.get(str(row["player_id"]), 1.0),
                    4,
                ),
                axis=1,
            )
            logger.info(f"  → Injury multipliers applied to {len(injury_multipliers)} players")
        else:
            logger.info("  → No injury multipliers available (no injured teammates found)")
    except Exception as e:
        logger.warning(f"  Injury context failed: {e} — skipping")

    # ── 6e. Lineup impact features ────────────────────────────────────────
    logger.info("  Computing lineup impact features...")
    try:
        lineup_df = build_lineup_features(conn=conn)
        logger.info(f"  → {len(lineup_df)} lineup feature rows")
    except Exception as e:
        logger.warning(f"  Lineup features failed: {e} — skipping")
        lineup_df = pd.DataFrame()

    if not lineup_df.empty:
        features = features.merge(lineup_df, on=key, how="left")
    for col in ["usage_delta_teammate_out", "assist_delta_teammate_out", "rebound_delta_teammate_out"]:
        if col not in features.columns:
            features[col] = 0.0
        else:
            features[col] = features[col].fillna(0.0)

    if not pos_def_df.empty:
        pos_def_df["player_id"] = pos_def_df["player_id"].astype(str)
        features = features.merge(
            pos_def_df[key + [c for c in pos_def_df.columns if c not in key]],
            on=key, how="left",
        )
    for col, default in [
        ("positional_defense_adj_pts", 1.0),
        ("positional_defense_adj_reb", 1.0),
        ("positional_defense_adj_ast", 1.0),
        ("defense_vs_pg",              8.0),
        ("defense_vs_sg",              8.0),
        ("defense_vs_sf",              8.0),
        ("defense_vs_pf",              8.0),
        ("defense_vs_c",               8.0),
        ("player_position",            "SF"),
    ]:
        if col not in features.columns:
            features[col] = default
        else:
            features[col] = features[col].fillna(default)

    # ── 8. Write to DB ───────────────────────────────────────────────────────
    expected_cols = [
        "game_id", "player_id",
        "points_avg_last_5",  "points_avg_last_10",
        "rebounds_avg_last_5", "rebounds_avg_last_10",
        "assists_avg_last_5",  "assists_avg_last_10",
        "steals_avg_last_5",   "steals_avg_last_10",
        "blocks_avg_last_5",   "blocks_avg_last_10",
        "season_avg_points", "season_avg_rebounds", "season_avg_assists",
        "season_avg_steals", "season_avg_blocks",
        "minutes_avg_last_5", "minutes_avg_last_10", "minutes_trend",
        "games_started_last_5", "minutes_projection",
        "blowout_risk", "blowout_adjustment_factor",
        "team_pace", "opponent_pace", "expected_game_pace", "pace_adjustment_factor",
        "opponent_points_allowed", "opponent_rebounds_allowed", "opponent_assists_allowed",
        "defense_adj_pts", "defense_adj_reb", "defense_adj_ast",
        "opponent_steals_allowed", "opponent_blocks_allowed",
        "defense_adj_stl", "defense_adj_blk",
        "usage_proxy", "usage_trend_last_5",
        "team_off_rating", "opponent_def_rating", "rating_matchup_factor",
        "usage_delta_teammate_out", "assist_delta_teammate_out", "rebound_delta_teammate_out",
        "positional_defense_adj_pts", "positional_defense_adj_reb", "positional_defense_adj_ast",
        "defense_vs_pg", "defense_vs_sg", "defense_vs_sf", "defense_vs_pf", "defense_vs_c",
        "player_position",
    ]
    features = features[[c for c in expected_cols if c in features.columns]]

    if incremental:
        conn.execute("INSERT OR REPLACE INTO player_features BY NAME SELECT * FROM features")
    else:
        conn.execute("DELETE FROM player_features")
        conn.execute("INSERT INTO player_features BY NAME SELECT * FROM features")

    n = len(features)
    logger.info(f"  → {n} feature rows written to player_features.")
    conn.execute(
        "INSERT OR REPLACE INTO ingestion_log VALUES (?,?,?,?,?,?,current_timestamp)",
        [str(uuid.uuid4()), "feature_builder", "player_features", n, "success", ""]
    )
    if close:
        conn.close()
    return n
