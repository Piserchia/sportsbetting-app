import { useState, useEffect, useRef } from "react";
import { LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine, ResponsiveContainer, Area, AreaChart, Cell } from "recharts";

// ── Mock Data (replace with API calls once FastAPI layer is built) ──────────
const MOCK_PLAYER = {
  id: "203954",
  name: "Joel Embiid",
  team: "PHI",
  position: "C",
  opponent: "BOS",
  gameTime: "7:30 PM ET",
  status: "ACTIVE",
  minutesProjection: 32.4,
};

const MOCK_GAME_LOG = [
  { game: "vs MIA", date: "Mar 1", pts: 34, reb: 11, ast: 5, min: 34, opp_pace: 98.2, opp_def_rtg: 112.1 },
  { game: "@ NYK", date: "Feb 27", pts: 28, reb: 9,  ast: 3, min: 31, opp_pace: 97.8, opp_def_rtg: 108.4 },
  { game: "vs CHI", date: "Feb 25", pts: 41, reb: 12, ast: 6, min: 36, opp_pace: 101.2, opp_def_rtg: 115.2 },
  { game: "@ ATL", date: "Feb 22", pts: 22, reb: 8,  ast: 4, min: 28, opp_pace: 102.4, opp_def_rtg: 116.8 },
  { game: "vs ORL", date: "Feb 19", pts: 31, reb: 10, ast: 7, min: 33, opp_pace: 96.1, opp_def_rtg: 104.3 },
  { game: "@ BKN", date: "Feb 17", pts: 19, reb: 7,  ast: 2, min: 27, opp_pace: 99.3, opp_def_rtg: 117.2 },
  { game: "vs WAS", date: "Feb 14", pts: 38, reb: 14, ast: 5, min: 35, opp_pace: 103.1, opp_def_rtg: 118.9 },
  { game: "@ CLE", date: "Feb 12", pts: 25, reb: 9,  ast: 4, min: 32, opp_pace: 96.8, opp_def_rtg: 106.1 },
  { game: "vs TOR", date: "Feb 10", pts: 44, reb: 13, ast: 8, min: 37, opp_pace: 100.5, opp_def_rtg: 113.4 },
  { game: "@ MIL", date: "Feb 7",  pts: 27, reb: 10, ast: 3, min: 30, opp_pace: 98.9, opp_def_rtg: 109.2 },
];

const MOCK_OPPONENT_FLAGS = [
  { type: "PACE",    severity: "HIGH",   label: "BOS ranks 4th in pace (102.8)", icon: "⚡" },
  { type: "DEF",     severity: "CAUTION", label: "BOS allows 2nd-fewest pts to C (21.4 ppg)", icon: "🛡" },
  { type: "MATCHUP", severity: "GOOD",   label: "Embiid averaging 31.2 pts vs BOS last 3", icon: "🔥" },
  { type: "REST",    severity: "GOOD",   label: "2 days rest — higher mins projection", icon: "✓" },
];

const MOCK_SIMULATION = {
  mean: 29.4,
  std: 8.2,
  // Pre-computed normal distribution curve
  curve: Array.from({ length: 80 }, (_, i) => {
    const x = i * 1.0;
    const mean = 29.4, std = 8.2;
    const y = (1 / (std * Math.sqrt(2 * Math.PI))) * Math.exp(-0.5 * ((x - mean) / std) ** 2);
    return { x: parseFloat(x.toFixed(1)), y: parseFloat((y * 100).toFixed(4)) };
  }),
};

const MOCK_PROP_LINES = [
  { stat: "points", line: 15, modelProb: 0.96, dkOdds: -800, fdOdds: -750, bmOdds: -700 },
  { stat: "points", line: 20, modelProb: 0.88, dkOdds: -400, fdOdds: -380, bmOdds: -420 },
  { stat: "points", line: 25, modelProb: 0.71, dkOdds: -160, fdOdds: -155, bmOdds: -165 },
  { stat: "points", line: 29.5, modelProb: 0.52, dkOdds: -115, fdOdds: -110, bmOdds: -120 },
  { stat: "points", line: 30, modelProb: 0.49, dkOdds: -108, fdOdds: -105, bmOdds: -112 },
  { stat: "points", line: 35, modelProb: 0.28, dkOdds: 180,  fdOdds: 175,  bmOdds: 185  },
  { stat: "points", line: 40, modelProb: 0.11, dkOdds: 420,  fdOdds: 400,  bmOdds: 440  },
  { stat: "points", line: 45, modelProb: 0.03, dkOdds: 900,  fdOdds: 850,  bmOdds: 950  },
];

// ── Utilities ──────────────────────────────────────────────────────────────
const probToAmericanOdds = (p) => {
  if (p <= 0 || p >= 1) return "N/A";
  if (p >= 0.5) return `${Math.round(-(p / (1 - p)) * 100)}`;
  return `+${Math.round(((1 - p) / p) * 100)}`;
};

const americanToImplied = (odds) => {
  if (odds > 0) return 100 / (odds + 100);
  return Math.abs(odds) / (Math.abs(odds) + 100);
};

const calcEdge = (modelProb, bookOdds) => {
  const implied = americanToImplied(bookOdds);
  return ((modelProb - implied) * 100).toFixed(1);
};

const formatOdds = (n) => (n > 0 ? `+${n}` : `${n}`);

const edgeColor = (edge) => {
  const e = parseFloat(edge);
  if (e >= 5) return "#00ff88";
  if (e >= 2) return "#aaff44";
  if (e <= -5) return "#ff4455";
  if (e <= -2) return "#ff8844";
  return "#888";
};

const severityColor = (s) => ({
  HIGH: "#00ff88",
  GOOD: "#00ff88",
  CAUTION: "#ffaa00",
  BAD: "#ff4455",
}[s] || "#888");

// ── Sub-components ────────────────────────────────────────────────────────

const StatBadge = ({ label, value, sub }) => (
  <div style={{
    background: "rgba(255,255,255,0.04)",
    border: "1px solid rgba(255,255,255,0.08)",
    borderRadius: 4,
    padding: "10px 16px",
    minWidth: 90,
  }}>
    <div style={{ color: "#555", fontSize: 10, letterSpacing: "0.12em", fontFamily: "monospace", marginBottom: 4 }}>
      {label}
    </div>
    <div style={{ color: "#e8e8e8", fontSize: 22, fontFamily: "monospace", fontWeight: 700, lineHeight: 1 }}>
      {value}
    </div>
    {sub && <div style={{ color: "#444", fontSize: 10, fontFamily: "monospace", marginTop: 3 }}>{sub}</div>}
  </div>
);

const SectionLabel = ({ children }) => (
  <div style={{
    color: "#333",
    fontSize: 10,
    letterSpacing: "0.18em",
    fontFamily: "monospace",
    textTransform: "uppercase",
    marginBottom: 12,
    paddingBottom: 6,
    borderBottom: "1px solid #1a1a1a",
  }}>
    {children}
  </div>
);

const CustomDistTooltip = ({ active, payload }) => {
  if (!active || !payload?.length) return null;
  const x = payload[0]?.payload?.x;
  const normal = (x, m, s) => (1/(s*Math.sqrt(2*Math.PI)))*Math.exp(-0.5*((x-m)/s)**2);
  const prob = MOCK_PROP_LINES.find(p => Math.abs(p.line - x) < 0.5);
  return (
    <div style={{
      background: "#0e0e0e",
      border: "1px solid #222",
      borderRadius: 4,
      padding: "8px 12px",
      fontFamily: "monospace",
      fontSize: 11,
    }}>
      <div style={{ color: "#666" }}>score: <span style={{ color: "#e8e8e8" }}>{x}</span></div>
      {prob && <div style={{ color: "#00ff88", marginTop: 2 }}>P(≥{prob.line}) = {(prob.modelProb * 100).toFixed(0)}%</div>}
    </div>
  );
};

const CustomBarTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{
      background: "#0e0e0e",
      border: "1px solid #222",
      borderRadius: 4,
      padding: "8px 12px",
      fontFamily: "monospace",
      fontSize: 11,
    }}>
      <div style={{ color: "#666", marginBottom: 4 }}>{label}</div>
      {payload.map((p, i) => (
        <div key={i} style={{ color: p.color }}>{p.name}: {p.value}</div>
      ))}
    </div>
  );
};

// ── Main Dashboard ────────────────────────────────────────────────────────
export default function PropDashboard() {
  const [activeStat, setActiveStat] = useState("points");
  const [selectedLine, setSelectedLine] = useState(29.5);
  const [hoverRow, setHoverRow] = useState(null);

  const avg10 = (MOCK_GAME_LOG.reduce((s, g) => s + g.pts, 0) / MOCK_GAME_LOG.length).toFixed(1);
  const avg5  = (MOCK_GAME_LOG.slice(0, 5).reduce((s, g) => s + g.pts, 0) / 5).toFixed(1);
  const high10 = Math.max(...MOCK_GAME_LOG.map(g => g.pts));
  const hit10  = MOCK_GAME_LOG.filter(g => g.pts >= selectedLine).length;

  const selectedProp = MOCK_PROP_LINES.find(p => p.line === selectedLine) || MOCK_PROP_LINES[3];
  const fairOdds     = probToAmericanOdds(selectedProp.modelProb);
  const dkEdge       = calcEdge(selectedProp.modelProb, selectedProp.dkOdds);
  const fdEdge       = calcEdge(selectedProp.modelProb, selectedProp.fdOdds);

  return (
    <div style={{
      background: "#080808",
      minHeight: "100vh",
      color: "#e8e8e8",
      fontFamily: "'IBM Plex Mono', 'Courier New', monospace",
      padding: "0",
    }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@300;400;500;600;700&family=Bebas+Neue&display=swap');
        * { box-sizing: border-box; }
        ::-webkit-scrollbar { width: 4px; }
        ::-webkit-scrollbar-track { background: #0e0e0e; }
        ::-webkit-scrollbar-thumb { background: #222; border-radius: 2px; }
        .prop-row:hover { background: rgba(0,255,136,0.04) !important; cursor: pointer; }
        .stat-tab { transition: all 0.15s; cursor: pointer; }
        .stat-tab:hover { color: #e8e8e8 !important; }
        .flag-row { transition: background 0.15s; }
        .flag-row:hover { background: rgba(255,255,255,0.03) !important; }
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }
        @keyframes scanline {
          0% { transform: translateY(-100%); }
          100% { transform: translateY(100vh); }
        }
      `}</style>

      {/* Scanline overlay */}
      <div style={{
        position: "fixed", top: 0, left: 0, right: 0, bottom: 0,
        backgroundImage: "repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,0,0,0.03) 2px, rgba(0,0,0,0.03) 4px)",
        pointerEvents: "none", zIndex: 0,
      }} />

      <div style={{ position: "relative", zIndex: 1, maxWidth: 1400, margin: "0 auto", padding: "24px 28px" }}>

        {/* ── Header ── */}
        <div style={{
          display: "flex", justifyContent: "space-between", alignItems: "flex-start",
          marginBottom: 28, paddingBottom: 20,
          borderBottom: "1px solid #1a1a1a",
        }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 6 }}>
              <span style={{
                fontFamily: "'Bebas Neue', sans-serif",
                fontSize: 42, letterSpacing: "0.04em", lineHeight: 1,
                color: "#e8e8e8",
              }}>
                {MOCK_PLAYER.name}
              </span>
              <span style={{
                background: "#00ff88", color: "#000", fontSize: 10,
                fontWeight: 700, padding: "3px 8px", borderRadius: 2,
                letterSpacing: "0.1em",
              }}>
                {MOCK_PLAYER.status}
              </span>
            </div>
            <div style={{ color: "#444", fontSize: 11, letterSpacing: "0.08em" }}>
              {MOCK_PLAYER.team} · {MOCK_PLAYER.position} · vs {MOCK_PLAYER.opponent} · {MOCK_PLAYER.gameTime}
            </div>
          </div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", justifyContent: "flex-end" }}>
            <StatBadge label="L10 AVG" value={avg10} sub="pts" />
            <StatBadge label="L5 AVG" value={avg5} sub="pts" />
            <StatBadge label="SEASON HIGH" value={high10} sub="pts" />
            <StatBadge label="MIN PROJ" value={MOCK_PLAYER.minutesProjection} sub="minutes" />
          </div>
        </div>

        {/* ── Stat tabs ── */}
        <div style={{ display: "flex", gap: 4, marginBottom: 24 }}>
          {["points", "rebounds", "assists"].map(s => (
            <button key={s} className="stat-tab"
              onClick={() => setActiveStat(s)}
              style={{
                background: activeStat === s ? "#00ff88" : "transparent",
                color: activeStat === s ? "#000" : "#444",
                border: `1px solid ${activeStat === s ? "#00ff88" : "#1e1e1e"}`,
                borderRadius: 2, padding: "6px 18px",
                fontSize: 11, fontFamily: "monospace",
                letterSpacing: "0.12em", textTransform: "uppercase",
                fontWeight: activeStat === s ? 700 : 400,
                cursor: "pointer",
              }}>
              {s}
            </button>
          ))}
          <div style={{ marginLeft: "auto", color: "#2a2a2a", fontSize: 10, alignSelf: "center", letterSpacing: "0.1em" }}>
            SIM: 10,000 RUNS · MODEL v1.2
          </div>
        </div>

        {/* ── Main grid ── */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 380px", gap: 20, marginBottom: 20 }}>

          {/* Left column */}
          <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>

            {/* Distribution curve */}
            <div style={{
              background: "#0a0a0a", border: "1px solid #151515",
              borderRadius: 6, padding: "20px 20px 12px",
            }}>
              <SectionLabel>Monte Carlo Distribution · 10,000 Simulations</SectionLabel>
              <div style={{ display: "flex", gap: 16, marginBottom: 16 }}>
                <div>
                  <span style={{ color: "#333", fontSize: 10, letterSpacing: "0.1em" }}>MODEL MEAN </span>
                  <span style={{ color: "#00ff88", fontSize: 13, fontWeight: 700 }}>{MOCK_SIMULATION.mean}</span>
                </div>
                <div>
                  <span style={{ color: "#333", fontSize: 10, letterSpacing: "0.1em" }}>σ </span>
                  <span style={{ color: "#666", fontSize: 13 }}>{MOCK_SIMULATION.std}</span>
                </div>
                <div>
                  <span style={{ color: "#333", fontSize: 10, letterSpacing: "0.1em" }}>P(≥{selectedLine}) </span>
                  <span style={{ color: "#00ff88", fontSize: 13, fontWeight: 700 }}>
                    {(selectedProp.modelProb * 100).toFixed(0)}%
                  </span>
                </div>
              </div>

              <ResponsiveContainer width="100%" height={180}>
                <AreaChart data={MOCK_SIMULATION.curve} margin={{ top: 0, right: 0, left: -30, bottom: 0 }}>
                  <defs>
                    <linearGradient id="distGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor="#00ff88" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#00ff88" stopOpacity={0.02} />
                    </linearGradient>
                    <linearGradient id="distGradOver" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor="#00ff88" stopOpacity={0.7} />
                      <stop offset="95%" stopColor="#00ff88" stopOpacity={0.1} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="2 4" stroke="#111" vertical={false} />
                  <XAxis dataKey="x" stroke="#222" tick={{ fill: "#333", fontSize: 9, fontFamily: "monospace" }}
                    tickLine={false} interval={9} />
                  <YAxis stroke="transparent" tick={false} />
                  <Tooltip content={<CustomDistTooltip />} />

                  {/* Selected line marker */}
                  <ReferenceLine x={selectedLine} stroke="#00ff88" strokeWidth={1.5}
                    strokeDasharray="4 3" label={{ value: `${selectedLine}`, fill: "#00ff88", fontSize: 10, fontFamily: "monospace" }} />

                  {/* Mean marker */}
                  <ReferenceLine x={MOCK_SIMULATION.mean} stroke="#ffffff" strokeWidth={1}
                    strokeDasharray="2 4" label={{ value: "μ", fill: "#555", fontSize: 10 }} />

                  {/* Book line markers */}
                  {MOCK_PROP_LINES.filter(p => p.line !== selectedLine).map(p => (
                    <ReferenceLine key={p.line} x={p.line} stroke="#1e3a28"
                      strokeWidth={1} strokeDasharray="1 5" />
                  ))}

                  <Area type="monotone" dataKey="y" stroke="#00ff88" strokeWidth={1.5}
                    fill="url(#distGrad)" dot={false} />
                </AreaChart>
              </ResponsiveContainer>
            </div>

            {/* Last 10 games bar chart */}
            <div style={{
              background: "#0a0a0a", border: "1px solid #151515",
              borderRadius: 6, padding: "20px 20px 12px",
            }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                <SectionLabel>Last 10 Games · Points</SectionLabel>
                <div style={{ color: "#333", fontSize: 10, fontFamily: "monospace", marginBottom: 12 }}>
                  {hit10}/10 hit {selectedLine}+
                  <span style={{
                    marginLeft: 8, color: hit10 >= 6 ? "#00ff88" : hit10 >= 4 ? "#ffaa00" : "#ff4455",
                    fontWeight: 700
                  }}>
                    ({(hit10 / 10 * 100).toFixed(0)}%)
                  </span>
                </div>
              </div>

              <ResponsiveContainer width="100%" height={160}>
                <BarChart data={MOCK_GAME_LOG.slice().reverse()} margin={{ top: 4, right: 0, left: -30, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="2 4" stroke="#111" vertical={false} />
                  <XAxis dataKey="game" stroke="#222" tick={{ fill: "#333", fontSize: 9, fontFamily: "monospace" }} tickLine={false} />
                  <YAxis stroke="transparent" tick={{ fill: "#333", fontSize: 9, fontFamily: "monospace" }} />
                  <Tooltip content={<CustomBarTooltip />} />
                  <ReferenceLine y={selectedLine} stroke="#00ff88" strokeWidth={1} strokeDasharray="4 3"
                    label={{ value: `${selectedLine}`, fill: "#00ff88", fontSize: 9, fontFamily: "monospace", position: "right" }} />
                  <Bar dataKey="pts" name="PTS" radius={[2, 2, 0, 0]}>
                    {MOCK_GAME_LOG.slice().reverse().map((g, i) => (
                      <Cell key={i} fill={g.pts >= selectedLine ? "#00ff88" : "#1a2a1a"} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>

            {/* Recent game log table */}
            <div style={{
              background: "#0a0a0a", border: "1px solid #151515",
              borderRadius: 6, padding: "20px",
            }}>
              <SectionLabel>Game Log · Last 10</SectionLabel>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
                <thead>
                  <tr style={{ color: "#333", borderBottom: "1px solid #151515" }}>
                    {["DATE", "MATCHUP", "MIN", "PTS", "REB", "AST", "OPP PACE", "OPP DEF RTG"].map(h => (
                      <th key={h} style={{ textAlign: "right", padding: "4px 8px", fontWeight: 400, letterSpacing: "0.08em", fontSize: 9 }}>
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {MOCK_GAME_LOG.map((g, i) => (
                    <tr key={i} className="flag-row"
                      style={{ borderBottom: "1px solid #0f0f0f", background: i === hoverRow ? "rgba(0,255,136,0.03)" : "transparent" }}
                      onMouseEnter={() => setHoverRow(i)} onMouseLeave={() => setHoverRow(null)}>
                      <td style={{ padding: "6px 8px", color: "#444", textAlign: "right", fontSize: 10 }}>{g.date}</td>
                      <td style={{ padding: "6px 8px", color: "#666", textAlign: "right" }}>{g.game}</td>
                      <td style={{ padding: "6px 8px", color: "#555", textAlign: "right" }}>{g.min}</td>
                      <td style={{ padding: "6px 8px", textAlign: "right", fontWeight: 700,
                        color: g.pts >= selectedLine ? "#00ff88" : g.pts >= selectedLine * 0.85 ? "#ffaa00" : "#666" }}>
                        {g.pts}
                      </td>
                      <td style={{ padding: "6px 8px", color: "#666", textAlign: "right" }}>{g.reb}</td>
                      <td style={{ padding: "6px 8px", color: "#666", textAlign: "right" }}>{g.ast}</td>
                      <td style={{ padding: "6px 8px", textAlign: "right",
                        color: g.opp_pace > 101 ? "#00ff88" : g.opp_pace < 97 ? "#ff4455" : "#666" }}>
                        {g.opp_pace}
                      </td>
                      <td style={{ padding: "6px 8px", textAlign: "right",
                        color: g.opp_def_rtg > 114 ? "#00ff88" : g.opp_def_rtg < 108 ? "#ff4455" : "#666" }}>
                        {g.opp_def_rtg}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Right column */}
          <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>

            {/* Opponent flags */}
            <div style={{
              background: "#0a0a0a", border: "1px solid #151515",
              borderRadius: 6, padding: "20px",
            }}>
              <SectionLabel>Matchup Intelligence · vs {MOCK_PLAYER.opponent}</SectionLabel>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {MOCK_OPPONENT_FLAGS.map((flag, i) => (
                  <div key={i} className="flag-row" style={{
                    display: "flex", alignItems: "flex-start", gap: 10,
                    padding: "10px 12px", borderRadius: 4,
                    border: `1px solid ${severityColor(flag.severity)}22`,
                    background: `${severityColor(flag.severity)}08`,
                  }}>
                    <span style={{ fontSize: 14, lineHeight: 1.4 }}>{flag.icon}</span>
                    <div>
                      <div style={{ color: severityColor(flag.severity), fontSize: 9, letterSpacing: "0.1em", marginBottom: 2 }}>
                        {flag.type}
                      </div>
                      <div style={{ color: "#888", fontSize: 11, lineHeight: 1.4 }}>{flag.label}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Prop line selector + edge table */}
            <div style={{
              background: "#0a0a0a", border: "1px solid #151515",
              borderRadius: 6, padding: "20px",
            }}>
              <SectionLabel>Alternate Lines · Select to Analyze</SectionLabel>

              {/* Selected line detail */}
              <div style={{
                background: "#050505", border: "1px solid #00ff8833",
                borderRadius: 4, padding: "14px 16px", marginBottom: 16,
              }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                  <div>
                    <span style={{ color: "#444", fontSize: 10, letterSpacing: "0.1em" }}>SELECTED LINE </span>
                    <span style={{ color: "#e8e8e8", fontSize: 20, fontWeight: 700 }}>{selectedLine}</span>
                    <span style={{ color: "#444", fontSize: 11, marginLeft: 4 }}>pts</span>
                  </div>
                  <div style={{ textAlign: "right" }}>
                    <div style={{ color: "#444", fontSize: 9, letterSpacing: "0.1em", marginBottom: 2 }}>MODEL PROB</div>
                    <div style={{ color: "#00ff88", fontSize: 18, fontWeight: 700 }}>
                      {(selectedProp.modelProb * 100).toFixed(0)}%
                    </div>
                  </div>
                </div>
                <div style={{ display: "flex", gap: 8 }}>
                  <div style={{ flex: 1, background: "#0a0a0a", borderRadius: 3, padding: "8px 10px" }}>
                    <div style={{ color: "#333", fontSize: 9, letterSpacing: "0.08em", marginBottom: 3 }}>FAIR ODDS</div>
                    <div style={{ color: "#e8e8e8", fontSize: 14, fontWeight: 700 }}>{fairOdds}</div>
                  </div>
                  <div style={{ flex: 1, background: "#0a0a0a", borderRadius: 3, padding: "8px 10px" }}>
                    <div style={{ color: "#333", fontSize: 9, letterSpacing: "0.08em", marginBottom: 3 }}>DK EDGE</div>
                    <div style={{ color: edgeColor(dkEdge), fontSize: 14, fontWeight: 700 }}>{dkEdge > 0 ? "+" : ""}{dkEdge}%</div>
                  </div>
                  <div style={{ flex: 1, background: "#0a0a0a", borderRadius: 3, padding: "8px 10px" }}>
                    <div style={{ color: "#333", fontSize: 9, letterSpacing: "0.08em", marginBottom: 3 }}>FD EDGE</div>
                    <div style={{ color: edgeColor(fdEdge), fontSize: 14, fontWeight: 700 }}>{fdEdge > 0 ? "+" : ""}{fdEdge}%</div>
                  </div>
                </div>
              </div>

              {/* Full ladder */}
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
                <thead>
                  <tr style={{ color: "#2a2a2a", borderBottom: "1px solid #141414" }}>
                    {["LINE", "MODEL", "FAIR", "DK", "FD", "EDGE"].map(h => (
                      <th key={h} style={{ textAlign: "right", padding: "4px 6px", fontWeight: 400, fontSize: 9, letterSpacing: "0.08em" }}>
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {MOCK_PROP_LINES.map((p, i) => {
                    const edge = calcEdge(p.modelProb, p.dkOdds);
                    const isSelected = p.line === selectedLine;
                    return (
                      <tr key={i} className="prop-row"
                        onClick={() => setSelectedLine(p.line)}
                        style={{
                          borderBottom: "1px solid #0d0d0d",
                          background: isSelected ? "rgba(0,255,136,0.06)" : "transparent",
                          cursor: "pointer",
                        }}>
                        <td style={{ padding: "7px 6px", textAlign: "right", fontWeight: isSelected ? 700 : 400,
                          color: isSelected ? "#00ff88" : "#666" }}>
                          {p.line}+
                        </td>
                        <td style={{ padding: "7px 6px", textAlign: "right", color: "#00ff88", fontWeight: 600 }}>
                          {(p.modelProb * 100).toFixed(0)}%
                        </td>
                        <td style={{ padding: "7px 6px", textAlign: "right", color: "#555" }}>
                          {probToAmericanOdds(p.modelProb)}
                        </td>
                        <td style={{ padding: "7px 6px", textAlign: "right", color: "#666" }}>
                          {formatOdds(p.dkOdds)}
                        </td>
                        <td style={{ padding: "7px 6px", textAlign: "right", color: "#666" }}>
                          {formatOdds(p.fdOdds)}
                        </td>
                        <td style={{ padding: "7px 6px", textAlign: "right", fontWeight: 700,
                          color: edgeColor(edge) }}>
                          {edge > 0 ? "+" : ""}{edge}%
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* Model confidence */}
            <div style={{
              background: "#0a0a0a", border: "1px solid #151515",
              borderRadius: 6, padding: "16px 20px",
            }}>
              <SectionLabel>Model Confidence</SectionLabel>
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {[
                  { label: "Sample Size", value: "10 games", score: 0.6, note: "min 15 recommended" },
                  { label: "Minutes Stability", value: "±3.2 min", score: 0.75, note: "σ from L10" },
                  { label: "Usage Consistency", value: "28.4% USG", score: 0.82, note: "low variance" },
                ].map((item, i) => (
                  <div key={i}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                      <span style={{ color: "#555", fontSize: 10, letterSpacing: "0.06em" }}>{item.label}</span>
                      <span style={{ color: "#666", fontSize: 10 }}>{item.value}</span>
                    </div>
                    <div style={{ background: "#0f0f0f", borderRadius: 2, height: 3, overflow: "hidden" }}>
                      <div style={{
                        height: "100%", borderRadius: 2,
                        width: `${item.score * 100}%`,
                        background: item.score > 0.75 ? "#00ff88" : item.score > 0.5 ? "#ffaa00" : "#ff4455",
                        transition: "width 0.5s ease",
                      }} />
                    </div>
                    <div style={{ color: "#2a2a2a", fontSize: 9, marginTop: 2 }}>{item.note}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div style={{ borderTop: "1px solid #111", paddingTop: 14, display: "flex", justifyContent: "space-between" }}>
          <div style={{ color: "#1e1e1e", fontSize: 9, letterSpacing: "0.1em" }}>
            DATA: NBA.COM · ODDS: SPORTSGAMEODDS · MODEL: MONTE CARLO v1.2
          </div>
          <div style={{ color: "#1e1e1e", fontSize: 9, letterSpacing: "0.1em" }}>
            UPDATED: {new Date().toLocaleTimeString()} · FOR ANALYTICAL USE ONLY
          </div>
        </div>
      </div>
    </div>
  );
}
