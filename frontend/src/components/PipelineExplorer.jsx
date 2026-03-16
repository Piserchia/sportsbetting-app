import { useState, useMemo } from "react";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, BarChart, Bar, Cell, ReferenceLine,
} from "recharts";

// ── Theme (matches PropDashboard) ────────────────────────────────────────────
const T = {
  bg:        "#f4f5f7",
  surface:   "#ffffff",
  border:    "#e2e4e9",
  text:      "#1a1d23",
  textMid:   "#4a5568",
  textSub:   "#8a94a6",
  accent:    "#0ea96e",
  accentBg:  "#e8faf3",
  blue:      "#2563eb",
  blueBg:    "#eff6ff",
  warn:      "#d97706",
  warnBg:    "#fffbeb",
  danger:    "#dc2626",
  dangerBg:  "#fef2f2",
  purple:    "#7c3aed",
  purpleBg:  "#f5f3ff",
  orange:    "#ea580c",
  orangeBg:  "#fff7ed",
};

// ── Pipeline Stages (from PIPELINE.md + contracts) ───────────────────────────
const STAGES = [
  {
    key: "ingestion",
    label: "Data Sources",
    icon: "📡",
    color: T.blue,
    colorBg: T.blueBg,
    purpose: "Fetch raw data from external APIs — NBA stats, sportsbook odds, player props, injuries, and lineups.",
    inputs: ["NBA API (nba_api)", "SportsGameOdds API", "The Odds API", "ESPN / NBA.com"],
    outputs: ["teams", "players", "games", "player_game_stats", "team_game_stats", "odds", "sportsbook_props", "player_injuries", "starting_lineups"],
    example: "Fetches box scores for every NBA game — 1 API call per game with a 3-second delay to respect rate limits.",
    details: [
      "Teams, players, games, and schedules from NBA API",
      "Game odds (moneyline, spread, totals) from The Odds API",
      "Player prop lines from SportsGameOdds (DraftKings + FanDuel)",
      "Injury reports and starting lineups from ESPN / NBA.com",
    ],
  },
  {
    key: "gamelogs",
    label: "Game Logs",
    icon: "📋",
    color: "#6366f1",
    colorBg: "#eef2ff",
    purpose: "Normalize raw box score data into a clean, consistent format for feature engineering.",
    inputs: ["player_game_stats"],
    outputs: ["player_game_logs"],
    example: 'Converts raw "MIN: 34:22" strings into numeric 34.37 minutes, standardizes column names.',
    details: [
      "Extracts minutes, points, rebounds, assists, steals, blocks",
      "Converts string minute formats to decimals",
      "Creates a unified game log per (game_id, player_id)",
    ],
  },
  {
    key: "features",
    label: "Features",
    icon: "🧮",
    color: T.purple,
    colorBg: T.purpleBg,
    purpose: "Transform raw game data into 50+ predictive features that capture player context.",
    inputs: ["player_game_logs", "team_game_stats", "games", "player_injuries", "starting_lineups"],
    outputs: ["player_features (50+ columns)"],
    example: "A player averaging 28.4 pts over last 5 games, facing a team allowing 118 pts/game, gets defense_adj_pts = 1.07.",
    details: [
      "Rolling averages: L5, L10, season for all stats",
      "Minutes model: projection + blowout risk",
      "Pace context: team/opponent pace, adjustment factors",
      "Defense: opponent allowed stats, positional matchups",
      "Usage: rate proxy, 5-game trends",
      "Lineups: on/off splits for teammate injuries",
    ],
  },
  {
    key: "projections",
    label: "Projections",
    icon: "🎯",
    color: T.accent,
    colorBg: T.accentBg,
    purpose: "Generate stat predictions using LightGBM ML models with heuristic fallback.",
    inputs: ["player_features"],
    outputs: ["player_projections", "player_distributions"],
    example: "LeBron: points_mean = 27.4, rebounds_mean = 7.8, assists_mean = 8.1",
    details: [
      "Position-specific LightGBM models for each stat",
      "Falls back to weighted-average heuristic when data is insufficient",
      "Outputs mean + standard deviation for each stat",
      "Stats modeled: points, rebounds, assists, steals, blocks",
    ],
  },
  {
    key: "distributions",
    label: "Distributions",
    icon: "📊",
    color: T.orange,
    colorBg: T.orangeBg,
    purpose: "Fit appropriate statistical distributions to each player's projected stats.",
    inputs: ["player_distributions (mean, std_dev)"],
    outputs: ["Distribution parameters per player/stat"],
    example: "Points use Gamma (right-skewed) — captures the long tail of big scoring games.",
    details: [
      "Points: Gamma distribution (right-skewed, better tail behavior)",
      "Rebounds: Negative Binomial (count data, overdispersed)",
      "Assists: Negative Binomial (count data, overdispersed)",
      "Steals/Blocks: Negative Binomial",
      "Fallback: Normal distribution if fitting fails",
      "Minimum std_dev of 1.5 to prevent degenerate distributions",
    ],
  },
  {
    key: "simulations",
    label: "Simulations",
    icon: "🎲",
    color: T.warn,
    colorBg: T.warnBg,
    purpose: "Run 10,000 Monte Carlo simulations per player per stat to estimate probabilities.",
    inputs: ["player_distributions"],
    outputs: ["player_simulations — P(stat >= line) for every prop line"],
    example: "10,000 random samples from Gamma(mean=27.4, std=6.2) → count how many exceed each line.",
    details: [
      "10,000 random samples per player per stat",
      "Uses fitted distributions (Gamma, NegBin)",
      "Gaussian Copula for combo props (preserves correlations)",
      "Calculates P(stat >= line) for all sportsbook prop lines",
      "27 point lines, 12 rebound lines, 11 assist lines, 4 each for steals/blocks",
    ],
  },
  {
    key: "edges",
    label: "Edge Detection",
    icon: "💰",
    color: T.danger,
    colorBg: T.dangerBg,
    purpose: "Compare model probabilities against sportsbook implied probabilities to find +EV bets.",
    inputs: ["player_simulations", "sportsbook_props"],
    outputs: ["prop_edges — edge %, fair odds, expected value"],
    example: "Model says 60% chance of 25+ pts. Book implies 50%. That's a +10% edge.",
    details: [
      "Joins simulations with live sportsbook prop lines",
      "Exact line matching required (e.g., 24.5 not 25)",
      "implied_prob = |odds| / (|odds| + 100)",
      "edge = (model_prob - implied_prob) x 100",
      "Ranks edges by bet_score = (edge * 0.6) + (probability * 25)",
    ],
  },
];

// ── Feature Groups (from feature_schema.yaml) ────────────────────────────────
const FEATURE_GROUPS = [
  {
    name: "Rolling Stats",
    icon: "📈",
    color: T.blue,
    description: "EWMA recent adjusted, last 10, and season averages",
    features: [
      "points_recent_adj", "points_avg_last_10",
      "rebounds_recent_adj", "rebounds_avg_last_10",
      "assists_recent_adj", "assists_avg_last_10",
      "season_avg_points", "season_avg_rebounds", "season_avg_assists",
      "steals_recent_adj", "steals_avg_last_10",
      "blocks_recent_adj", "blocks_avg_last_10",
      "season_avg_steals", "season_avg_blocks",
    ],
  },
  {
    name: "Minutes Model",
    icon: "⏱️",
    color: T.purple,
    description: "Minutes projection and blowout risk",
    features: [
      "minutes_avg_last_5", "minutes_avg_last_10", "minutes_trend",
      "games_started_last_5", "minutes_projection",
      "blowout_risk", "blowout_adjustment_factor",
    ],
  },
  {
    name: "Pace",
    icon: "🏃",
    color: T.accent,
    description: "Game tempo context",
    features: [
      "team_pace", "opponent_pace",
      "expected_game_pace", "pace_adjustment_factor",
    ],
  },
  {
    name: "Defense",
    icon: "🛡️",
    color: T.danger,
    description: "Opponent defensive strength",
    features: [
      "opponent_points_allowed", "opponent_rebounds_allowed", "opponent_assists_allowed",
      "defense_adj_pts", "defense_adj_reb", "defense_adj_ast",
      "opponent_steals_allowed", "opponent_blocks_allowed",
      "defense_adj_stl", "defense_adj_blk",
    ],
  },
  {
    name: "Positional Defense",
    icon: "🎯",
    color: T.orange,
    description: "Defense by opponent position",
    features: [
      "positional_defense_adj_pts", "positional_defense_adj_reb", "positional_defense_adj_ast",
      "defense_vs_pg", "defense_vs_sg", "defense_vs_sf", "defense_vs_pf", "defense_vs_c",
      "player_position",
    ],
  },
  {
    name: "Advanced Defense",
    icon: "📊",
    color: "#6366f1",
    description: "Offensive/defensive ratings",
    features: [
      "team_off_rating", "opponent_def_rating", "rating_matchup_factor",
    ],
  },
  {
    name: "Usage",
    icon: "⚡",
    color: T.warn,
    description: "Usage rate and trends",
    features: [
      "usage_proxy", "usage_trend_last_5",
    ],
  },
  {
    name: "Lineup Impact",
    icon: "👥",
    color: T.blue,
    description: "Teammate injury impact (on/off splits)",
    features: [
      "usage_delta_teammate_out",
      "assist_delta_teammate_out",
      "rebound_delta_teammate_out",
    ],
  },
];

// ── Simulation Distribution Data (mock example) ─────────────────────────────
function generateDistributionData(mean, stdDev) {
  const data = [];
  const min = Math.max(0, mean - 3.5 * stdDev);
  const max = mean + 3.5 * stdDev;
  const step = (max - min) / 60;
  for (let x = min; x <= max; x += step) {
    const z = (x - mean) / stdDev;
    // Gamma-like skew: shift normal slightly right
    const skew = x < mean ? 0.85 : 1.1;
    const y = skew * Math.exp(-0.5 * z * z) / (stdDev * Math.sqrt(2 * Math.PI));
    data.push({ x: Math.round(x * 10) / 10, density: Math.round(y * 1000) / 1000 });
  }
  return data;
}

function generateProbabilityLadder(mean, stdDev) {
  const lines = [15.5, 19.5, 22.5, 24.5, 27.5, 29.5, 32.5, 34.5, 39.5];
  return lines.map(line => {
    // Approximate P(X >= line) using normal CDF
    const z = (line - mean) / stdDev;
    const prob = 1 - 0.5 * (1 + erf(z / Math.sqrt(2)));
    return { line: `${line}+`, probability: Math.round(prob * 100) };
  });
}

function erf(x) {
  const t = 1 / (1 + 0.3275911 * Math.abs(x));
  const poly = t * (0.254829592 + t * (-0.284496736 + t * (1.421413741 + t * (-1.453152027 + t * 1.061405429))));
  const val = 1 - poly * Math.exp(-x * x);
  return x >= 0 ? val : -val;
}

// ── Styles ───────────────────────────────────────────────────────────────────
const card = {
  background: T.surface,
  border: `1px solid ${T.border}`,
  borderRadius: 12,
  padding: 24,
};

const sectionTitle = {
  fontSize: 20,
  fontWeight: 700,
  color: T.text,
  marginBottom: 16,
};

const pill = (color, bg) => ({
  display: "inline-block",
  padding: "2px 10px",
  borderRadius: 20,
  fontSize: 11,
  fontWeight: 600,
  color,
  background: bg,
});

// ── Components ───────────────────────────────────────────────────────────────

function ArrowRight() {
  return (
    <svg width="28" height="28" viewBox="0 0 28 28" style={{ flexShrink: 0, opacity: 0.3 }}>
      <path d="M8 14h12M16 9l5 5-5 5" stroke={T.textSub} strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  );
}

function PipelineDiagram({ activeStage, onSelect }) {
  return (
    <div style={{ ...card, padding: "20px 16px" }}>
      <div style={{ fontSize: 13, fontWeight: 600, color: T.textSub, marginBottom: 14, textTransform: "uppercase", letterSpacing: "0.05em" }}>
        Pipeline Flow
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 6, overflowX: "auto", paddingBottom: 4 }}>
        {STAGES.map((stage, i) => (
          <div key={stage.key} style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <button
              onClick={() => onSelect(stage.key === activeStage ? null : stage.key)}
              style={{
                display: "flex", flexDirection: "column", alignItems: "center", gap: 6,
                padding: "12px 16px", borderRadius: 10, cursor: "pointer",
                border: activeStage === stage.key ? `2px solid ${stage.color}` : `1px solid ${T.border}`,
                background: activeStage === stage.key ? stage.colorBg : T.surface,
                transition: "all 0.15s",
                minWidth: 100,
              }}
            >
              <span style={{ fontSize: 24 }}>{stage.icon}</span>
              <span style={{ fontSize: 11, fontWeight: 600, color: activeStage === stage.key ? stage.color : T.textMid, textAlign: "center", lineHeight: 1.3 }}>
                {stage.label}
              </span>
            </button>
            {i < STAGES.length - 1 && <ArrowRight />}
          </div>
        ))}
      </div>
    </div>
  );
}

function StagePanel({ stage }) {
  if (!stage) return null;
  const s = STAGES.find(st => st.key === stage);
  if (!s) return null;

  return (
    <div style={{ ...card, borderLeft: `4px solid ${s.color}`, marginTop: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
        <span style={{ fontSize: 28 }}>{s.icon}</span>
        <div>
          <div style={{ fontSize: 18, fontWeight: 700, color: T.text }}>{s.label}</div>
          <div style={{ fontSize: 13, color: T.textMid, marginTop: 2 }}>{s.purpose}</div>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 11, fontWeight: 700, color: T.textSub, textTransform: "uppercase", marginBottom: 6 }}>Inputs</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {s.inputs.map(inp => (
              <span key={inp} style={pill(T.blue, T.blueBg)}>{inp}</span>
            ))}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 11, fontWeight: 700, color: T.textSub, textTransform: "uppercase", marginBottom: 6 }}>Outputs</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {s.outputs.map(out => (
              <span key={out} style={pill(T.accent, T.accentBg)}>{out}</span>
            ))}
          </div>
        </div>
      </div>

      <div style={{ background: T.bg, borderRadius: 8, padding: 14, marginBottom: 14 }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: T.textSub, textTransform: "uppercase", marginBottom: 6 }}>Example</div>
        <div style={{ fontSize: 13, color: T.textMid, fontStyle: "italic" }}>{s.example}</div>
      </div>

      <div>
        <div style={{ fontSize: 11, fontWeight: 700, color: T.textSub, textTransform: "uppercase", marginBottom: 8 }}>Details</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {s.details.map((d, i) => (
            <div key={i} style={{ fontSize: 13, color: T.textMid, paddingLeft: 12, position: "relative" }}>
              <span style={{ position: "absolute", left: 0, color: T.accent }}>+</span>
              {d}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function FeatureExplorer() {
  const [expanded, setExpanded] = useState(null);

  return (
    <div style={card}>
      <div style={sectionTitle}>Feature Explorer</div>
      <div style={{ fontSize: 13, color: T.textMid, marginBottom: 16 }}>
        50+ features engineered from raw game data. Click a group to see all features.
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 12 }}>
        {FEATURE_GROUPS.map(group => (
          <div
            key={group.name}
            onClick={() => setExpanded(expanded === group.name ? null : group.name)}
            style={{
              border: expanded === group.name ? `2px solid ${group.color}` : `1px solid ${T.border}`,
              borderRadius: 10,
              padding: 14,
              cursor: "pointer",
              transition: "all 0.15s",
              background: expanded === group.name ? `${group.color}08` : T.surface,
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
              <span style={{ fontSize: 18 }}>{group.icon}</span>
              <span style={{ fontSize: 14, fontWeight: 700, color: T.text }}>{group.name}</span>
              <span style={{ marginLeft: "auto", fontSize: 11, color: T.textSub, fontWeight: 600 }}>
                {group.features.length}
              </span>
            </div>
            <div style={{ fontSize: 12, color: T.textMid, marginBottom: expanded === group.name ? 10 : 0 }}>
              {group.description}
            </div>
            {expanded === group.name && (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 8 }}>
                {group.features.map(f => (
                  <code key={f} style={{
                    fontSize: 11, padding: "2px 8px", borderRadius: 4,
                    background: T.bg, color: T.textMid, fontFamily: "monospace",
                  }}>
                    {f}
                  </code>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function SimulationVisual() {
  const mean = 27.4;
  const stdDev = 6.2;
  const distData = useMemo(() => generateDistributionData(mean, stdDev), []);
  const probData = useMemo(() => generateProbabilityLadder(mean, stdDev), []);

  return (
    <div style={card}>
      <div style={sectionTitle}>Monte Carlo Simulation</div>
      <div style={{ fontSize: 13, color: T.textMid, marginBottom: 20 }}>
        10,000 random samples per player per stat. The distribution shape determines how likely each outcome is.
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24 }}>
        {/* Distribution curve */}
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: T.text, marginBottom: 4 }}>
            Example: Points Distribution
          </div>
          <div style={{ display: "flex", gap: 16, marginBottom: 12 }}>
            <span style={pill(T.accent, T.accentBg)}>Mean: {mean}</span>
            <span style={pill(T.blue, T.blueBg)}>Std Dev: {stdDev}</span>
            <span style={pill(T.purple, T.purpleBg)}>Gamma</span>
          </div>
          <ResponsiveContainer width="100%" height={200}>
            <AreaChart data={distData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
              <defs>
                <linearGradient id="distGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={T.accent} stopOpacity={0.3} />
                  <stop offset="100%" stopColor={T.accent} stopOpacity={0.03} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#edf0f5" />
              <XAxis dataKey="x" tick={{ fontSize: 10, fill: T.textSub }} label={{ value: "Points", position: "insideBottom", offset: -2, fontSize: 11, fill: T.textSub }} />
              <YAxis tick={false} width={10} />
              <Tooltip
                formatter={(val) => [val.toFixed(4), "Density"]}
                labelFormatter={(val) => `${val} points`}
                contentStyle={{ fontSize: 12, borderRadius: 8, border: `1px solid ${T.border}` }}
              />
              <ReferenceLine x={mean} stroke={T.accent} strokeDasharray="4 4" label={{ value: `Mean: ${mean}`, position: "top", fontSize: 10, fill: T.accent }} />
              <Area type="monotone" dataKey="density" stroke={T.accent} fill="url(#distGrad)" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* Probability ladder */}
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: T.text, marginBottom: 4 }}>
            Probability Ladder
          </div>
          <div style={{ fontSize: 12, color: T.textSub, marginBottom: 12 }}>
            {"P(points >= line) from 10k simulations"}
          </div>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={probData} layout="vertical" margin={{ top: 5, right: 10, left: 10, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#edf0f5" horizontal={false} />
              <XAxis type="number" domain={[0, 100]} tick={{ fontSize: 10, fill: T.textSub }} tickFormatter={v => `${v}%`} />
              <YAxis type="category" dataKey="line" tick={{ fontSize: 11, fill: T.textMid }} width={45} />
              <Tooltip
                formatter={(val) => [`${val}%`, "Probability"]}
                contentStyle={{ fontSize: 12, borderRadius: 8, border: `1px solid ${T.border}` }}
              />
              <Bar dataKey="probability" radius={[0, 4, 4, 0]} barSize={14}>
                {probData.map((entry) => (
                  <Cell key={entry.line} fill={entry.probability >= 50 ? T.accent : entry.probability >= 30 ? T.warn : T.danger} fillOpacity={0.8} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div style={{ background: T.bg, borderRadius: 8, padding: 14, marginTop: 16 }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: T.textSub, textTransform: "uppercase", marginBottom: 6 }}>How It Works</div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16 }}>
          {[
            { step: "1", title: "Fit Distribution", desc: "Points use Gamma, rebounds use Negative Binomial" },
            { step: "2", title: "Draw 10k Samples", desc: "Random values from the fitted distribution" },
            { step: "3", title: "Count Exceedances", desc: "P(stat >= line) = samples above line / 10,000" },
          ].map(s => (
            <div key={s.step} style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
              <span style={{
                width: 24, height: 24, borderRadius: "50%", background: T.accent, color: "#fff",
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: 12, fontWeight: 700, flexShrink: 0,
              }}>{s.step}</span>
              <div>
                <div style={{ fontSize: 13, fontWeight: 600, color: T.text }}>{s.title}</div>
                <div style={{ fontSize: 12, color: T.textMid }}>{s.desc}</div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function EdgeExplanation() {
  const modelProb = 60;
  const impliedProb = 50;
  const edge = modelProb - impliedProb;

  const barData = [
    { label: "Model", value: modelProb, fill: T.accent },
    { label: "Sportsbook", value: impliedProb, fill: T.blue },
  ];

  const exampleEdges = [
    { player: "LeBron James", stat: "Points", line: "24.5+", model: 64, book: 52, edge: 12, odds: "-110" },
    { player: "Luka Doncic", stat: "Assists", line: "8.5+", model: 58, book: 48, edge: 10, odds: "-105" },
    { player: "Jayson Tatum", stat: "Rebounds", line: "7.5+", model: 55, book: 50, edge: 5, odds: "-115" },
  ];

  return (
    <div style={card}>
      <div style={sectionTitle}>Edge Detection</div>
      <div style={{ fontSize: 13, color: T.textMid, marginBottom: 20 }}>
        An "edge" exists when our model thinks an outcome is more likely than the sportsbook does.
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24 }}>
        {/* Formula */}
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: T.text, marginBottom: 12 }}>How Edges Are Calculated</div>
          <div style={{ background: T.bg, borderRadius: 8, padding: 16, fontFamily: "monospace", fontSize: 13, lineHeight: 2.2 }}>
            <div><span style={{ color: T.textSub }}>implied_prob</span> = |odds| / (|odds| + 100)</div>
            <div><span style={{ color: T.textSub }}>edge</span> = (model_prob - implied_prob) x 100</div>
            <div style={{ borderTop: `1px solid ${T.border}`, marginTop: 8, paddingTop: 8 }}>
              <span style={{ color: T.accent }}>model_prob</span> = <strong>{modelProb}%</strong>
            </div>
            <div>
              <span style={{ color: T.blue }}>implied_prob</span> = <strong>{impliedProb}%</strong>
            </div>
            <div>
              <span style={{ color: T.danger }}>edge</span> = <strong>+{edge}%</strong>
            </div>
          </div>
        </div>

        {/* Bar comparison */}
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: T.text, marginBottom: 12 }}>Visual Comparison</div>
          <ResponsiveContainer width="100%" height={160}>
            <BarChart data={barData} layout="vertical" margin={{ top: 10, right: 30, left: 10, bottom: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#edf0f5" horizontal={false} />
              <XAxis type="number" domain={[0, 100]} tick={{ fontSize: 11, fill: T.textSub }} tickFormatter={v => `${v}%`} />
              <YAxis type="category" dataKey="label" tick={{ fontSize: 13, fontWeight: 600, fill: T.textMid }} width={90} />
              <Tooltip
                formatter={(val) => [`${val}%`, "Probability"]}
                contentStyle={{ fontSize: 12, borderRadius: 8, border: `1px solid ${T.border}` }}
              />
              <Bar dataKey="value" radius={[0, 6, 6, 0]} barSize={28}>
                {barData.map((entry, i) => (
                  <Cell key={i} fill={entry.fill} fillOpacity={0.85} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          <div style={{ textAlign: "center", marginTop: 8 }}>
            <span style={{
              ...pill(T.danger, T.dangerBg),
              fontSize: 14, fontWeight: 700, padding: "4px 16px",
            }}>
              Edge: +{edge}%
            </span>
          </div>
        </div>
      </div>

      {/* Example edges table */}
      <div style={{ marginTop: 20 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: T.text, marginBottom: 10 }}>Example Edges</div>
        <div style={{ borderRadius: 8, border: `1px solid ${T.border}`, overflow: "hidden" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ background: T.bg }}>
                {["Player", "Prop", "Model", "Book Implied", "Edge", "Book Odds"].map(h => (
                  <th key={h} style={{ padding: "8px 12px", textAlign: "left", fontSize: 11, fontWeight: 700, color: T.textSub, textTransform: "uppercase" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {exampleEdges.map((row, i) => (
                <tr key={i} style={{ borderTop: `1px solid ${T.border}` }}>
                  <td style={{ padding: "8px 12px", fontWeight: 600, color: T.text }}>{row.player}</td>
                  <td style={{ padding: "8px 12px", color: T.textMid }}>{row.stat} {row.line}</td>
                  <td style={{ padding: "8px 12px" }}>
                    <span style={pill(T.accent, T.accentBg)}>{row.model}%</span>
                  </td>
                  <td style={{ padding: "8px 12px" }}>
                    <span style={pill(T.blue, T.blueBg)}>{row.book}%</span>
                  </td>
                  <td style={{ padding: "8px 12px" }}>
                    <span style={{ ...pill(T.danger, T.dangerBg), fontWeight: 700 }}>+{row.edge}%</span>
                  </td>
                  <td style={{ padding: "8px 12px", color: T.textMid, fontFamily: "monospace" }}>{row.odds}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function DistributionTypes() {
  const types = [
    { stat: "Points", dist: "Gamma", reason: "Right-skewed — captures big scoring games", color: T.accent },
    { stat: "Rebounds", dist: "Neg. Binomial", reason: "Count data, overdispersed", color: T.blue },
    { stat: "Assists", dist: "Neg. Binomial", reason: "Count data, overdispersed", color: T.purple },
    { stat: "Steals", dist: "Neg. Binomial", reason: "Rare count events", color: T.warn },
    { stat: "Blocks", dist: "Neg. Binomial", reason: "Rare count events", color: T.orange },
  ];

  return (
    <div style={{ ...card, padding: 20 }}>
      <div style={{ fontSize: 15, fontWeight: 700, color: T.text, marginBottom: 12 }}>Distribution Types</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 10 }}>
        {types.map(t => (
          <div key={t.stat} style={{ textAlign: "center", padding: 12, borderRadius: 8, border: `1px solid ${T.border}` }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: t.color }}>{t.stat}</div>
            <div style={{ fontSize: 12, fontWeight: 600, color: T.text, marginTop: 4 }}>{t.dist}</div>
            <div style={{ fontSize: 11, color: T.textSub, marginTop: 2 }}>{t.reason}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Main Component ───────────────────────────────────────────────────────────
export default function PipelineExplorer() {
  const [activeStage, setActiveStage] = useState(null);

  return (
    <div style={{ maxWidth: 1200, margin: "0 auto", padding: "24px 28px" }}>
      {/* Header */}
      <div style={{ marginBottom: 24 }}>
        <div style={{ fontSize: 24, fontWeight: 700, color: T.text }}>How It Works</div>
        <div style={{ fontSize: 14, color: T.textMid, marginTop: 4 }}>
          From raw NBA data to betting edges — a visual guide to the analytics pipeline.
        </div>
      </div>

      {/* Pipeline Diagram */}
      <PipelineDiagram activeStage={activeStage} onSelect={setActiveStage} />
      <StagePanel stage={activeStage} />

      {/* Spacer */}
      <div style={{ height: 28 }} />

      {/* Feature Explorer */}
      <FeatureExplorer />

      <div style={{ height: 28 }} />

      {/* Simulation Section */}
      <SimulationVisual />

      <div style={{ height: 16 }} />

      {/* Distribution Types */}
      <DistributionTypes />

      <div style={{ height: 28 }} />

      {/* Edge Detection */}
      <EdgeExplanation />

      {/* Footer */}
      <div style={{ textAlign: "center", padding: "32px 0 16px", fontSize: 12, color: T.textSub }}>
        Data sourced from pipeline contracts and architecture documentation.
      </div>
    </div>
  );
}
