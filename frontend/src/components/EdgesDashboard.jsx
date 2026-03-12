import { useState, useEffect } from "react";

const API = "http://localhost:8000";

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
};

const STATS = ["all", "points", "rebounds", "assists", "steals", "blocks", "PRA", "PR", "PA", "SB"];

const STAT_LABEL = {
  points: "PTS", rebounds: "REB", assists: "AST",
  steals: "STL", blocks: "BLK", PRA: "PRA", PR: "PR", PA: "PA", SB: "SB",
};

const formatOdds = (n) => {
  if (n == null) return "—";
  return n > 0 ? `+${n}` : `${n}`;
};

const edgeColor = (edge) => {
  if (edge == null) return T.textSub;
  if (edge >= 7)  return T.accent;
  if (edge >= 4)  return "#16a34a";
  if (edge >= 2)  return "#65a30d";
  if (edge <= -5) return T.danger;
  if (edge <= -2) return "#ea580c";
  return T.textSub;
};

const probColor = (p) => {
  if (p >= 0.75) return T.accent;
  if (p >= 0.65) return "#16a34a";
  if (p >= 0.55) return T.textMid;
  return T.textSub;
};

function ProbBar({ probability }) {
  const pct = Math.round((probability || 0) * 100);
  const color = probColor(probability);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div style={{
        width: 80, height: 6, background: T.gridLine,
        borderRadius: 3, overflow: "hidden", flexShrink: 0,
      }}>
        <div style={{
          width: `${pct}%`, height: "100%",
          background: color, borderRadius: 3,
          transition: "width 0.3s ease",
        }} />
      </div>
      <span style={{ fontSize: 13, fontWeight: 700, color, fontVariantNumeric: "tabular-nums", minWidth: 36 }}>
        {pct}%
      </span>
    </div>
  );
}

export default function EdgesDashboard({ onPlayerSelect }) {
  const [data,        setData]        = useState(null);
  const [loading,     setLoading]     = useState(true);
  const [error,       setError]       = useState(null);
  const [statFilter,  setStatFilter]  = useState("all");
  const [minProb,     setMinProb]     = useState(60);
  const [sortBy,      setSortBy]      = useState("edge"); // "edge" | "prob" | "line"
  const [groupBy,     setGroupBy]     = useState("player"); // "player" | "matchup" | "stat"

  const load = async (prob) => {
    setLoading(true); setError(null);
    try {
      const statParam = statFilter !== "all" ? `&stat=${statFilter}` : "";
      const r = await fetch(`${API}/edges/today?min_probability=${(prob || minProb) / 100}${statParam}`);
      if (!r.ok) throw new Error(`API error ${r.status}`);
      setData(await r.json());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [statFilter]);

  const edges = data?.edges || [];

  // Client-side safety filter: remove lines with fair odds worse than -1000
  const filtered = edges.filter(e => e.fair_odds == null || e.fair_odds > -1000);

  // Sort
  const sorted = [...filtered].sort((a, b) => {
    if (sortBy === "edge") {
      const ae = a.edge_percent ?? (a.model_probability * 100 - 60);
      const be = b.edge_percent ?? (b.model_probability * 100 - 60);
      return be - ae;
    }
    if (sortBy === "prob") return b.model_probability - a.model_probability;
    if (sortBy === "line") return b.line - a.line;
    return 0;
  });

  // Group
  const grouped = {};
  for (const edge of sorted) {
    let key;
    if (groupBy === "matchup") key = edge.matchup;
    else if (groupBy === "stat") key = STAT_LABEL[edge.stat] || edge.stat;
    else key = edge.player_name;

    if (!grouped[key]) grouped[key] = [];
    grouped[key].push(edge);
  }

  const hasBookData = data?.source === "sportsbook";

  return (
    <div style={{
      background: T.bg, minHeight: "100vh", color: T.text,
      fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
      padding: "28px",
    }}>
      <div style={{ maxWidth: 1200, margin: "0 auto" }}>

        {/* Header */}
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 20, flexWrap: "wrap", gap: 12 }}>
          <div>
            <div style={{ fontSize: 18, fontWeight: 700, color: T.text, letterSpacing: "-0.02em" }}>
              Best Edges
              {data?.date && (
                <span style={{ fontSize: 13, fontWeight: 400, color: T.textSub, marginLeft: 10 }}>
                  {data.is_today ? "Today" : data.date}
                  {!data.is_today && <span style={{ color: T.warn, marginLeft: 6, fontSize: 11, fontWeight: 600 }}>⚠ not today's games</span>}
                </span>
              )}
            </div>
            <div style={{ fontSize: 12, color: T.textSub, marginTop: 3 }}>
              {hasBookData
                ? `${edges.length} edges vs sportsbook — sorted by edge %`
                : `${edges.length} model projections — no sportsbook data loaded yet`
              }
            </div>
          </div>
          <button
            onClick={() => load()}
            style={{
              background: T.surface, border: `1px solid ${T.border}`,
              borderRadius: 8, padding: "7px 14px", fontSize: 12,
              color: T.text, cursor: "pointer", fontWeight: 500,
            }}
          >↻ Refresh</button>
        </div>

        {!hasBookData && (
          <div style={{
            background: T.warnBg, border: `1px solid #fcd34d`,
            borderRadius: 8, padding: "10px 16px", marginBottom: 16,
            fontSize: 12, color: T.warn, display: "flex", alignItems: "center", gap: 8,
          }}>
            <span style={{ fontWeight: 700 }}>⚡ Model-only mode</span>
            — Sportsbook props not loaded. Showing model probabilities and fair odds only.
            Edge % requires sportsbook data (run props ingestion on a game day).
          </div>
        )}

        {error && (
          <div style={{
            background: T.dangerBg, border: `1px solid #fca5a5`,
            borderRadius: 8, padding: "10px 16px", marginBottom: 16,
            fontSize: 12, color: T.danger,
          }}>
            {error}
          </div>
        )}

        {/* Controls */}
        <div style={{ display: "flex", gap: 12, marginBottom: 20, flexWrap: "wrap", alignItems: "center" }}>

          {/* Stat filter */}
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
            {STATS.map(s => (
              <button key={s} onClick={() => setStatFilter(s)} style={{
                padding: "5px 12px", borderRadius: 6, fontSize: 12, fontWeight: 600,
                cursor: "pointer",
                background: statFilter === s ? T.accentBg : T.surface,
                color: statFilter === s ? T.accent : T.textSub,
                border: statFilter === s ? `1px solid #b6f0d8` : `1px solid ${T.border}`,
              }}>
                {s === "all" ? "All" : (STAT_LABEL[s] || s)}
              </button>
            ))}
          </div>

          <div style={{ marginLeft: "auto", display: "flex", gap: 12, alignItems: "center" }}>
            {/* Min probability */}
            <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: T.textSub }}>
              <span>Min prob</span>
              <select
                value={minProb}
                onChange={e => { setMinProb(+e.target.value); load(+e.target.value); }}
                style={{
                  background: T.surface, border: `1px solid ${T.border}`,
                  borderRadius: 6, padding: "4px 8px", fontSize: 12, color: T.text,
                }}
              >
                {[50, 55, 60, 65, 70, 75].map(v => (
                  <option key={v} value={v}>{v}%</option>
                ))}
              </select>
            </div>

            {/* Sort */}
            <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: T.textSub }}>
              <span>Sort</span>
              <select
                value={sortBy}
                onChange={e => setSortBy(e.target.value)}
                style={{
                  background: T.surface, border: `1px solid ${T.border}`,
                  borderRadius: 6, padding: "4px 8px", fontSize: 12, color: T.text,
                }}
              >
                <option value="edge">{hasBookData ? "Edge %" : "Probability"}</option>
                <option value="prob">Model probability</option>
                <option value="line">Line size</option>
              </select>
            </div>

            {/* Group */}
            <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: T.textSub }}>
              <span>Group</span>
              <select
                value={groupBy}
                onChange={e => setGroupBy(e.target.value)}
                style={{
                  background: T.surface, border: `1px solid ${T.border}`,
                  borderRadius: 6, padding: "4px 8px", fontSize: 12, color: T.text,
                }}
              >
                <option value="player">Player</option>
                <option value="matchup">Matchup</option>
                <option value="stat">Stat</option>
              </select>
            </div>
          </div>
        </div>

        {loading && (
          <div style={{ textAlign: "center", color: T.textSub, padding: 60, fontSize: 13 }}>Loading...</div>
        )}

        {!loading && edges.length === 0 && (
          <div style={{ textAlign: "center", color: T.textSub, padding: 60, fontSize: 13 }}>
            No edges found for the current filters.
          </div>
        )}

        {/* Edge groups */}
        {!loading && Object.entries(grouped).map(([groupKey, groupEdges]) => (
          <div key={groupKey} style={{ marginBottom: 20 }}>
            {/* Group header */}
            <div style={{
              display: "flex", alignItems: "center", gap: 10,
              marginBottom: 8,
            }}>
              <span style={{ fontSize: 13, fontWeight: 700, color: T.text }}>{groupKey}</span>
              {groupBy === "player" && groupEdges[0] && (
                <>
                  <span style={{
                    fontSize: 10, fontWeight: 700, color: T.textSub,
                    background: T.bg, padding: "2px 7px", borderRadius: 4,
                  }}>
                    {groupEdges[0].team}
                  </span>
                  <span style={{ fontSize: 11, color: T.textFaint }}>{groupEdges[0].matchup}</span>
                  <button
                    onClick={() => onPlayerSelect && onPlayerSelect({ player_id: groupEdges[0].player_id, full_name: groupKey })}
                    style={{
                      fontSize: 10, color: T.blue, background: T.blueBg,
                      border: `1px solid #bfdbfe`, borderRadius: 4,
                      padding: "2px 8px", cursor: "pointer", fontWeight: 600,
                      marginLeft: 4,
                    }}
                  >
                    View profile →
                  </button>
                </>
              )}
              {groupBy === "matchup" && (
                <span style={{ fontSize: 11, color: T.textFaint }}>{groupEdges.length} props</span>
              )}
            </div>

            {/* Edge cards */}
            <div style={{
              background: T.surface, border: `1px solid ${T.border}`,
              borderRadius: 10, overflow: "hidden",
              boxShadow: "0 1px 4px rgba(0,0,0,0.06)",
            }}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr style={{ background: T.bg }}>
                    {groupBy !== "stat" && (
                      <th style={thStyle}>Stat</th>
                    )}
                    {groupBy !== "player" && (
                      <th style={thStyle}>Player</th>
                    )}
                    <th style={thStyle}>Book Line</th>
                    <th style={thStyle}>Model Proj</th>
                    <th style={thStyle}>Model Prob</th>
                    <th style={thStyle}>Fair Odds</th>
                    {hasBookData && <>
                      <th style={thStyle}>Book</th>
                      <th style={thStyle}>Book Odds</th>
                      <th style={{ ...thStyle, textAlign: "right" }}>Edge</th>
                    </>}
                  </tr>
                </thead>
                <tbody>
                  {groupEdges.map((e, i) => (
                    <tr key={`${e.player_id}-${e.stat}-${e.line}-${e.book}-${i}`}
                      style={{
                        borderTop: i > 0 ? `1px solid ${T.gridLine}` : "none",
                        background: i % 2 === 1 ? T.bg : T.surface,
                      }}>
                      {groupBy !== "stat" && (
                        <td style={tdStyle}>
                          <span style={{
                            background: statTagBg(e.stat), color: statTagColor(e.stat),
                            fontSize: 10, fontWeight: 700, padding: "2px 8px",
                            borderRadius: 4, letterSpacing: "0.05em",
                          }}>
                            {STAT_LABEL[e.stat] || e.stat}
                          </span>
                        </td>
                      )}
                      {groupBy !== "player" && (
                        <td style={tdStyle}>
                          <span
                            onClick={() => onPlayerSelect && onPlayerSelect({ player_id: e.player_id, full_name: e.player_name })}
                            style={{ color: T.blue, fontWeight: 600, cursor: "pointer", fontSize: 13 }}
                          >
                            {e.player_name}
                          </span>
                          <span style={{ color: T.textFaint, fontSize: 11, marginLeft: 6 }}>{e.team}</span>
                        </td>
                      )}
                      <td style={{ ...tdStyle, fontWeight: 700, color: T.text, fontVariantNumeric: "tabular-nums" }}>
                        {e.line}+
                      </td>
                      <td style={{ ...tdStyle, fontVariantNumeric: "tabular-nums" }}>
                        {e.model_mean != null ? (
                          <span style={{
                            color: e.model_mean > e.line ? T.accent : e.model_mean < e.line ? T.danger : T.textSub,
                            fontWeight: 600,
                          }}>
                            {e.model_mean}
                            <span style={{ fontSize: 10, fontWeight: 400, marginLeft: 4, color: T.textFaint }}>
                              proj
                            </span>
                          </span>
                        ) : <span style={{ color: T.textFaint }}>—</span>}
                      </td>
                      <td style={tdStyle}>
                        <ProbBar probability={e.model_probability} />
                      </td>
                      <td style={{ ...tdStyle, color: T.textMid, fontVariantNumeric: "tabular-nums" }}>
                        {formatOdds(e.fair_odds)}
                      </td>
                      {hasBookData && <>
                        <td style={{ ...tdStyle, color: T.textSub, fontSize: 11 }}>
                          {e.book || "—"}
                        </td>
                        <td style={{ ...tdStyle, color: T.textMid, fontVariantNumeric: "tabular-nums" }}>
                          {formatOdds(e.sportsbook_odds)}
                        </td>
                        <td style={{ ...tdStyle, textAlign: "right", fontWeight: 700, color: edgeColor(e.edge_percent), fontVariantNumeric: "tabular-nums" }}>
                          {e.edge_percent != null ? `${e.edge_percent > 0 ? "+" : ""}${e.edge_percent}%` : "—"}
                        </td>
                      </>}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

const thStyle = {
  padding: "7px 14px", textAlign: "left",
  fontSize: 10, fontWeight: 700, color: T.textSub,
  textTransform: "uppercase", letterSpacing: "0.08em",
  borderBottom: `1px solid ${T.border}`,
};

const tdStyle = {
  padding: "10px 14px", fontSize: 13, color: T.textMid,
};

const STAT_COLORS = {
  points:   { bg: "#eff6ff", color: "#2563eb" },
  rebounds: { bg: "#f0fdf4", color: "#16a34a" },
  assists:  { bg: "#fefce8", color: "#ca8a04" },
  steals:   { bg: "#fff7ed", color: "#ea580c" },
  blocks:   { bg: "#fdf4ff", color: "#9333ea" },
  PRA:      { bg: "#f0f9ff", color: "#0284c7" },
  PR:       { bg: "#f0fdf4", color: "#15803d" },
  PA:       { bg: "#fefce8", color: "#b45309" },
  SB:       { bg: "#fff1f2", color: "#e11d48" },
};

const statTagBg    = (s) => STAT_COLORS[s]?.bg    || T.bg;
const statTagColor = (s) => STAT_COLORS[s]?.color || T.textSub;
