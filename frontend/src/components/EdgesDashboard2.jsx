import React, { useEffect, useState, useCallback } from "react";

const API = "http://localhost:8000";

const T = {
  bg:        "#0f1117",
  card:      "#16181f",
  border:    "#23263a",
  text:      "#e8eaf0",
  textSub:   "#7b8099",
  textFaint: "#454860",
  accent:    "#34d399",
  accentBg:  "rgba(52,211,153,0.08)",
  warn:      "#f59e0b",
  red:       "#f87171",
  green:     "#34d399",
  greenMid:  "#6ee7b7",
};

const STATS = ["all", "points", "rebounds", "assists", "steals", "blocks"];

function EdgeBadge({ edge }) {
  if (edge === null || edge === undefined) return <span style={{ color: T.textFaint }}>—</span>;
  const color = edge >= 7 ? T.green : edge >= 4 ? T.greenMid : edge <= -5 ? T.red : edge <= -2 ? T.warn : T.text;
  return (
    <span style={{ color, fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>
      {edge > 0 ? "+" : ""}{edge.toFixed(1)}%
    </span>
  );
}

function ProbBar({ prob }) {
  const pct = Math.round(prob * 100);
  const color = pct >= 65 ? T.green : pct >= 55 ? T.greenMid : T.warn;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <div style={{ width: 48, height: 4, background: T.border, borderRadius: 2, overflow: "hidden" }}>
        <div style={{ width: `${pct}%`, height: "100%", background: color, borderRadius: 2 }} />
      </div>
      <span style={{ color, fontWeight: 600, fontSize: 12, fontVariantNumeric: "tabular-nums" }}>{pct}%</span>
    </div>
  );
}

function LineDiff({ diff, stat }) {
  if (diff === null || diff === undefined) return <span style={{ color: T.textFaint }}>—</span>;
  const color = diff > 0 ? T.green : diff < 0 ? T.red : T.textSub;
  return (
    <span style={{ color, fontWeight: 600 }}>
      {diff > 0 ? "+" : ""}{diff.toFixed(1)}
    </span>
  );
}

export default function EdgesDashboard2({ onPlayerSelect }) {
  const [edges, setEdges]       = useState([]);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState(null);
  const [minEdge, setMinEdge]   = useState(2);
  const [inputVal, setInputVal] = useState("2");
  const [statFilter, setStatFilter] = useState("all");
  const [sortBy, setSortBy]     = useState("score"); // "score" | "edge" | "prob"

  const fetchEdges = useCallback(() => {
    setLoading(true);
    setError(null);
    fetch(`${API}/edges/best?limit=150&min_edge=${minEdge}`)
      .then(r => r.json())
      .then(data => { setEdges(data.edges || []); setLoading(false); })
      .catch(() => { setError("Failed to load edges"); setLoading(false); });
  }, [minEdge]);

  useEffect(() => { fetchEdges(); }, [fetchEdges]);

  const filtered = edges
    .filter(e => statFilter === "all" || e.stat === statFilter)
    .sort((a, b) => {
      if (sortBy === "score") return b.score - a.score;
      if (sortBy === "edge")  return b.edge_percent - a.edge_percent;
      if (sortBy === "prob")  return b.probability - a.probability;
      return 0;
    });

  const applyMinEdge = () => {
    const v = parseFloat(inputVal);
    if (!isNaN(v)) setMinEdge(v);
  };

  return (
    <div style={{ background: T.bg, minHeight: "100vh", padding: "24px 28px", fontFamily: "system-ui, sans-serif" }}>
      <style>{`
        .e2-row:hover { background: ${T.accentBg} !important; cursor: pointer; }
        .e2-th { color: ${T.textSub}; font-size: 10px; font-weight: 700; text-transform: uppercase;
                  letter-spacing: 0.08em; padding: 8px 12px; text-align: left; border-bottom: 1px solid ${T.border}; }
        .sort-btn { background: none; border: none; cursor: pointer; padding: 0; margin-left: 4px;
                    color: ${T.textFaint}; font-size: 10px; }
        .sort-btn.active { color: ${T.accent}; }
      `}</style>

      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
        <div>
          <div style={{ color: T.text, fontSize: 18, fontWeight: 700 }}>Best Edges — Today</div>
          <div style={{ color: T.textSub, fontSize: 12, marginTop: 2 }}>
            One line per prop · best book · ranked by bet score
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span style={{ color: T.textSub, fontSize: 12 }}>Min edge:</span>
          <input
            type="number"
            value={inputVal}
            onChange={e => setInputVal(e.target.value)}
            onKeyDown={e => e.key === "Enter" && applyMinEdge()}
            style={{
              width: 52, padding: "4px 8px", borderRadius: 6, border: `1px solid ${T.border}`,
              background: T.card, color: T.text, fontSize: 12, textAlign: "center",
            }}
          />
          <button
            onClick={applyMinEdge}
            style={{
              padding: "4px 12px", borderRadius: 6, border: `1px solid ${T.border}`,
              background: T.accentBg, color: T.accent, fontSize: 12, fontWeight: 600, cursor: "pointer",
            }}
          >
            Apply
          </button>
        </div>
      </div>

      {/* Stat filter */}
      <div style={{ display: "flex", gap: 6, marginBottom: 16 }}>
        {STATS.map(s => (
          <button
            key={s}
            onClick={() => setStatFilter(s)}
            style={{
              padding: "4px 12px", borderRadius: 6, fontSize: 11, fontWeight: 600,
              cursor: "pointer", border: "1px solid",
              borderColor: statFilter === s ? T.accent : T.border,
              background: statFilter === s ? T.accentBg : "transparent",
              color: statFilter === s ? T.accent : T.textSub,
            }}
          >
            {s === "all" ? "All" : s.charAt(0).toUpperCase() + s.slice(1)}
          </button>
        ))}
        <span style={{ marginLeft: "auto", color: T.textFaint, fontSize: 12, alignSelf: "center" }}>
          {filtered.length} edges
        </span>
      </div>

      {/* Table */}
      {loading ? (
        <div style={{ color: T.textSub, padding: 40, textAlign: "center" }}>Loading…</div>
      ) : error ? (
        <div style={{ color: T.red, padding: 40, textAlign: "center" }}>{error}</div>
      ) : filtered.length === 0 ? (
        <div style={{ color: T.textSub, padding: 40, textAlign: "center" }}>No edges found for selected filters.</div>
      ) : (
        <div style={{ background: T.card, borderRadius: 10, border: `1px solid ${T.border}`, overflow: "hidden" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th className="e2-th">Player</th>
                <th className="e2-th">Matchup</th>
                <th className="e2-th">Stat</th>
                <th className="e2-th">Line</th>
                <th className="e2-th">Projection</th>
                <th className="e2-th">
                  vs Line
                </th>
                <th className="e2-th">
                  Prob
                  <button className={`sort-btn ${sortBy === "prob" ? "active" : ""}`} onClick={() => setSortBy("prob")}>▼</button>
                </th>
                <th className="e2-th">Fair Odds</th>
                <th className="e2-th">Best Book</th>
                <th className="e2-th">Odds</th>
                <th className="e2-th">
                  Edge
                  <button className={`sort-btn ${sortBy === "edge" ? "active" : ""}`} onClick={() => setSortBy("edge")}>▼</button>
                </th>
                <th className="e2-th">
                  Score
                  <button className={`sort-btn ${sortBy === "score" ? "active" : ""}`} onClick={() => setSortBy("score")}>▼</button>
                </th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((e, i) => (
                <tr
                  key={i}
                  className="e2-row"
                  style={{ background: i % 2 === 0 ? T.card : "rgba(255,255,255,0.015)", borderBottom: `1px solid ${T.border}` }}
                  onClick={() => onPlayerSelect && onPlayerSelect({ player_id: e.player_id, full_name: e.player })}
                >
                  <td style={{ padding: "10px 12px", color: T.text, fontWeight: 600, fontSize: 13 }}>
                    {e.player}
                  </td>
                  <td style={{ padding: "10px 12px", color: T.textSub, fontSize: 12 }}>
                    {e.matchup}
                  </td>
                  <td style={{ padding: "10px 12px" }}>
                    <span style={{
                      background: T.accentBg, color: T.accent,
                      padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 700,
                    }}>
                      {e.stat.toUpperCase()}
                    </span>
                  </td>
                  <td style={{ padding: "10px 12px", color: T.text, fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>
                    {e.line}
                  </td>
                  <td style={{ padding: "10px 12px", color: T.textSub, fontVariantNumeric: "tabular-nums" }}>
                    {e.projection !== null ? e.projection.toFixed(1) : "—"}
                  </td>
                  <td style={{ padding: "10px 12px" }}>
                    <LineDiff diff={e.line_diff} stat={e.stat} />
                  </td>
                  <td style={{ padding: "10px 12px" }}>
                    <ProbBar prob={e.probability} />
                  </td>
                  <td style={{ padding: "10px 12px", color: T.textSub, fontSize: 12, fontVariantNumeric: "tabular-nums" }}>
                    {e.fair_odds !== null ? (e.fair_odds > 0 ? `+${e.fair_odds}` : e.fair_odds) : "—"}
                  </td>
                  <td style={{ padding: "10px 12px", color: T.textSub, fontSize: 12, fontWeight: 600 }}>
                    {e.best_book}
                  </td>
                  <td style={{ padding: "10px 12px", color: T.text, fontVariantNumeric: "tabular-nums", fontSize: 13 }}>
                    {e.best_odds !== null ? (e.best_odds > 0 ? `+${e.best_odds}` : e.best_odds) : "—"}
                  </td>
                  <td style={{ padding: "10px 12px" }}>
                    <EdgeBadge edge={e.edge_percent} />
                  </td>
                  <td style={{ padding: "10px 12px", color: T.accent, fontWeight: 700, fontSize: 13, fontVariantNumeric: "tabular-nums" }}>
                    {e.score.toFixed(1)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
