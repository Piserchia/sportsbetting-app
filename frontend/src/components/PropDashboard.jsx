import { useState, useEffect, useCallback } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ReferenceLine, ResponsiveContainer, AreaChart, Area, Cell,
} from "recharts";

const API = "http://localhost:8000";
const CURRENT_SEASON = "2025-26";

// ── Theme ──────────────────────────────────────────────────────────────────
const T = {
  bg:        "#f4f5f7",
  surface:   "#ffffff",
  border:    "#e2e4e9",
  borderMid: "#d0d3db",
  text:      "#1a1d23",
  textMid:   "#4a5568",
  textSub:   "#8a94a6",
  textFaint: "#b8bfcc",
  accent:    "#0ea96e",
  accentBg:  "#e8faf3",
  accentDark:"#0a7a50",
  blue:      "#2563eb",
  blueBg:    "#eff6ff",
  warn:      "#d97706",
  warnBg:    "#fffbeb",
  danger:    "#dc2626",
  dangerBg:  "#fef2f2",
  gridLine:  "#edf0f5",
  barHit:    "#0ea96e",
  barMiss:   "#dde2ec",
};

// ── Utilities ──────────────────────────────────────────────────────────────
const formatOdds = (n) => {
  if (n === null || n === undefined) return "—";
  return n > 0 ? `+${n}` : `${n}`;
};

const formatDate = (d) => {
  if (!d) return "";
  const dt = new Date(d + "T00:00:00");
  return dt.toLocaleDateString("en-US", { month: "short", day: "numeric" });
};

const edgeColor = (edge) => {
  if (edge === null || edge === undefined) return T.textSub;
  const e = parseFloat(edge);
  if (e >= 5)  return T.accent;
  if (e >= 2)  return "#16a34a";
  if (e <= -5) return T.danger;
  if (e <= -2) return "#ea580c";
  return T.textSub;
};

const severityColor = (s) => ({
  HIGH:    T.accent,
  GOOD:    T.accent,
  NEUTRAL: T.textSub,
  CAUTION: T.warn,
  BAD:     T.danger,
}[s] || T.textSub);

const severityBg = (s) => ({
  HIGH:    T.accentBg,
  GOOD:    T.accentBg,
  NEUTRAL: "#f8f9fb",
  CAUTION: T.warnBg,
  BAD:     T.dangerBg,
}[s] || "#f8f9fb");

const severityBorder = (s) => ({
  HIGH:    "#b6f0d8",
  GOOD:    "#b6f0d8",
  NEUTRAL: T.border,
  CAUTION: "#fcd34d",
  BAD:     "#fca5a5",
}[s] || T.border);

// ── Sub-components ─────────────────────────────────────────────────────────
const StatBadge = ({ label, value, sub }) => (
  <div style={{
    background: T.surface, border: `1px solid ${T.border}`,
    borderRadius: 8, padding: "12px 18px", minWidth: 96,
    boxShadow: "0 1px 3px rgba(0,0,0,0.06)",
  }}>
    <div style={{ color: T.textSub, fontSize: 10, letterSpacing: "0.1em", fontWeight: 600, marginBottom: 4, textTransform: "uppercase" }}>{label}</div>
    <div style={{ color: T.text, fontSize: 24, fontWeight: 700, lineHeight: 1, fontVariantNumeric: "tabular-nums" }}>{value ?? "—"}</div>
    {sub && <div style={{ color: T.textFaint, fontSize: 10, marginTop: 3 }}>{sub}</div>}
  </div>
);

const Card = ({ children, style = {} }) => (
  <div style={{
    background: T.surface, border: `1px solid ${T.border}`,
    borderRadius: 10, padding: "20px",
    boxShadow: "0 1px 4px rgba(0,0,0,0.06)", ...style,
  }}>
    {children}
  </div>
);

const SectionLabel = ({ children }) => (
  <div style={{
    color: T.textSub, fontSize: 10, letterSpacing: "0.14em", fontWeight: 700,
    textTransform: "uppercase", marginBottom: 14, paddingBottom: 8,
    borderBottom: `1px solid ${T.border}`,
  }}>
    {children}
  </div>
);

const Spinner = () => (
  <div style={{ color: T.textSub, fontSize: 12, padding: 60, textAlign: "center" }}>
    Loading...
  </div>
);

const DistTooltip = ({ active, payload, ladder }) => {
  if (!active || !payload?.length) return null;
  const x = payload[0]?.payload?.x;
  const nearby = ladder?.find(p => Math.abs(p.line - x) < 0.6);
  return (
    <div style={{
      background: T.surface, border: `1px solid ${T.border}`,
      borderRadius: 6, padding: "8px 12px", fontSize: 12,
      boxShadow: "0 4px 12px rgba(0,0,0,0.1)",
    }}>
      <div style={{ color: T.textSub }}>Score: <span style={{ color: T.text, fontWeight: 600 }}>{x}</span></div>
      {nearby && <div style={{ color: T.accent, marginTop: 2, fontWeight: 600 }}>
        P(≥{nearby.line}) = {(nearby.probability * 100).toFixed(0)}%
      </div>}
    </div>
  );
};

const BarTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{
      background: T.surface, border: `1px solid ${T.border}`,
      borderRadius: 6, padding: "8px 12px", fontSize: 12,
      boxShadow: "0 4px 12px rgba(0,0,0,0.1)",
    }}>
      <div style={{ color: T.textSub, marginBottom: 4 }}>{label}</div>
      {payload.map((p, i) => (
        <div key={i} style={{ color: T.text, fontWeight: 600 }}>{p.name}: {p.value}</div>
      ))}
    </div>
  );
};

// ── Player Search ──────────────────────────────────────────────────────────
function PlayerSearch({ onSelect }) {
  const [query, setQuery]     = useState("");
  const [results, setResults] = useState([]);
  const [focused, setFocused] = useState(false);

  useEffect(() => {
    if (query.length < 2) { setResults([]); return; }
    const t = setTimeout(async () => {
      try {
        const r = await fetch(`${API}/players?q=${encodeURIComponent(query)}&limit=10`);
        const data = await r.json();
        setResults(data);
      } catch { setResults([]); }
    }, 250);
    return () => clearTimeout(t);
  }, [query]);

  const showDropdown = focused && results.length > 0;

  return (
    <div style={{ position: "relative", width: 280 }}>
      <div style={{ position: "relative" }}>
        <input
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder="Search player..."
          onFocus={() => setFocused(true)}
          onBlur={() => setTimeout(() => setFocused(false), 200)}
          style={{
            width: "100%", background: T.surface,
            border: `1.5px solid ${focused ? T.accent : T.border}`, borderRadius: 8,
            padding: "9px 14px 9px 36px", color: T.text,
            fontSize: 13, outline: "none", transition: "border-color 0.15s",
          }}
        />
        <span style={{ position: "absolute", left: 11, top: "50%", transform: "translateY(-50%)", color: T.textFaint, fontSize: 14 }}>🔍</span>
      </div>
      {showDropdown && (
        <div style={{
          position: "absolute", top: "calc(100% + 4px)", left: 0, right: 0, zIndex: 100,
          background: T.surface, border: `1px solid ${T.border}`, borderRadius: 8,
          boxShadow: "0 8px 24px rgba(0,0,0,0.12)", overflow: "hidden",
        }}>
          {results.map(p => (
            <div key={p.player_id}
              onMouseDown={() => { onSelect(p); setQuery(p.full_name); setFocused(false); setResults([]); }}
              style={{
                padding: "9px 14px", cursor: "pointer", fontSize: 13,
                borderBottom: `1px solid ${T.gridLine}`,
                display: "flex", justifyContent: "space-between", alignItems: "center",
              }}
              onMouseEnter={e => e.currentTarget.style.background = T.accentBg}
              onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
              <span style={{ color: T.text, fontWeight: 500 }}>{p.full_name}</span>
              <span style={{
                color: T.textSub, fontSize: 11, background: T.bg,
                padding: "2px 7px", borderRadius: 4, fontWeight: 600,
              }}>{p.team}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Main Dashboard ─────────────────────────────────────────────────────────
export default function PropDashboard() {
  const [activeStat, setActiveStat]     = useState("points");
  const [selectedLine, setSelectedLine] = useState(null);
  const [playerId, setPlayerId]         = useState(null);
  const [profile, setProfile]           = useState(null);
  const [gameLog, setGameLog]           = useState([]);
  const [simData, setSimData]           = useState(null);
  const [propsData, setPropsData]       = useState(null);
  const [flags, setFlags]               = useState([]);
  const [loading, setLoading]           = useState(false);
  const [error, setError]               = useState(null);

  const loadPlayer = useCallback(async (pid, stat) => {
    if (!pid) return;
    setLoading(true); setError(null);
    try {
      const [pRes, lRes, sRes, prRes] = await Promise.all([
        fetch(`${API}/players/${pid}/profile`),
        fetch(`${API}/players/${pid}/game-log?limit=10`),
        fetch(`${API}/players/${pid}/simulations?stat=${stat}`),
        fetch(`${API}/players/${pid}/props?stat=${stat}`),
      ]);
      if (!pRes.ok) throw new Error("Player not found");
      const [p, log, sim, props] = await Promise.all([
        pRes.json(), lRes.json(),
        sRes.ok ? sRes.json() : null,
        prRes.ok ? prRes.json() : null,
      ]);
      setProfile(p);
      setGameLog(Array.isArray(log) ? log : []);
      setSimData(sim);
      setPropsData(props);
      if (sim?.ladder?.length) {
        const closest = sim.ladder.reduce((prev, curr) =>
          Math.abs(curr.line - sim.mean) < Math.abs(prev.line - sim.mean) ? curr : prev
        );
        setSelectedLine(closest.line);
      }
      if (p.next_game_id) {
        const fRes = await fetch(`${API}/games/${p.next_game_id}/matchup-flags?player_id=${pid}`);
        if (fRes.ok) { const fd = await fRes.json(); setFlags(fd.flags || []); }
      } else { setFlags([]); }
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { if (playerId) loadPlayer(playerId, activeStat); }, [activeStat, playerId]);

  const handleSelect = (p) => { setPlayerId(p.player_id); loadPlayer(p.player_id, activeStat); };

  const ladder   = propsData?.lines || simData?.ladder || [];
  const selProp  = ladder.find(p => p.line === selectedLine);
  const logStat  = activeStat;
  const hit10    = selectedLine ? gameLog.filter(g => (g[logStat] ?? 0) >= selectedLine).length : 0;
  const bookKeys = selProp ? Object.keys(selProp.books || {}) : [];

  // Bar chart data with date label
  const barData = [...gameLog].reverse().map(g => ({
    ...g,
    label: `${formatDate(g.date)}\n${g.matchup}`,
    dateLabel: formatDate(g.date),
  }));

  return (
    <div style={{ background: T.bg, minHeight: "100vh", color: T.text, fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif" }}>
      <style>{`
        * { box-sizing: border-box; }
        ::-webkit-scrollbar { width: 5px; }
        ::-webkit-scrollbar-track { background: ${T.bg}; }
        ::-webkit-scrollbar-thumb { background: ${T.borderMid}; border-radius: 3px; }
        .prop-row:hover { background: ${T.accentBg} !important; cursor: pointer; }
        .stat-tab { transition: all 0.15s; cursor: pointer; border: none; }
        .flag-row:hover { background: rgba(0,0,0,0.02) !important; }
        .hover-row:hover { background: ${T.bg} !important; }
        input::placeholder { color: ${T.textFaint}; }
      `}</style>

      {/* ── Header ── */}
      <div style={{
        background: T.surface, borderBottom: `1px solid ${T.border}`,
        padding: "0 28px",
        boxShadow: "0 1px 4px rgba(0,0,0,0.06)",
      }}>
        <div style={{ maxWidth: 1400, margin: "0 auto", display: "flex", alignItems: "center", gap: 24, height: 58 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div style={{
              width: 28, height: 28, borderRadius: 7,
              background: `linear-gradient(135deg, ${T.accent}, ${T.blue})`,
              display: "flex", alignItems: "center", justifyContent: "center",
            }}>
              <span style={{ color: "#fff", fontSize: 14 }}>📊</span>
            </div>
            <span style={{ fontWeight: 800, fontSize: 16, color: T.text, letterSpacing: "-0.02em" }}>
              PropModel
            </span>
            <span style={{
              background: T.accentBg, color: T.accent,
              fontSize: 10, fontWeight: 700, padding: "2px 7px",
              borderRadius: 4, letterSpacing: "0.05em",
            }}>{CURRENT_SEASON}</span>
          </div>
          <PlayerSearch onSelect={handleSelect} />
          <div style={{ marginLeft: "auto", color: T.textFaint, fontSize: 11 }}>
            {propsData?.source === "model_only"
              ? <span style={{ color: T.warn, fontWeight: 600 }}>⚡ Model only — no sportsbook data</span>
              : <span style={{ color: T.accent, fontWeight: 600 }}>✓ Live sportsbook data</span>
            }
          </div>
        </div>
      </div>

      <div style={{ maxWidth: 1400, margin: "0 auto", padding: "24px 28px" }}>

        {!playerId && !loading && (
          <div style={{
            display: "flex", flexDirection: "column", alignItems: "center",
            justifyContent: "center", height: "60vh", gap: 12,
          }}>
            <div style={{ fontSize: 40 }}>🏀</div>
            <div style={{ color: T.textSub, fontSize: 15, fontWeight: 500 }}>Search for a player to begin</div>
            <div style={{ color: T.textFaint, fontSize: 13 }}>Type a player name in the search box above</div>
          </div>
        )}

        {error && (
          <div style={{
            background: T.dangerBg, border: `1px solid #fca5a5`,
            borderRadius: 8, padding: "12px 16px", color: T.danger, fontSize: 13, marginBottom: 20,
          }}>
            {error}
          </div>
        )}

        {loading && <Spinner />}

        {profile && !loading && (
          <>
            {/* ── Player header ── */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 20 }}>
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
                  <h1 style={{ margin: 0, fontSize: 32, fontWeight: 800, letterSpacing: "-0.03em", color: T.text }}>
                    {profile.full_name}
                  </h1>
                  {profile.is_active && (
                    <span style={{
                      background: T.accentBg, color: T.accentDark,
                      fontSize: 10, fontWeight: 700, padding: "3px 8px",
                      borderRadius: 5, letterSpacing: "0.05em",
                    }}>ACTIVE</span>
                  )}
                </div>
                <div style={{ color: T.textSub, fontSize: 13, display: "flex", gap: 8, alignItems: "center" }}>
                  <span style={{
                    background: T.bg, border: `1px solid ${T.border}`,
                    padding: "2px 8px", borderRadius: 4, fontWeight: 600, fontSize: 12,
                  }}>{profile.team}</span>
                  {profile.opponent && <><span style={{ color: T.textFaint }}>vs</span><span style={{ fontWeight: 600 }}>{profile.opponent}</span></>}
                  {profile.next_game_date && <span style={{ color: T.textFaint }}>· {formatDate(profile.next_game_date)}</span>}
                </div>
              </div>
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap", justifyContent: "flex-end" }}>
                <StatBadge label="L10 Avg"    value={profile.l10_avg_pts}        sub="pts" />
                <StatBadge label="L5 Avg"     value={profile.l5_avg_pts}         sub="pts" />
                <StatBadge label="Season Avg" value={profile.season_avg_pts}     sub="pts" />
                <StatBadge label="Min Proj"   value={profile.minutes_projection} sub="min" />
              </div>
            </div>

            {/* ── Stat tabs ── */}
            <div style={{ display: "flex", gap: 6, marginBottom: 20 }}>
              {["points", "rebounds", "assists"].map(s => (
                <button key={s} className="stat-tab" onClick={() => setActiveStat(s)} style={{
                  background: activeStat === s ? T.accent : T.surface,
                  color: activeStat === s ? "#fff" : T.textMid,
                  border: `1.5px solid ${activeStat === s ? T.accent : T.border}`,
                  borderRadius: 7, padding: "7px 20px",
                  fontSize: 12, fontWeight: 600,
                  letterSpacing: "0.04em", textTransform: "capitalize",
                  boxShadow: activeStat === s ? "0 2px 8px rgba(14,169,110,0.3)" : "none",
                }}>{s}</button>
              ))}
            </div>

            {/* ── Main grid ── */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 380px", gap: 20, marginBottom: 20 }}>

              {/* Left */}
              <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

                {/* Distribution chart */}
                {simData && (
                  <Card>
                    <SectionLabel>Monte Carlo Distribution · 10,000 Simulations</SectionLabel>
                    <div style={{ display: "flex", gap: 24, marginBottom: 16 }}>
                      <div>
                        <div style={{ color: T.textFaint, fontSize: 10, fontWeight: 600, letterSpacing: "0.08em", marginBottom: 2 }}>MEAN</div>
                        <div style={{ color: T.accent, fontSize: 20, fontWeight: 700 }}>{simData.mean}</div>
                      </div>
                      <div>
                        <div style={{ color: T.textFaint, fontSize: 10, fontWeight: 600, letterSpacing: "0.08em", marginBottom: 2 }}>STD DEV</div>
                        <div style={{ color: T.textMid, fontSize: 20, fontWeight: 700 }}>{simData.std_dev}</div>
                      </div>
                      {selectedLine && selProp && (
                        <div style={{
                          background: T.accentBg, border: `1px solid #b6f0d8`,
                          borderRadius: 8, padding: "8px 16px",
                        }}>
                          <div style={{ color: T.textFaint, fontSize: 10, fontWeight: 600, letterSpacing: "0.08em", marginBottom: 2 }}>P(≥{selectedLine})</div>
                          <div style={{ color: T.accentDark, fontSize: 20, fontWeight: 700 }}>
                            {selProp.model_prob ? `${(selProp.model_prob * 100).toFixed(0)}%` : "—"}
                          </div>
                        </div>
                      )}
                    </div>
                    <ResponsiveContainer width="100%" height={180}>
                      <AreaChart data={simData.curve} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
                        <defs>
                          <linearGradient id="dg" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%"  stopColor={T.accent} stopOpacity={0.25} />
                            <stop offset="95%" stopColor={T.accent} stopOpacity={0.02} />
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 4" stroke={T.gridLine} vertical={false} />
                        <XAxis dataKey="x" stroke={T.border} tick={{ fill: T.textFaint, fontSize: 10 }} tickLine={false} interval={9} />
                        <YAxis stroke="transparent" tick={false} />
                        <Tooltip content={<DistTooltip ladder={ladder} />} />
                        {selectedLine && (
                          <ReferenceLine x={selectedLine} stroke={T.accent} strokeWidth={2} strokeDasharray="5 3"
                            label={{ value: `${selectedLine}`, fill: T.accentDark, fontSize: 11, fontWeight: 600 }} />
                        )}
                        <ReferenceLine x={simData.mean} stroke={T.blue} strokeWidth={1.5} strokeDasharray="3 4"
                          label={{ value: "μ", fill: T.blue, fontSize: 11 }} />
                        {ladder.filter(p => p.line !== selectedLine).map(p => (
                          <ReferenceLine key={p.line} x={p.line} stroke={T.borderMid} strokeWidth={1} strokeDasharray="2 5" />
                        ))}
                        <Area type="monotone" dataKey="y" stroke={T.accent} strokeWidth={2} fill="url(#dg)" dot={false} />
                      </AreaChart>
                    </ResponsiveContainer>
                  </Card>
                )}

                {/* Bar chart */}
                {gameLog.length > 0 && (
                  <Card>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 14 }}>
                      <div>
                        <SectionLabel>Last {gameLog.length} Games · {activeStat.charAt(0).toUpperCase() + activeStat.slice(1)}</SectionLabel>
                      </div>
                      {selectedLine && (
                        <div style={{
                          background: hit10 / gameLog.length >= 0.6 ? T.accentBg : hit10 / gameLog.length >= 0.4 ? T.warnBg : T.dangerBg,
                          border: `1px solid ${hit10 / gameLog.length >= 0.6 ? "#b6f0d8" : hit10 / gameLog.length >= 0.4 ? "#fcd34d" : "#fca5a5"}`,
                          borderRadius: 6, padding: "4px 10px", fontSize: 12, fontWeight: 700,
                          color: hit10 / gameLog.length >= 0.6 ? T.accentDark : hit10 / gameLog.length >= 0.4 ? T.warn : T.danger,
                        }}>
                          {hit10}/{gameLog.length} hit {selectedLine}+ ({(hit10 / gameLog.length * 100).toFixed(0)}%)
                        </div>
                      )}
                    </div>
                    <ResponsiveContainer width="100%" height={180}>
                      <BarChart data={barData} margin={{ top: 4, right: 8, left: -20, bottom: 24 }}>
                        <CartesianGrid strokeDasharray="3 4" stroke={T.gridLine} vertical={false} />
                        <XAxis
                          dataKey="dateLabel"
                          stroke={T.border}
                          tick={{ fill: T.textSub, fontSize: 10, fontWeight: 500 }}
                          tickLine={false}
                          interval={0}
                          angle={-35}
                          textAnchor="end"
                          height={40}
                        />
                        <YAxis stroke="transparent" tick={{ fill: T.textFaint, fontSize: 10 }} />
                        <Tooltip content={<BarTooltip />} />
                        {selectedLine && (
                          <ReferenceLine y={selectedLine} stroke={T.accent} strokeWidth={1.5} strokeDasharray="5 3"
                            label={{ value: `${selectedLine}`, fill: T.accentDark, fontSize: 10, fontWeight: 600, position: "right" }} />
                        )}
                        <Bar dataKey={logStat} name={activeStat.charAt(0).toUpperCase() + activeStat.slice(1)} radius={[4, 4, 0, 0]}>
                          {barData.map((g, i) => (
                            <Cell key={i} fill={selectedLine && (g[logStat] ?? 0) >= selectedLine ? T.barHit : T.barMiss} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </Card>
                )}

                {/* Game log table */}
                {gameLog.length > 0 && (
                  <Card style={{ padding: 0, overflow: "hidden" }}>
                    <div style={{ padding: "16px 20px 0" }}>
                      <SectionLabel>Game Log · Last {gameLog.length}</SectionLabel>
                    </div>
                    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                      <thead>
                        <tr style={{ background: T.bg }}>
                          {["Date", "Matchup", "Min", "Pts", "Reb", "Ast", "Stl", "Blk", "Tov"].map(h => (
                            <th key={h} style={{
                              textAlign: "right", padding: "8px 12px",
                              fontWeight: 600, fontSize: 10, color: T.textSub,
                              letterSpacing: "0.06em", textTransform: "uppercase",
                              borderBottom: `1px solid ${T.border}`,
                            }}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {gameLog.map((g, i) => (
                          <tr key={i} className="hover-row" style={{ borderBottom: `1px solid ${T.gridLine}` }}>
                            <td style={{ padding: "8px 12px", color: T.textSub, textAlign: "right", fontSize: 11 }}>
                              {formatDate(g.date)}
                            </td>
                            <td style={{ padding: "8px 12px", color: T.textMid, textAlign: "right", fontWeight: 500 }}>
                              {g.matchup}
                            </td>
                            <td style={{ padding: "8px 12px", color: T.textSub, textAlign: "right" }}>{g.minutes}</td>
                            {["points", "rebounds", "assists", "steals", "blocks", "turnovers"].map(s => (
                              <td key={s} style={{
                                padding: "8px 12px", textAlign: "right",
                                fontWeight: s === logStat ? 700 : 400,
                                color: s === logStat
                                  ? (selectedLine && g[s] >= selectedLine ? T.accent
                                    : selectedLine && g[s] >= selectedLine * 0.85 ? T.warn : T.text)
                                  : T.textSub,
                              }}>
                                {g[s] ?? "—"}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </Card>
                )}
              </div>

              {/* Right column */}
              <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

                {/* Matchup flags */}
                <Card>
                  <SectionLabel>Matchup Intelligence{profile.opponent ? ` · vs ${profile.opponent}` : ""}</SectionLabel>
                  {flags.length === 0 ? (
                    <div style={{ color: T.textFaint, fontSize: 12, padding: "8px 0" }}>
                      {profile.opponent ? "No flags — data still building." : "No upcoming game found."}
                    </div>
                  ) : (
                    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                      {flags.map((flag, i) => (
                        <div key={i} className="flag-row" style={{
                          display: "flex", alignItems: "flex-start", gap: 10,
                          padding: "10px 12px", borderRadius: 7,
                          border: `1px solid ${severityBorder(flag.severity)}`,
                          background: severityBg(flag.severity),
                        }}>
                          <span style={{ fontSize: 16, lineHeight: 1.4 }}>{flag.icon}</span>
                          <div>
                            <div style={{ color: severityColor(flag.severity), fontSize: 9, fontWeight: 700, letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 2 }}>
                              {flag.type}
                            </div>
                            <div style={{ color: T.textMid, fontSize: 12, lineHeight: 1.5 }}>{flag.label}</div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </Card>

                {/* Prop ladder */}
                <Card>
                  <SectionLabel>Alternate Lines · Click to Analyze</SectionLabel>

                  {selProp && (
                    <div style={{
                      background: T.accentBg, border: `1px solid #b6f0d8`,
                      borderRadius: 8, padding: "14px 16px", marginBottom: 16,
                    }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                        <div>
                          <span style={{ color: T.textSub, fontSize: 11 }}>Line </span>
                          <span style={{ color: T.text, fontSize: 24, fontWeight: 800 }}>{selProp.line}</span>
                          <span style={{ color: T.textSub, fontSize: 12, marginLeft: 4 }}>{activeStat.slice(0, 3)}</span>
                        </div>
                        <div style={{ textAlign: "right" }}>
                          <div style={{ color: T.textSub, fontSize: 10, fontWeight: 600, letterSpacing: "0.08em", marginBottom: 2 }}>MODEL PROB</div>
                          <div style={{ color: T.accentDark, fontSize: 22, fontWeight: 800 }}>
                            {selProp.model_prob ? `${(selProp.model_prob * 100).toFixed(0)}%` : "—"}
                          </div>
                        </div>
                      </div>
                      <div style={{ display: "flex", gap: 8 }}>
                        <div style={{ flex: 1, background: T.surface, borderRadius: 6, padding: "8px 10px", border: `1px solid ${T.border}` }}>
                          <div style={{ color: T.textFaint, fontSize: 9, fontWeight: 600, letterSpacing: "0.08em", marginBottom: 3 }}>FAIR ODDS</div>
                          <div style={{ color: T.text, fontSize: 15, fontWeight: 700 }}>{formatOdds(selProp.fair_odds)}</div>
                        </div>
                        {bookKeys.slice(0, 2).map(book => (
                          <div key={book} style={{ flex: 1, background: T.surface, borderRadius: 6, padding: "8px 10px", border: `1px solid ${T.border}` }}>
                            <div style={{ color: T.textFaint, fontSize: 9, fontWeight: 600, letterSpacing: "0.08em", marginBottom: 3 }}>
                              {book.toUpperCase().slice(0, 6)} EDGE
                            </div>
                            <div style={{ color: edgeColor(selProp.books[book].edge), fontSize: 15, fontWeight: 700 }}>
                              {selProp.books[book].edge !== null
                                ? `${selProp.books[book].edge > 0 ? "+" : ""}${selProp.books[book].edge}%`
                                : "—"}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                    <thead>
                      <tr style={{ background: T.bg }}>
                        {["Line", "Model", "Fair", ...(propsData?.source !== "model_only" ? bookKeys.slice(0, 2).map(b => b.slice(0, 6)) : []), "Edge"].map(h => (
                          <th key={h} style={{
                            textAlign: "right", padding: "6px 8px",
                            fontWeight: 600, fontSize: 9, color: T.textSub,
                            letterSpacing: "0.08em", textTransform: "uppercase",
                            borderBottom: `1px solid ${T.border}`,
                          }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {ladder.map((p, i) => {
                        const isSelected = p.line === selectedLine;
                        const bArr = Object.values(p.books || {});
                        const topEdge = bArr.length ? Math.max(...bArr.map(b => b.edge ?? -99)) : null;
                        return (
                          <tr key={i} className="prop-row" onClick={() => setSelectedLine(p.line)}
                            style={{
                              borderBottom: `1px solid ${T.gridLine}`,
                              background: isSelected ? T.accentBg : "transparent",
                            }}>
                            <td style={{
                              padding: "8px 8px", textAlign: "right",
                              fontWeight: isSelected ? 700 : 500,
                              color: isSelected ? T.accentDark : T.textMid,
                            }}>{p.line}+</td>
                            <td style={{ padding: "8px 8px", textAlign: "right", color: T.accent, fontWeight: 700 }}>
                              {p.model_prob ? `${(p.model_prob * 100).toFixed(0)}%` : "—"}
                            </td>
                            <td style={{ padding: "8px 8px", textAlign: "right", color: T.textSub }}>
                              {formatOdds(p.fair_odds)}
                            </td>
                            {propsData?.source !== "model_only" && bookKeys.slice(0, 2).map(book => (
                              <td key={book} style={{ padding: "8px 8px", textAlign: "right", color: T.textSub }}>
                                {p.books?.[book] ? formatOdds(p.books[book].over_odds) : "—"}
                              </td>
                            ))}
                            <td style={{ padding: "8px 8px", textAlign: "right", fontWeight: 700, color: edgeColor(topEdge) }}>
                              {topEdge !== null && topEdge > -99 ? `${topEdge > 0 ? "+" : ""}${topEdge}%` : "—"}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </Card>

                {/* Model info */}
                <Card>
                  <SectionLabel>Model Info</SectionLabel>
                  <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                    {[
                      { label: "Games in sample",    value: profile.games_played },
                      { label: "Points projection",  value: profile.points_projection ? `${profile.points_projection} pts` : "—" },
                      { label: "Minutes projection", value: profile.minutes_projection ? `${profile.minutes_projection} min` : "—" },
                      { label: "Simulations",        value: "10,000" },
                      { label: "Model version",      value: "v2 — context adjusted" },
                    ].map((item, i) => (
                      <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <span style={{ color: T.textSub, fontSize: 12 }}>{item.label}</span>
                        <span style={{ color: T.text, fontSize: 12, fontWeight: 600 }}>{item.value}</span>
                      </div>
                    ))}
                  </div>
                </Card>
              </div>
            </div>

            <div style={{ borderTop: `1px solid ${T.border}`, paddingTop: 14, display: "flex", justifyContent: "space-between" }}>
              <div style={{ color: T.textFaint, fontSize: 10 }}>Data: NBA.com · Odds: SportsGameOdds · Model: Monte Carlo v2</div>
              <div style={{ color: T.textFaint, fontSize: 10 }}>For analytical use only</div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
