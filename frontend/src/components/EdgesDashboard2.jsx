import React, { useEffect, useState, useCallback, useMemo } from "react";

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
  live:      "#f87171",
  liveBg:    "rgba(248,113,113,0.12)",
};

const STATS = ["all", "points", "rebounds", "assists", "steals", "blocks"];

const STATUS_STYLE = {
  Live:     { color: T.live,   bg: T.liveBg,   label: "LIVE" },
  Upcoming: { color: T.accent, bg: T.accentBg,  label: "TODAY" },
  Final:    { color: T.textFaint, bg: "rgba(69,72,96,0.2)", label: "FINAL" },
};

function GameStatusBadge({ status }) {
  if (!status) return null;
  const s = STATUS_STYLE[status] || STATUS_STYLE.Upcoming;
  return (
    <span style={{
      fontSize: 9, fontWeight: 700, letterSpacing: "0.07em",
      padding: "1px 5px", borderRadius: 3,
      color: s.color, background: s.bg, marginLeft: 5,
    }}>{s.label}</span>
  );
}

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

function LineDiff({ diff }) {
  if (diff === null || diff === undefined) return <span style={{ color: T.textFaint }}>—</span>;
  const color = diff > 0 ? T.green : diff < 0 ? T.red : T.textSub;
  return (
    <span style={{ color, fontWeight: 600 }}>
      {diff > 0 ? "+" : ""}{diff.toFixed(1)}
    </span>
  );
}

function FilterInput({ label, value, onChange, placeholder }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <span style={{ color: T.textSub, fontSize: 12, whiteSpace: "nowrap" }}>{label}</span>
      <input
        type="number"
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        style={{
          width: 56, padding: "4px 8px", borderRadius: 6, border: `1px solid ${T.border}`,
          background: T.card, color: T.text, fontSize: 12, textAlign: "center",
        }}
      />
    </div>
  );
}

export default function EdgesDashboard2({ onPlayerSelect }) {
  const [edges, setEdges]           = useState([]);
  const [data, setData]             = useState({});
  const [loading, setLoading]       = useState(true);
  const [error, setError]           = useState(null);
  const [minEdge, setMinEdge]       = useState(2);
  const [inputVal, setInputVal]     = useState("2");
  const [minLine, setMinLine]       = useState("");
  const [maxLine, setMaxLine]       = useState("");
  const [statFilter, setStatFilter] = useState("all");
  const [matchupFilter, setMatchupFilter] = useState("all");
  const [sortBy, setSortBy]         = useState("score");

  const fetchEdges = useCallback(() => {
    setLoading(true);
    setError(null);
    let url = `${API}/edges/best?limit=1000&min_edge=${minEdge}`;
    if (minLine !== "") url += `&min_line=${minLine}`;
    if (maxLine !== "") url += `&max_line=${maxLine}`;
    fetch(url)
      .then(r => r.json())
      .then(d => { setEdges(d.edges || []); setData(d); setLoading(false); })
      .catch(() => { setError("Failed to load edges"); setLoading(false); });
  }, [minEdge, minLine, maxLine]);

  useEffect(() => { fetchEdges(); }, [fetchEdges]);

  // Derive unique matchups with game time (e.g., "LAL @ BOS")
  const matchupInfo = useMemo(() => {
    const map = {};
    edges.forEach(e => {
      if (e.matchup && !map[e.matchup]) {
        map[e.matchup] = e.game_time_et || null;
      }
    });
    return map;
  }, [edges]);
  const allMatchups = useMemo(() => ["all", ...Object.keys(matchupInfo).sort()], [matchupInfo]);

  // Derive union of all book names
  const allBooks = useMemo(() => {
    const books = new Set();
    edges.forEach(e => (e.books || []).forEach(b => books.add(b.book)));
    return Array.from(books).sort();
  }, [edges]);

  const filtered = useMemo(() => {
    const sorted = edges
      .filter(e => statFilter === "all" || e.stat === statFilter)
      .filter(e => matchupFilter === "all" || e.matchup === matchupFilter)
      .sort((a, b) => {
        if (sortBy === "score") return b.score - a.score;
        if (sortBy === "edge")  return b.best_edge - a.best_edge;
        if (sortBy === "prob")  return b.probability - a.probability;
        return 0;
      });

    // Dedup: keep only the best row per (player_id, stat) — already sorted so first wins
    const seen = new Set();
    return sorted.filter(e => {
      const key = `${e.player_id}|${e.stat}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }, [edges, statFilter, matchupFilter, sortBy]);

  const applyFilters = () => {
    const v = parseFloat(inputVal);
    if (!isNaN(v)) setMinEdge(v);
    fetchEdges();
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
        input[type=number]::-webkit-inner-spin-button { opacity: 0.4; }
      `}</style>

      {/* Header */}
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 20, flexWrap: "wrap", gap: 12 }}>
        <div>
          <div style={{ color: T.text, fontSize: 18, fontWeight: 700 }}>Best Edges — Today</div>
          <div style={{ color: T.textSub, fontSize: 12, marginTop: 2 }}>
            One row per player/stat · all sportsbooks · ranked by bet score
          </div>
        </div>
        {/* Filters row */}
        <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
          <FilterInput label="Min edge:" value={inputVal} onChange={setInputVal} placeholder="2" />
          <FilterInput label="Min line:" value={minLine} onChange={setMinLine} placeholder="—" />
          <FilterInput label="Max line:" value={maxLine} onChange={setMaxLine} placeholder="—" />
          <button
            onClick={applyFilters}
            onKeyDown={e => e.key === "Enter" && applyFilters()}
            style={{
              padding: "4px 14px", borderRadius: 6, border: `1px solid ${T.border}`,
              background: T.accentBg, color: T.accent, fontSize: 12, fontWeight: 600, cursor: "pointer",
            }}
          >
            Apply
          </button>
        </div>
      </div>

      {/* Stat filter */}
      <div style={{ display: "flex", gap: 6, marginBottom: 10, flexWrap: "wrap" }}>
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
            {s === "all" ? "All Stats" : s.charAt(0).toUpperCase() + s.slice(1)}
          </button>
        ))}
      </div>

      {/* Matchup filter */}
      {allMatchups.length > 1 && (
        <div style={{ display: "flex", gap: 5, marginBottom: 16, flexWrap: "wrap", alignItems: "center" }}>
          <span style={{ color: T.textFaint, fontSize: 11, marginRight: 4 }}>Game:</span>
          {allMatchups.map(m => (
            <button
              key={m}
              onClick={() => setMatchupFilter(m)}
              style={{
                padding: "3px 10px", borderRadius: 5, fontSize: 11, fontWeight: 600,
                cursor: "pointer", border: "1px solid",
                borderColor: matchupFilter === m ? T.accent : T.border,
                background: matchupFilter === m ? T.accentBg : "transparent",
                color: matchupFilter === m ? T.accent : T.textSub,
              }}
            >
              {m === "all" ? "All Games" : `${m}${matchupInfo[m] ? ` · ${matchupInfo[m]}` : ""}`}
            </button>
          ))}
          <span style={{ marginLeft: "auto", color: T.textFaint, fontSize: 12, alignSelf: "center" }}>
            {filtered.length} edges
          </span>
        </div>
      )}

      {/* Table */}
      {loading ? (
        <div style={{ color: T.textSub, padding: 40, textAlign: "center" }}>Loading…</div>
      ) : error ? (
        <div style={{ color: T.red, padding: 40, textAlign: "center" }}>{error}</div>
      ) : filtered.length === 0 ? (
        <div style={{
          textAlign: "center", padding: "48px 24px",
          background: T.card, borderRadius: 12, border: `1px solid ${T.border}`,
        }}>
          <div style={{ fontSize: 28, marginBottom: 12 }}>📊</div>
          <div style={{ fontSize: 15, fontWeight: 600, color: T.text, marginBottom: 8 }}>
            No edges available for today
          </div>
          <div style={{ fontSize: 13, color: T.textSub, lineHeight: 1.6, maxWidth: 420, margin: "0 auto" }}>
            {edges.length === 0
              ? (data?.games_today === 0
                  ? "No NBA games scheduled today."
                  : !data?.has_sims
                    ? `${data?.games_today} game${data?.games_today > 1 ? "s" : ""} today — pipeline hasn't run yet. Run the pipeline to generate projections and edges.`
                    : !data?.has_props
                      ? `${data?.games_today} game${data?.games_today > 1 ? "s" : ""} today — no sportsbook props loaded. Run props ingestion before games start.`
                      : data?.upcoming_games === 0
                        ? "All games have finished. Edges are generated for upcoming games only."
                        : "No sportsbook edges found for today's games.")
              : "No edges matched the current filters. Try adjusting the minimum edge or line range."
            }
          </div>
        </div>
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
                <th className="e2-th">vs Line</th>
                <th className="e2-th">
                  Prob
                  <button className={`sort-btn ${sortBy === "prob" ? "active" : ""}`} onClick={() => setSortBy("prob")}>▼</button>
                </th>
                <th className="e2-th">Fair Odds</th>
                {allBooks.map(book => (
                  <th key={book} className="e2-th">{book.replace("draftkings", "DK").replace("fanduel", "FD").replace("betmgm", "MGM")}</th>
                ))}
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
              {filtered.map((e, i) => {
                const bookMap = {};
                (e.books || []).forEach(b => { bookMap[b.book] = b; });
                return (
                  <tr
                    key={i}
                    className="e2-row"
                    style={{ background: i % 2 === 0 ? T.card : "rgba(255,255,255,0.015)", borderBottom: `1px solid ${T.border}` }}
                    onClick={() => onPlayerSelect && onPlayerSelect({ player_id: e.player_id, full_name: e.player })}
                  >
                    <td style={{ padding: "10px 12px", color: T.text, fontWeight: 600, fontSize: 13 }}>
                      {e.player}
                    </td>
                    <td style={{ padding: "10px 12px", color: T.textSub, fontSize: 12, whiteSpace: "nowrap" }}>
                      {e.matchup}
                      {e.game_time_et && <span style={{ color: T.textFaint, fontSize: 10, marginLeft: 5 }}>{e.game_time_et}</span>}
                      <GameStatusBadge status={e.game_status} />
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
                      {e.projection !== null && e.projection !== undefined ? e.projection.toFixed(1) : "—"}
                    </td>
                    <td style={{ padding: "10px 12px" }}>
                      <LineDiff diff={e.line_diff} />
                    </td>
                    <td style={{ padding: "10px 12px" }}>
                      <ProbBar prob={e.probability} />
                    </td>
                    <td style={{ padding: "10px 12px", color: T.textSub, fontSize: 12, fontVariantNumeric: "tabular-nums" }}>
                      {e.fair_odds !== null ? (e.fair_odds > 0 ? `+${e.fair_odds}` : e.fair_odds) : "—"}
                    </td>
                    {allBooks.map(book => {
                      const bk = bookMap[book];
                      return (
                        <td key={book} style={{ padding: "10px 12px", fontSize: 12, fontVariantNumeric: "tabular-nums" }}>
                          {bk ? (
                            <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
                              <span style={{ color: T.text }}>{bk.odds > 0 ? `+${bk.odds}` : bk.odds}</span>
                              <span style={{ fontSize: 10, color: bk.edge_percent >= 4 ? T.green : bk.edge_percent >= 2 ? T.greenMid : T.textFaint }}>
                                {bk.edge_percent > 0 ? "+" : ""}{bk.edge_percent.toFixed(1)}%
                              </span>
                            </div>
                          ) : (
                            <span style={{ color: T.textFaint }}>—</span>
                          )}
                        </td>
                      );
                    })}
                    <td style={{ padding: "10px 12px" }}>
                      <EdgeBadge edge={e.best_edge} />
                    </td>
                    <td style={{ padding: "10px 12px", color: T.accent, fontWeight: 700, fontSize: 13, fontVariantNumeric: "tabular-nums" }}>
                      {e.score.toFixed(1)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
