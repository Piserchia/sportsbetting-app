import { useState, useEffect, useCallback } from "react";

const API = "http://localhost:8000";

const T = {
  bg: "#f4f5f7", surface: "#ffffff", card: "#ffffff",
  border: "#e2e4e9", text: "#1a1d23", textMid: "#4a5568",
  textSub: "#8a94a6", textFaint: "#b8bfcc",
  accent: "#0ea96e", accentBg: "#e8faf3",
  blue: "#2563eb", blueBg: "#eff6ff",
  warn: "#d97706", warnBg: "#fffbeb",
  danger: "#dc2626", dangerBg: "#fef2f2",
  red: "#dc2626", green: "#0ea96e",
};

const STATS = ["All", "points", "rebounds", "assists", "steals", "blocks"];
const POSITIONS = ["All", "PG", "SG", "SF", "PF", "C"];

const resultColor = (r) => {
  if (r === "win") return T.green;
  if (r === "loss") return T.red;
  if (r === "push") return T.warn;
  return T.textFaint;
};

const resultBg = (r) => {
  if (r === "win") return T.accentBg;
  if (r === "loss") return T.dangerBg;
  if (r === "push") return T.warnBg;
  return "#f0f1f4";
};

const wrColor = (wr) => {
  if (wr >= 55) return T.green;
  if (wr >= 50) return T.text;
  return T.red;
};

const roiColor = (roi) => roi > 0 ? T.green : roi < 0 ? T.red : T.text;

function StatCard({ label, value, sub, color }) {
  return (
    <div style={{
      background: T.card, borderRadius: 12, border: `1px solid ${T.border}`,
      padding: "20px 24px", flex: 1, minWidth: 140,
    }}>
      <div style={{ fontSize: 12, color: T.textSub, fontWeight: 500, marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 26, fontWeight: 700, color: color || T.text, letterSpacing: "-0.02em" }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: T.textFaint, marginTop: 4 }}>{sub}</div>}
    </div>
  );
}

function FilterSelect({ label, value, options, onChange }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <span style={{ fontSize: 12, color: T.textSub, fontWeight: 500 }}>{label}:</span>
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        style={{
          background: T.surface, border: `1px solid ${T.border}`, borderRadius: 6,
          padding: "5px 10px", fontSize: 12, color: T.text, cursor: "pointer",
          outline: "none",
        }}
      >
        {options.map(o => (
          <option key={o} value={o}>{o === "All" ? "All" : o.charAt(0).toUpperCase() + o.slice(1)}</option>
        ))}
      </select>
    </div>
  );
}

function SectionCard({ title, children, style = {} }) {
  return (
    <div style={{
      background: T.card, borderRadius: 12, border: `1px solid ${T.border}`,
      marginBottom: 24, overflow: "hidden", ...style,
    }}>
      <div style={{ padding: "14px 20px", borderBottom: `1px solid ${T.border}`, fontSize: 14, fontWeight: 600, color: T.text }}>
        {title}
      </div>
      {children}
    </div>
  );
}

const thStyle = {
  padding: "10px 14px", textAlign: "left", fontSize: 11, fontWeight: 600,
  color: T.textSub, borderBottom: `1px solid ${T.border}`, background: "#fafbfc",
  whiteSpace: "nowrap",
};

const tdStyle = { padding: "10px 14px", fontSize: 13, color: T.text };

export default function BetPerformanceDashboard() {
  const [perf, setPerf] = useState(null);
  const [bets, setBets] = useState([]);
  const [models, setModels] = useState([]);
  const [byType, setByType] = useState([]);
  const [byPosition, setByPosition] = useState([]);
  const [matrix, setMatrix] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filterStat, setFilterStat] = useState("All");
  const [filterPos, setFilterPos] = useState("All");

  const loadAnalytics = useCallback(() => {
    Promise.all([
      fetch(`${API}/bets/performance`).then(r => r.json()),
      fetch(`${API}/bets/by-model`).then(r => r.json()),
      fetch(`${API}/bets/by-type`).then(r => r.json()),
      fetch(`${API}/bets/by-position`).then(r => r.json()),
      fetch(`${API}/bets/type-position-matrix`).then(r => r.json()),
    ]).then(([p, m, t, pos, mx]) => {
      setPerf(p);
      setModels(m.models || []);
      setByType(t.types || []);
      setByPosition(pos.positions || []);
      setMatrix(mx.matrix || []);
    }).catch(() => {});
  }, []);

  const loadBets = useCallback(() => {
    const params = new URLSearchParams({ limit: "200" });
    if (filterStat !== "All") params.set("stat", filterStat);
    if (filterPos !== "All") params.set("position", filterPos);
    fetch(`${API}/bets/recent?${params}`).then(r => r.json())
      .then(b => setBets(b.bets || []))
      .catch(() => {});
  }, [filterStat, filterPos]);

  const load = useCallback(() => {
    setLoading(true);
    Promise.all([loadAnalytics(), loadBets()])
      .finally(() => setLoading(false));
  }, [loadAnalytics, loadBets]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { loadBets(); }, [filterStat, filterPos, loadBets]);

  const handleReset = () => {
    if (!window.confirm("Are you sure you want to delete all tracked bet history?")) return;
    fetch(`${API}/bets/reset`, { method: "POST" })
      .then(r => r.json())
      .then(() => load())
      .catch(() => {});
  };

  if (loading) {
    return <div style={{ padding: 60, textAlign: "center", color: T.textSub }}>Loading...</div>;
  }

  // Build heatmap data structure
  const heatmapStats = [...new Set(matrix.map(m => m.stat))];
  const heatmapPositions = POSITIONS.filter(p => p !== "All");
  const heatmapLookup = {};
  matrix.forEach(m => { heatmapLookup[`${m.stat}_${m.position}`] = m; });

  const heatmapCellColor = (wr) => {
    if (wr === null || wr === undefined) return "#f8f9fb";
    if (wr >= 58) return "#d1fae5";
    if (wr >= 54) return "#e8faf3";
    if (wr >= 50) return "#fefce8";
    if (wr >= 45) return "#fff7ed";
    return "#fef2f2";
  };

  return (
    <div style={{ maxWidth: 1200, margin: "0 auto", padding: "24px 28px" }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 24 }}>
        <div>
          <div style={{ fontSize: 18, fontWeight: 700, color: T.text }}>Bet Performance</div>
          <div style={{ fontSize: 12, color: T.textSub, marginTop: 2 }}>
            Track model recommendations and outcomes over time
          </div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button onClick={load} style={{
            background: T.surface, border: `1px solid ${T.border}`, borderRadius: 8,
            padding: "7px 14px", fontSize: 12, color: T.text, cursor: "pointer", fontWeight: 500,
          }}>Refresh</button>
          <button onClick={handleReset} style={{
            background: T.dangerBg, border: `1px solid #fca5a5`, borderRadius: 8,
            padding: "7px 14px", fontSize: 12, color: T.danger, cursor: "pointer", fontWeight: 500,
          }}>Reset Tracking</button>
        </div>
      </div>

      {/* Performance Cards */}
      <div style={{ display: "flex", gap: 12, marginBottom: 24, flexWrap: "wrap" }}>
        <StatCard label="Total Bets" value={perf?.total_bets ?? 0} sub={`${perf?.pending ?? 0} pending`} />
        <StatCard label="Win Rate" value={`${perf?.win_rate ?? 0}%`}
          sub={`${perf?.wins ?? 0}W / ${perf?.losses ?? 0}L / ${perf?.pushes ?? 0}P`}
          color={perf?.win_rate > 50 ? T.green : perf?.win_rate > 0 ? T.text : T.textSub} />
        <StatCard label="ROI" value={`${perf?.roi > 0 ? "+" : ""}${perf?.roi ?? 0}%`}
          color={roiColor(perf?.roi ?? 0)} />
        <StatCard label="Avg CLV" value={perf?.avg_clv != null ? `${perf.avg_clv > 0 ? "+" : ""}${perf.avg_clv}` : "N/A"} />
      </div>

      {/* Performance by Bet Type + Position — side by side */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20, marginBottom: 0 }}>
        {/* By Bet Type */}
        {byType.length > 0 && (
          <SectionCard title="Performance by Stat Type">
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead><tr>
                {["Stat", "Bets", "Win Rate", "ROI"].map(h => <th key={h} style={thStyle}>{h}</th>)}
              </tr></thead>
              <tbody>
                {byType.map(t => (
                  <tr key={t.stat} style={{ borderBottom: `1px solid ${T.border}` }}>
                    <td style={{ ...tdStyle, fontWeight: 600, textTransform: "capitalize" }}>{t.stat}</td>
                    <td style={tdStyle}>{t.bets}</td>
                    <td style={{ ...tdStyle, color: wrColor(t.win_rate), fontWeight: 600 }}>{t.win_rate}%</td>
                    <td style={{ ...tdStyle, color: roiColor(t.roi), fontWeight: 600 }}>
                      {t.roi > 0 ? "+" : ""}{t.roi}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </SectionCard>
        )}

        {/* By Position */}
        {byPosition.length > 0 && (
          <SectionCard title="Performance by Position">
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead><tr>
                {["Position", "Bets", "Win Rate", "ROI"].map(h => <th key={h} style={thStyle}>{h}</th>)}
              </tr></thead>
              <tbody>
                {byPosition.map(p => (
                  <tr key={p.position} style={{ borderBottom: `1px solid ${T.border}` }}>
                    <td style={{ ...tdStyle, fontWeight: 600 }}>{p.position}</td>
                    <td style={tdStyle}>{p.bets}</td>
                    <td style={{ ...tdStyle, color: wrColor(p.win_rate), fontWeight: 600 }}>{p.win_rate}%</td>
                    <td style={{ ...tdStyle, color: roiColor(p.roi), fontWeight: 600 }}>
                      {p.roi > 0 ? "+" : ""}{p.roi}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </SectionCard>
        )}
      </div>

      {/* Heatmap: Stat vs Position */}
      {matrix.length > 0 && (
        <SectionCard title="Win Rate: Stat Type vs Position">
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  <th style={{ ...thStyle, minWidth: 90 }}>Stat</th>
                  {heatmapPositions.map(p => (
                    <th key={p} style={{ ...thStyle, textAlign: "center", minWidth: 64 }}>{p}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {heatmapStats.map(stat => (
                  <tr key={stat} style={{ borderBottom: `1px solid ${T.border}` }}>
                    <td style={{ ...tdStyle, fontWeight: 600, textTransform: "capitalize" }}>{stat}</td>
                    {heatmapPositions.map(pos => {
                      const cell = heatmapLookup[`${stat}_${pos}`];
                      const wr = cell?.win_rate;
                      return (
                        <td key={pos} style={{
                          ...tdStyle, textAlign: "center", fontWeight: 600,
                          background: heatmapCellColor(wr),
                          color: wr != null ? wrColor(wr) : T.textFaint,
                        }}>
                          {wr != null ? `${wr}%` : "—"}
                          {cell?.bets != null && wr != null && (
                            <div style={{ fontSize: 9, color: T.textFaint, fontWeight: 400, marginTop: 1 }}>
                              n={cell.bets}
                            </div>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </SectionCard>
      )}

      {/* Model Version Comparison */}
      {models.length > 0 && (
        <SectionCard title="Model Version Comparison">
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr>
              {["Version", "Bets", "Win Rate", "ROI", "Avg CLV"].map(h => <th key={h} style={thStyle}>{h}</th>)}
            </tr></thead>
            <tbody>
              {models.map(m => (
                <tr key={m.model_version} style={{ borderBottom: `1px solid ${T.border}` }}>
                  <td style={{ ...tdStyle, fontWeight: 600, color: T.blue }}>{m.model_version}</td>
                  <td style={tdStyle}>{m.bets}</td>
                  <td style={{ ...tdStyle, color: wrColor(m.win_rate), fontWeight: 600 }}>{m.win_rate}%</td>
                  <td style={{ ...tdStyle, color: roiColor(m.roi), fontWeight: 600 }}>
                    {m.roi > 0 ? "+" : ""}{m.roi}%
                  </td>
                  <td style={{ ...tdStyle, color: T.textMid }}>
                    {m.avg_clv != null ? (m.avg_clv > 0 ? `+${m.avg_clv}` : m.avg_clv) : "N/A"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </SectionCard>
      )}

      {/* Filters */}
      <div style={{
        display: "flex", gap: 16, alignItems: "center", marginBottom: 16,
        background: T.card, border: `1px solid ${T.border}`, borderRadius: 10,
        padding: "10px 16px",
      }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: T.text }}>Filter Bets</span>
        <FilterSelect label="Stat" value={filterStat} options={STATS} onChange={setFilterStat} />
        <FilterSelect label="Position" value={filterPos} options={POSITIONS} onChange={setFilterPos} />
        {(filterStat !== "All" || filterPos !== "All") && (
          <button onClick={() => { setFilterStat("All"); setFilterPos("All"); }} style={{
            background: "transparent", border: "none", color: T.textSub,
            fontSize: 11, cursor: "pointer", textDecoration: "underline",
          }}>Clear filters</button>
        )}
      </div>

      {/* Recent Bets Table */}
      <SectionCard title={`Recent Bets (${bets.length})`} style={{ marginBottom: 0 }}>
        {bets.length === 0 ? (
          <div style={{ padding: "48px 24px", textAlign: "center" }}>
            <div style={{ fontSize: 28, marginBottom: 12 }}>📋</div>
            <div style={{ fontSize: 15, fontWeight: 600, color: T.text, marginBottom: 8 }}>No tracked bets yet</div>
            <div style={{ fontSize: 13, color: T.textSub, maxWidth: 360, margin: "0 auto", lineHeight: 1.6 }}>
              Bets are automatically logged when the pipeline generates edges with edge &ge; 3% and probability &ge; 55%.
            </div>
          </div>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 950 }}>
              <thead>
                <tr>
                  {["Date", "Player", "Pos", "Team", "Opponent", "Stat", "Line", "Prob", "Edge", "Actual", "Result"].map(h => (
                    <th key={h} style={thStyle}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {bets.map((b, i) => (
                  <tr key={i} style={{ borderBottom: `1px solid ${T.border}` }}>
                    <td style={{ ...tdStyle, fontSize: 12, color: T.textMid, whiteSpace: "nowrap" }}>{b.date || "—"}</td>
                    <td style={{ ...tdStyle, fontWeight: 600 }}>{b.player}</td>
                    <td style={{ ...tdStyle, fontSize: 11, color: T.textSub }}>{b.position || "—"}</td>
                    <td style={{ ...tdStyle, fontSize: 11, color: T.textSub }}>{b.team || "—"}</td>
                    <td style={{ ...tdStyle, fontSize: 11, color: T.textMid }}>
                      {b.opponent ? `vs ${b.opponent}` : "—"}
                    </td>
                    <td style={{ ...tdStyle, fontSize: 12, color: T.textMid, textTransform: "capitalize" }}>{b.stat}</td>
                    <td style={{ ...tdStyle, fontWeight: 600 }}>{b.line}+</td>
                    <td style={{ ...tdStyle, fontSize: 12 }}>{b.probability ? `${(b.probability * 100).toFixed(1)}%` : "—"}</td>
                    <td style={{ ...tdStyle, fontSize: 12, fontWeight: 600, color: T.accent }}>
                      {b.edge != null ? `+${b.edge}%` : "—"}
                    </td>
                    <td style={{ ...tdStyle, fontSize: 12, color: T.textMid }}>
                      {b.actual != null ? b.actual : "—"}
                    </td>
                    <td style={tdStyle}>
                      <span style={{
                        display: "inline-block", padding: "3px 10px", borderRadius: 6,
                        fontSize: 11, fontWeight: 700,
                        color: resultColor(b.result),
                        background: resultBg(b.result),
                      }}>
                        {b.result ? b.result.toUpperCase() : "PENDING"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </SectionCard>
    </div>
  );
}
