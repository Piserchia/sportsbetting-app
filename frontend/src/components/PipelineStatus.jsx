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
  blue:      "#2563eb",
  blueBg:    "#eff6ff",
  warn:      "#d97706",
  warnBg:    "#fffbeb",
  danger:    "#dc2626",
  dangerBg:  "#fef2f2",
  gridLine:  "#edf0f5",
};

function timeAgo(isoString) {
  if (!isoString) return "never";
  const d = new Date(isoString.endsWith("Z") ? isoString : isoString + "Z");
  if (isNaN(d)) return "—";
  const diffMs = Date.now() - d.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1)  return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24)  return `${diffHr}h ${diffMin % 60}m ago`;
  const diffDay = Math.floor(diffHr / 24);
  return `${diffDay}d ago`;
}

function formatDateTime(isoString) {
  if (!isoString) return "—";
  const d = new Date(isoString.endsWith("Z") ? isoString : isoString + "Z");
  if (isNaN(d)) return "—";
  return d.toLocaleString("en-US", {
    month: "short", day: "numeric",
    hour: "numeric", minute: "2-digit", hour12: true,
  });
}

function staleness(isoString) {
  if (!isoString) return "error";
  const d = new Date(isoString.endsWith("Z") ? isoString : isoString + "Z");
  if (isNaN(d)) return "error";
  const diffHr = (Date.now() - d.getTime()) / 3600000;
  if (diffHr < 4)  return "fresh";
  if (diffHr < 12) return "ok";
  if (diffHr < 48) return "stale";
  return "old";
}

const stalenessColor = { fresh: T.accent, ok: "#16a34a", stale: T.warn, old: T.danger, error: T.danger };
const stalenessBg    = { fresh: T.accentBg, ok: T.accentBg, stale: T.warnBg, old: T.dangerBg, error: T.dangerBg };
const stalenessLabel = { fresh: "Fresh", ok: "OK", stale: "Stale", old: "Out of date", error: "No data" };
const stalenessDot   = { fresh: "●", ok: "●", stale: "●", old: "●", error: "○" };

const PIPELINE_STAGES = [
  { source: "nba_api",         entity: "teams",              label: "Teams" },
  { source: "nba_api",         entity: "players",            label: "Players" },
  { source: "nba_api",         entity: "games",              label: "Games" },
  { source: "nba_api",         entity: "box_scores",         label: "Box Scores" },
  { source: "game_log_sync",   entity: "player_game_logs",   label: "Game Logs" },
  { source: "feature_builder", entity: "player_features",    label: "Features" },
  { source: "projection_model",entity: "player_projections", label: "Projections" },
  { source: "simulation",      entity: "player_simulations", label: "Simulations" },
  { source: "sportsgameodds",  entity: "props",              label: "Props" },
  { source: "edge_calculator", entity: "prop_edges",         label: "Edges" },
];

const COUNT_LABELS = {
  teams:              "Teams",
  players:            "Players",
  games:              "Games",
  player_game_stats:  "Game Stats",
  player_game_logs:   "Game Logs",
  player_features:    "Feature Rows",
  player_projections: "Projections",
  player_simulations: "Simulations",
  sportsbook_props:   "Sportsbook Props",
  prop_line_history:  "Line History",
  prop_edges:         "Prop Edges",
};

function fmtCount(n) {
  if (n === undefined || n === null) return "—";
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return n.toString();
}

export default function PipelineStatus() {
  const [data,      setData]      = useState(null);
  const [loading,   setLoading]   = useState(true);
  const [error,     setError]     = useState(null);
  const [refreshed, setRefreshed] = useState(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetch(`${API}/pipeline/status`);
      if (!r.ok) throw new Error(`API error ${r.status}`);
      const d = await r.json();
      setData(d);
      setRefreshed(new Date());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  // Build lookup map from ingestion data
  const logMap = {};
  if (data?.ingestion) {
    for (const row of data.ingestion) {
      logMap[`${row.source}::${row.entity}`] = row;
    }
  }

  return (
    <div style={{
      background: T.bg, minHeight: "100vh", color: T.text,
      fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
      padding: "28px",
    }}>
      <div style={{ maxWidth: 1100, margin: "0 auto" }}>

        {/* Header row */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 24 }}>
          <div>
            <div style={{ fontSize: 18, fontWeight: 700, color: T.text, letterSpacing: "-0.02em" }}>
              Pipeline Status
            </div>
            <div style={{ fontSize: 12, color: T.textSub, marginTop: 3 }}>
              Last refreshed: {refreshed ? refreshed.toLocaleTimeString() : "—"}
            </div>
          </div>
          <button
            onClick={load}
            style={{
              background: T.surface, border: `1px solid ${T.border}`,
              borderRadius: 8, padding: "8px 16px", fontSize: 13,
              color: T.text, cursor: "pointer", fontWeight: 500,
              boxShadow: "0 1px 3px rgba(0,0,0,0.06)",
            }}
          >
            ↻ Refresh
          </button>
        </div>

        {error && (
          <div style={{
            background: T.dangerBg, border: `1px solid #fca5a5`,
            borderRadius: 8, padding: "12px 16px", marginBottom: 20,
            fontSize: 13, color: T.danger,
          }}>
            Could not load pipeline status: {error}
          </div>
        )}

        {loading && !data && (
          <div style={{ textAlign: "center", color: T.textSub, padding: 60, fontSize: 13 }}>
            Loading...
          </div>
        )}

        {data && (
          <>
            {/* Summary cards */}
            <div style={{ display: "flex", gap: 14, marginBottom: 24, flexWrap: "wrap" }}>
              {[
                { label: "Latest Game", value: data.latest_game_date || "—", sub: "in database" },
                { label: "Features Through", value: data.latest_feature_date || "—", sub: "last built" },
                { label: "Projections", value: fmtCount(data.counts?.player_projections), sub: "players" },
                { label: "Simulations", value: fmtCount(data.counts?.player_simulations), sub: "rows" },
                { label: "Props", value: fmtCount(data.counts?.sportsbook_props), sub: "current" },
              ].map(c => (
                <div key={c.label} style={{
                  background: T.surface, border: `1px solid ${T.border}`,
                  borderRadius: 10, padding: "14px 20px", minWidth: 130,
                  boxShadow: "0 1px 3px rgba(0,0,0,0.06)", flex: "1 1 auto",
                }}>
                  <div style={{ fontSize: 10, fontWeight: 700, color: T.textSub, textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 6 }}>{c.label}</div>
                  <div style={{ fontSize: 22, fontWeight: 700, color: T.text, fontVariantNumeric: "tabular-nums" }}>{c.value}</div>
                  <div style={{ fontSize: 11, color: T.textFaint, marginTop: 2 }}>{c.sub}</div>
                </div>
              ))}
            </div>

            {/* Pipeline stage table */}
            <div style={{
              background: T.surface, border: `1px solid ${T.border}`,
              borderRadius: 10, boxShadow: "0 1px 4px rgba(0,0,0,0.06)",
              marginBottom: 24, overflow: "hidden",
            }}>
              <div style={{
                padding: "14px 20px", borderBottom: `1px solid ${T.border}`,
                fontSize: 10, fontWeight: 700, color: T.textSub,
                textTransform: "uppercase", letterSpacing: "0.1em",
              }}>
                Pipeline Stages
              </div>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr style={{ background: T.bg }}>
                    {["Stage", "Status", "Last Run", "Records", "Message"].map(h => (
                      <th key={h} style={{
                        padding: "8px 16px", textAlign: "left",
                        fontSize: 10, fontWeight: 700, color: T.textSub,
                        textTransform: "uppercase", letterSpacing: "0.08em",
                        borderBottom: `1px solid ${T.border}`,
                      }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {PIPELINE_STAGES.map((stage, i) => {
                    const row = logMap[`${stage.source}::${stage.entity}`];
                    const age = row?.status === "success" ? staleness(row?.ran_at) : (row ? "error" : "error");
                    const color = stalenessColor[age];
                    const bg    = i % 2 === 1 ? T.bg : T.surface;

                    return (
                      <tr key={`${stage.source}-${stage.entity}`} style={{ background: bg }}>
                        <td style={{ padding: "10px 16px", fontSize: 13, fontWeight: 500, color: T.text }}>
                          {stage.label}
                        </td>
                        <td style={{ padding: "10px 16px" }}>
                          {row ? (
                            <span style={{
                              display: "inline-flex", alignItems: "center", gap: 5,
                              background: stalenessBg[age], color,
                              fontSize: 11, fontWeight: 600,
                              padding: "3px 9px", borderRadius: 20,
                            }}>
                              <span style={{ fontSize: 8 }}>{stalenessDot[age]}</span>
                              {row.status === "success" ? stalenessLabel[age] : "Error"}
                            </span>
                          ) : (
                            <span style={{ color: T.textFaint, fontSize: 12 }}>No data</span>
                          )}
                        </td>
                        <td style={{ padding: "10px 16px", fontSize: 12, color: T.textMid, fontVariantNumeric: "tabular-nums" }}>
                          {row ? (
                            <span title={formatDateTime(row.ran_at)}>
                              {timeAgo(row.ran_at)}
                            </span>
                          ) : "—"}
                        </td>
                        <td style={{ padding: "10px 16px", fontSize: 12, color: T.textMid, fontVariantNumeric: "tabular-nums" }}>
                          {row ? fmtCount(row.records) : "—"}
                        </td>
                        <td style={{ padding: "10px 16px", fontSize: 11, color: T.textSub, maxWidth: 280 }}>
                          <span style={{ overflow: "hidden", textOverflow: "ellipsis", display: "block", whiteSpace: "nowrap" }}>
                            {row?.message || "—"}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* DB counts */}
            <div style={{
              background: T.surface, border: `1px solid ${T.border}`,
              borderRadius: 10, boxShadow: "0 1px 4px rgba(0,0,0,0.06)",
              overflow: "hidden",
            }}>
              <div style={{
                padding: "14px 20px", borderBottom: `1px solid ${T.border}`,
                fontSize: 10, fontWeight: 700, color: T.textSub,
                textTransform: "uppercase", letterSpacing: "0.1em",
              }}>
                Database Record Counts
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", padding: "16px 12px", gap: 8 }}>
                {Object.entries(data.counts || {}).map(([key, val]) => (
                  <div key={key} style={{
                    background: T.bg, border: `1px solid ${T.border}`,
                    borderRadius: 8, padding: "10px 16px", minWidth: 130,
                  }}>
                    <div style={{ fontSize: 10, color: T.textSub, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 4 }}>
                      {COUNT_LABELS[key] || key}
                    </div>
                    <div style={{ fontSize: 18, fontWeight: 700, color: T.text, fontVariantNumeric: "tabular-nums" }}>
                      {fmtCount(val)}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
