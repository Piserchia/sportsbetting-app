import { useState, useEffect } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Cell, ReferenceLine,
} from "recharts";

const API = "http://localhost:8000";

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
  danger:    "#dc2626",
  dangerBg:  "#fef2f2",
};

const FEATURE_LABELS = {
  minutes_projection: "Minutes Projection",
  points_avg_last_5: "Points Avg (L5)",
  points_avg_last_10: "Points Avg (L10)",
  season_avg_points: "Season Avg Points",
  rebounds_avg_last_5: "Rebounds Avg (L5)",
  rebounds_avg_last_10: "Rebounds Avg (L10)",
  season_avg_rebounds: "Season Avg Rebounds",
  assists_avg_last_5: "Assists Avg (L5)",
  assists_avg_last_10: "Assists Avg (L10)",
  season_avg_assists: "Season Avg Assists",
  steals_avg_last_5: "Steals Avg (L5)",
  steals_avg_last_10: "Steals Avg (L10)",
  season_avg_steals: "Season Avg Steals",
  blocks_avg_last_5: "Blocks Avg (L5)",
  blocks_avg_last_10: "Blocks Avg (L10)",
  season_avg_blocks: "Season Avg Blocks",
  usage_proxy: "Usage Rate",
  pace_adjustment_factor: "Pace Adjustment",
  defense_adj_pts: "Defense vs Points",
  defense_adj_reb: "Defense vs Rebounds",
  defense_adj_ast: "Defense vs Assists",
  defense_adj_stl: "Defense vs Steals",
  defense_adj_blk: "Defense vs Blocks",
  spread: "Game Spread",
  team_total: "Team Total",
  is_home: "Home Court",
  days_rest: "Days Rest",
  is_back_to_back: "Back-to-Back",
  games_started_last_5: "Games Started (L5)",
};

function getLabel(feature) {
  return FEATURE_LABELS[feature] || feature.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
}

export default function ProjectionDebugger({ playerId, stat = "points", onClose }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selectedStat, setSelectedStat] = useState(stat);

  useEffect(() => {
    if (!playerId) return;
    setLoading(true);
    fetch(`${API}/players/${playerId}/projection_explanation?stat=${selectedStat}`)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [playerId, selectedStat]);

  if (!playerId) return null;

  const chartData = (data?.contributions || []).slice(0, 12).map(c => ({
    feature: getLabel(c.feature),
    value: c.contribution,
    raw: c.feature,
  }));

  const positive = (data?.top_positive || []).map(c => ({ ...c, label: getLabel(c.feature) }));
  const negative = (data?.top_negative || []).map(c => ({ ...c, label: getLabel(c.feature) }));

  return (
    <div style={{
      background: T.surface,
      border: `1px solid ${T.border}`,
      borderRadius: 12,
      padding: 24,
      marginTop: 16,
    }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 16, fontWeight: 700, color: T.text }}>
            Projection Explainer
          </div>
          <div style={{ fontSize: 12, color: T.textSub, marginTop: 2 }}>
            SHAP feature contributions — why the model produced this projection
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {/* Stat selector */}
          <div style={{ display: "flex", gap: 2 }}>
            {["points", "rebounds", "assists", "steals", "blocks"].map(s => (
              <button
                key={s}
                onClick={() => setSelectedStat(s)}
                style={{
                  padding: "4px 10px", borderRadius: 6, fontSize: 11, fontWeight: 600,
                  cursor: "pointer",
                  border: selectedStat === s ? `1px solid ${T.accent}` : `1px solid ${T.border}`,
                  background: selectedStat === s ? T.accentBg : "transparent",
                  color: selectedStat === s ? T.accent : T.textSub,
                }}
              >
                {s.charAt(0).toUpperCase() + s.slice(1)}
              </button>
            ))}
          </div>
          {onClose && (
            <button
              onClick={onClose}
              style={{
                padding: "4px 12px", borderRadius: 6, fontSize: 12, fontWeight: 600,
                cursor: "pointer", border: `1px solid ${T.border}`,
                background: "transparent", color: T.textSub,
              }}
            >
              Close
            </button>
          )}
        </div>
      </div>

      {loading && (
        <div style={{ textAlign: "center", padding: 40, color: T.textSub, fontSize: 13 }}>
          Loading explanations...
        </div>
      )}

      {!loading && (!data || data.source === "no_data") && (
        <div style={{ textAlign: "center", padding: 40, color: T.textSub, fontSize: 13 }}>
          No SHAP data available for this player. Run the pipeline to generate explanations.
        </div>
      )}

      {!loading && data && data.source === "shap" && (
        <>
          {/* Chart */}
          <div style={{ marginBottom: 20 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: T.text, marginBottom: 8 }}>
              Feature Contributions for {selectedStat.charAt(0).toUpperCase() + selectedStat.slice(1)}
            </div>
            <ResponsiveContainer width="100%" height={Math.max(200, chartData.length * 28 + 40)}>
              <BarChart
                data={chartData}
                layout="vertical"
                margin={{ top: 5, right: 30, left: 140, bottom: 5 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#edf0f5" horizontal={false} />
                <XAxis
                  type="number"
                  tick={{ fontSize: 11, fill: T.textSub }}
                  tickFormatter={v => v > 0 ? `+${v.toFixed(1)}` : v.toFixed(1)}
                />
                <YAxis
                  type="category"
                  dataKey="feature"
                  tick={{ fontSize: 11, fill: T.textMid }}
                  width={135}
                />
                <Tooltip
                  formatter={(val) => [val > 0 ? `+${val.toFixed(3)}` : val.toFixed(3), "Contribution"]}
                  contentStyle={{ fontSize: 12, borderRadius: 8, border: `1px solid ${T.border}` }}
                />
                <ReferenceLine x={0} stroke={T.textSub} strokeWidth={1} />
                <Bar dataKey="value" radius={[0, 4, 4, 0]} barSize={16}>
                  {chartData.map((entry, i) => (
                    <Cell key={i} fill={entry.value >= 0 ? T.accent : T.danger} fillOpacity={0.8} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* Top drivers */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
            {/* Positive */}
            <div style={{
              border: `1px solid #b6f0d8`, borderRadius: 10, padding: 14,
              background: "#f0fdf7",
            }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: T.accent, marginBottom: 8, textTransform: "uppercase", letterSpacing: "0.04em" }}>
                Top Positive Drivers
              </div>
              {positive.length === 0 && (
                <div style={{ fontSize: 12, color: T.textSub }}>None</div>
              )}
              {positive.map((c, i) => (
                <div key={i} style={{ display: "flex", justifyContent: "space-between", padding: "4px 0", borderBottom: i < positive.length - 1 ? `1px solid #d5f5e8` : "none" }}>
                  <span style={{ fontSize: 13, color: T.text }}>{c.label}</span>
                  <span style={{ fontSize: 13, fontWeight: 700, color: T.accent, fontFamily: "monospace" }}>
                    +{c.contribution.toFixed(2)}
                  </span>
                </div>
              ))}
            </div>

            {/* Negative */}
            <div style={{
              border: `1px solid #fecaca`, borderRadius: 10, padding: 14,
              background: "#fef8f8",
            }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: T.danger, marginBottom: 8, textTransform: "uppercase", letterSpacing: "0.04em" }}>
                Top Negative Drivers
              </div>
              {negative.length === 0 && (
                <div style={{ fontSize: 12, color: T.textSub }}>None</div>
              )}
              {negative.map((c, i) => (
                <div key={i} style={{ display: "flex", justifyContent: "space-between", padding: "4px 0", borderBottom: i < negative.length - 1 ? `1px solid #fee2e2` : "none" }}>
                  <span style={{ fontSize: 13, color: T.text }}>{c.label}</span>
                  <span style={{ fontSize: 13, fontWeight: 700, color: T.danger, fontFamily: "monospace" }}>
                    {c.contribution.toFixed(2)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
