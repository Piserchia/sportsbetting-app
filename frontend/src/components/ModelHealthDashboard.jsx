import { useState, useEffect, useCallback, useMemo } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Cell, ReferenceLine, LineChart, Line,
  ScatterChart, Scatter, ZAxis,
} from "recharts";

const API = "http://localhost:8000";

const T = {
  bg:        "#f4f5f7",
  surface:   "#ffffff",
  border:    "#e2e4e9",
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
};

const STATS = ["points", "rebounds", "assists", "steals", "blocks"];

const FEATURE_LABELS = {
  minutes_projection: "Minutes Proj",
  points_recent_adj: "Points EWMA",
  points_avg_last_10: "Points L10",
  season_avg_points: "Season Pts",
  rebounds_recent_adj: "Rebounds EWMA",
  rebounds_avg_last_10: "Rebounds L10",
  season_avg_rebounds: "Season Reb",
  assists_recent_adj: "Assists EWMA",
  assists_avg_last_10: "Assists L10",
  season_avg_assists: "Season Ast",
  steals_recent_adj: "Steals EWMA",
  steals_avg_last_10: "Steals L10",
  season_avg_steals: "Season Stl",
  blocks_recent_adj: "Blocks EWMA",
  blocks_avg_last_10: "Blocks L10",
  season_avg_blocks: "Season Blk",
  usage_proxy: "Usage Rate",
  pace_adjustment_factor: "Pace Adj",
  defense_adj_pts: "Def vs Pts",
  defense_adj_reb: "Def vs Reb",
  defense_adj_ast: "Def vs Ast",
  defense_adj_stl: "Def vs Stl",
  defense_adj_blk: "Def vs Blk",
  is_home: "Home Court",
  days_rest: "Days Rest",
  is_back_to_back: "Back-to-Back",
  games_started_last_5: "Starts L5",
  points_posterior: "Pts Posterior",
  rebounds_posterior: "Reb Posterior",
  assists_posterior: "Ast Posterior",
  steals_posterior: "Stl Posterior",
  blocks_posterior: "Blk Posterior",
};

function Card({ title, children, style }) {
  return (
    <div style={{
      background: T.surface, borderRadius: 10, border: `1px solid ${T.border}`,
      padding: "18px 22px", ...style,
    }}>
      {title && (
        <div style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase",
          letterSpacing: "0.08em", color: T.textSub, marginBottom: 12 }}>
          {title}
        </div>
      )}
      {children}
    </div>
  );
}

function MetricCard({ label, value, subtitle, color }) {
  return (
    <div style={{
      background: T.surface, borderRadius: 8, border: `1px solid ${T.border}`,
      padding: "14px 18px", flex: "1 1 0", minWidth: 120,
    }}>
      <div style={{ fontSize: 11, color: T.textSub, fontWeight: 600, marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color: color || T.text, fontVariantNumeric: "tabular-nums" }}>
        {value ?? "—"}
      </div>
      {subtitle && <div style={{ fontSize: 11, color: T.textFaint, marginTop: 2 }}>{subtitle}</div>}
    </div>
  );
}

function StatPill({ stat, active, onClick }) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: "4px 12px", borderRadius: 6, fontSize: 11, fontWeight: 600,
        cursor: "pointer", border: "1px solid",
        borderColor: active ? T.accent : T.border,
        background: active ? T.accentBg : "transparent",
        color: active ? T.accent : T.textSub,
      }}
    >
      {stat.charAt(0).toUpperCase() + stat.slice(1)}
    </button>
  );
}

export default function ModelHealthDashboard() {
  const [backtests, setBacktests] = useState([]);
  const [performance, setPerformance] = useState(null);
  const [featureImportance, setFeatureImportance] = useState([]);
  const [accuracy, setAccuracy] = useState([]);
  const [calibration, setCalibration] = useState({ bins: [], ece: null });
  const [fiStat, setFiStat] = useState("points");
  const [calStat, setCalStat] = useState("points");
  const [drift, setDrift] = useState([]);
  const [driftStat, setDriftStat] = useState("points");
  const [edgeRealization, setEdgeRealization] = useState([]);
  const [projDist, setProjDist] = useState([]);
  const [projDistStat, setProjDistStat] = useState("points");
  const [globalDrivers, setGlobalDrivers] = useState([]);
  const [globalDriversStat, setGlobalDriversStat] = useState("points");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      fetch(`${API}/model/backtests`).then(r => r.json()).catch(() => ({ stats: [] })),
      fetch(`${API}/model/performance`).then(r => r.json()).catch(() => null),
      fetch(`${API}/model/projection-accuracy`).then(r => r.json()).catch(() => ({ accuracy: [] })),
    ]).then(([bt, perf, acc]) => {
      setBacktests(bt.stats || []);
      setPerformance(perf);
      setAccuracy(acc.accuracy || []);
      setLoading(false);
    });
  }, []);

  // Feature importance — reload when stat changes
  useEffect(() => {
    fetch(`${API}/model/feature-importance?stat=${fiStat}`)
      .then(r => r.json())
      .then(data => setFeatureImportance(data.features || []))
      .catch(() => setFeatureImportance([]));
  }, [fiStat]);

  // Drift — reload when stat changes
  useEffect(() => {
    fetch(`${API}/model/drift?stat=${driftStat}`)
      .then(r => r.json())
      .then(data => setDrift(data.drift || []))
      .catch(() => setDrift([]));
  }, [driftStat]);

  // Edge realization — single fetch on mount
  useEffect(() => {
    fetch(`${API}/model/edge-realization`)
      .then(r => r.json())
      .then(data => setEdgeRealization(data.buckets || []))
      .catch(() => setEdgeRealization([]));
  }, []);

  // Projection distribution — reload when stat changes
  useEffect(() => {
    fetch(`${API}/model/projection-distribution?stat=${projDistStat}`)
      .then(r => r.json())
      .then(data => setProjDist(data.bins || []))
      .catch(() => setProjDist([]));
  }, [projDistStat]);

  // Global SHAP drivers — reload when stat changes
  useEffect(() => {
    fetch(`${API}/model/global-drivers?stat=${globalDriversStat}`)
      .then(r => r.json())
      .then(data => setGlobalDrivers(data.drivers || []))
      .catch(() => setGlobalDrivers([]));
  }, [globalDriversStat]);

  // Calibration — reload when stat changes
  useEffect(() => {
    fetch(`${API}/model/calibration?stat=${calStat}`)
      .then(r => r.json())
      .then(data => setCalibration({ bins: data.bins || [], ece: data.ece }))
      .catch(() => setCalibration({ bins: [], ece: null }));
  }, [calStat]);

  const perf = performance || {};
  const winRate = perf.total_bets > 0
    ? ((perf.wins / perf.total_bets) * 100).toFixed(1) + "%"
    : "—";
  const roiColor = perf.roi > 0 ? T.accent : perf.roi < 0 ? T.danger : T.text;

  if (loading) {
    return (
      <div style={{ padding: 60, textAlign: "center", color: T.textSub }}>
        Loading model health data...
      </div>
    );
  }

  return (
    <div style={{ background: T.bg, minHeight: "100vh", padding: "24px 28px", fontFamily: "system-ui, sans-serif" }}>
      <div style={{ maxWidth: 1200, margin: "0 auto" }}>
        {/* Header */}
        <div style={{ marginBottom: 20 }}>
          <div style={{ fontSize: 18, fontWeight: 700, color: T.text }}>Model Health</div>
          <div style={{ fontSize: 12, color: T.textSub, marginTop: 2 }}>
            Prediction accuracy, calibration, and feature diagnostics
          </div>
        </div>

        {/* Section 1 — Performance Summary */}
        <div style={{ display: "flex", gap: 12, marginBottom: 20, flexWrap: "wrap" }}>
          <MetricCard
            label="Total Bets"
            value={perf.total_bets ?? 0}
            subtitle={perf.total_bets > 0 ? `${perf.wins}W / ${perf.losses}L / ${perf.pushes || 0}P` : null}
          />
          <MetricCard label="Win Rate" value={winRate} />
          <MetricCard
            label="ROI"
            value={perf.roi != null ? `${perf.roi > 0 ? "+" : ""}${perf.roi.toFixed(1)}%` : "—"}
            color={roiColor}
          />
          <MetricCard
            label="Avg CLV"
            value={perf.avg_clv != null ? perf.avg_clv.toFixed(2) : "—"}
            subtitle="closing line value"
          />
          <MetricCard
            label="Brier Score"
            value={perf.brier_score != null ? perf.brier_score.toFixed(4) : "—"}
            subtitle="lower is better"
          />
        </div>

        {/* Section 2 — Backtest Results */}
        <Card title="Backtest Results" style={{ marginBottom: 20 }}>
          {backtests.length === 0 ? (
            <div style={{ color: T.textSub, fontSize: 13, padding: 12 }}>
              No backtest data. Run: <code>python scripts/backtest_model.py</code>
            </div>
          ) : (
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr>
                  {["Stat", "Predictions", "Hit Rate", "Brier", "Log Loss", "ROI", "Avg Edge", "Last Run"].map(h => (
                    <th key={h} style={{
                      textAlign: "left", padding: "8px 10px", borderBottom: `1px solid ${T.border}`,
                      fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em",
                      color: T.textSub,
                    }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {backtests.map((b, i) => (
                  <tr key={b.stat} style={{ borderBottom: `1px solid ${T.border}` }}>
                    <td style={{ padding: "8px 10px", fontWeight: 600, color: T.text }}>
                      {b.stat.charAt(0).toUpperCase() + b.stat.slice(1)}
                    </td>
                    <td style={{ padding: "8px 10px", color: T.textMid, fontVariantNumeric: "tabular-nums" }}>
                      {b.total_predictions.toLocaleString()}
                    </td>
                    <td style={{ padding: "8px 10px", fontWeight: 600,
                      color: b.avg_hit_rate >= 0.52 ? T.accent : b.avg_hit_rate < 0.48 ? T.danger : T.textMid,
                      fontVariantNumeric: "tabular-nums",
                    }}>
                      {(b.avg_hit_rate * 100).toFixed(1)}%
                    </td>
                    <td style={{ padding: "8px 10px", color: T.textMid, fontVariantNumeric: "tabular-nums" }}>
                      {b.avg_brier.toFixed(4)}
                    </td>
                    <td style={{ padding: "8px 10px", color: T.textMid, fontVariantNumeric: "tabular-nums" }}>
                      {b.avg_log_loss.toFixed(4)}
                    </td>
                    <td style={{ padding: "8px 10px", fontWeight: 600,
                      color: b.avg_roi > 0 ? T.accent : b.avg_roi < 0 ? T.danger : T.textMid,
                      fontVariantNumeric: "tabular-nums",
                    }}>
                      {b.avg_roi > 0 ? "+" : ""}{b.avg_roi.toFixed(1)}%
                    </td>
                    <td style={{ padding: "8px 10px", color: T.textMid, fontVariantNumeric: "tabular-nums" }}>
                      {b.avg_edge > 0 ? "+" : ""}{(b.avg_edge * 100).toFixed(2)}%
                    </td>
                    <td style={{ padding: "8px 10px", color: T.textFaint, fontSize: 12 }}>
                      {b.last_run}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>

        {/* Two-column row: Feature Importance + Projection Accuracy */}
        <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 16, marginBottom: 20 }}>

          {/* Section 3 — Feature Importance */}
          <Card title="Feature Importance (LightGBM Gain)">
            <div style={{ display: "flex", gap: 5, marginBottom: 14 }}>
              {STATS.map(s => (
                <StatPill key={s} stat={s} active={fiStat === s} onClick={() => setFiStat(s)} />
              ))}
            </div>
            {featureImportance.length === 0 ? (
              <div style={{ color: T.textSub, fontSize: 13, padding: 12 }}>
                No feature importance data. Models must be trained first.
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={320}>
                <BarChart
                  data={featureImportance.map(f => ({
                    name: FEATURE_LABELS[f.feature] || f.feature,
                    value: f.importance,
                  }))}
                  layout="vertical"
                  margin={{ left: 10, right: 20, top: 4, bottom: 4 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke={T.border} horizontal={false} />
                  <XAxis type="number" tick={{ fontSize: 10, fill: T.textSub }} />
                  <YAxis
                    type="category" dataKey="name" width={120}
                    tick={{ fontSize: 10, fill: T.textMid }}
                  />
                  <Tooltip
                    contentStyle={{ fontSize: 12, borderRadius: 6, border: `1px solid ${T.border}` }}
                    formatter={(v) => [v.toLocaleString(), "Gain"]}
                  />
                  <Bar dataKey="value" radius={[0, 4, 4, 0]} maxBarSize={18}>
                    {featureImportance.map((_, i) => (
                      <Cell key={i} fill={i < 3 ? T.accent : i < 6 ? T.blue : T.textFaint} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </Card>

          {/* Section 4 — Projection Accuracy */}
          <Card title="Projection Accuracy">
            {accuracy.length === 0 ? (
              <div style={{ color: T.textSub, fontSize: 13, padding: 12 }}>
                No completed games with projections to evaluate.
              </div>
            ) : (
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                <thead>
                  <tr>
                    {["Stat", "MAE", "RMSE", "Games"].map(h => (
                      <th key={h} style={{
                        textAlign: "left", padding: "8px 8px", borderBottom: `1px solid ${T.border}`,
                        fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em",
                        color: T.textSub,
                      }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {accuracy.map(a => (
                    <tr key={a.stat} style={{ borderBottom: `1px solid ${T.border}` }}>
                      <td style={{ padding: "8px 8px", fontWeight: 600, color: T.text }}>
                        {a.stat.charAt(0).toUpperCase() + a.stat.slice(1)}
                      </td>
                      <td style={{ padding: "8px 8px", color: T.textMid, fontVariantNumeric: "tabular-nums" }}>
                        {a.mae.toFixed(2)}
                      </td>
                      <td style={{ padding: "8px 8px", color: T.textMid, fontVariantNumeric: "tabular-nums" }}>
                        {a.rmse.toFixed(2)}
                      </td>
                      <td style={{ padding: "8px 8px", color: T.textFaint, fontVariantNumeric: "tabular-nums" }}>
                        {a.n.toLocaleString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
        </div>

        {/* Section 5 — Calibration Curve */}
        <Card title="Calibration Curve" style={{ marginBottom: 20 }}>
          <div style={{ display: "flex", gap: 5, marginBottom: 14, alignItems: "center" }}>
            {STATS.map(s => (
              <StatPill key={s} stat={s} active={calStat === s} onClick={() => setCalStat(s)} />
            ))}
            {calibration.ece != null && (
              <span style={{ marginLeft: "auto", fontSize: 12, color: T.textSub }}>
                ECE: <strong style={{ color: calibration.ece < 0.05 ? T.accent : calibration.ece < 0.10 ? T.warn : T.danger }}>
                  {calibration.ece.toFixed(4)}
                </strong>
              </span>
            )}
          </div>
          {calibration.bins.length === 0 ? (
            <div style={{ color: T.textSub, fontSize: 13, padding: 12 }}>
              No calibration data available for this stat.
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={280}>
              <LineChart
                data={calibration.bins}
                margin={{ left: 10, right: 20, top: 10, bottom: 10 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke={T.border} />
                <XAxis
                  dataKey="bin_center" type="number" domain={[0, 1]}
                  tick={{ fontSize: 10, fill: T.textSub }}
                  label={{ value: "Predicted Probability", position: "insideBottom", offset: -4, fontSize: 11, fill: T.textSub }}
                  tickFormatter={v => `${(v * 100).toFixed(0)}%`}
                />
                <YAxis
                  domain={[0, 1]}
                  tick={{ fontSize: 10, fill: T.textSub }}
                  label={{ value: "Actual Hit Rate", angle: -90, position: "insideLeft", offset: 10, fontSize: 11, fill: T.textSub }}
                  tickFormatter={v => `${(v * 100).toFixed(0)}%`}
                />
                <Tooltip
                  contentStyle={{ fontSize: 12, borderRadius: 6, border: `1px solid ${T.border}` }}
                  formatter={(v, name) => [`${(v * 100).toFixed(1)}%`, name === "predicted" ? "Predicted" : "Actual"]}
                  labelFormatter={v => `Bin: ${(v * 100).toFixed(0)}%`}
                />
                {/* Perfect calibration line */}
                <Line
                  dataKey="bin_center" stroke={T.textFaint} strokeDasharray="5 5"
                  dot={false} name="Perfect"
                />
                {/* Actual calibration */}
                <Line
                  dataKey="actual" stroke={T.accent} strokeWidth={2}
                  dot={{ r: 4, fill: T.accent }} name="Actual"
                />
                <Line
                  dataKey="predicted" stroke={T.blue} strokeWidth={2}
                  dot={{ r: 3, fill: T.blue }} name="Predicted"
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </Card>

        {/* Section 6 — Model Drift */}
        <Card title="Model Drift (Avg Error Over Time)" style={{ marginBottom: 20 }}>
          <div style={{ display: "flex", gap: 5, marginBottom: 14 }}>
            {STATS.map(s => (
              <StatPill key={s} stat={s} active={driftStat === s} onClick={() => setDriftStat(s)} />
            ))}
          </div>
          {drift.length === 0 ? (
            <div style={{ color: T.textSub, fontSize: 13, padding: 12 }}>
              No drift data available. Requires completed games with projections.
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={280}>
              <LineChart data={drift} margin={{ left: 10, right: 20, top: 10, bottom: 10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={T.border} />
                <XAxis dataKey="date" tick={{ fontSize: 9, fill: T.textSub }} />
                <YAxis tick={{ fontSize: 10, fill: T.textSub }} />
                <Tooltip
                  contentStyle={{ fontSize: 12, borderRadius: 6, border: `1px solid ${T.border}` }}
                  formatter={(v, name) => [v, name === "error" ? "Avg Error" : name]}
                  labelFormatter={v => `Date: ${v}`}
                />
                <ReferenceLine y={0} stroke={T.textFaint} strokeDasharray="5 5" />
                <Line dataKey="error" stroke={T.accent} strokeWidth={2} dot={{ r: 2 }} name="Avg Error" />
              </LineChart>
            </ResponsiveContainer>
          )}
        </Card>

        {/* Two-column row: Edge Realization + Projection Distribution */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 20 }}>

          {/* Section 7 — Edge Realization */}
          <Card title="Edge Realization (ROI by Probability)">
            {edgeRealization.length === 0 ? (
              <div style={{ color: T.textSub, fontSize: 13, padding: 12 }}>
                No bet results data available.
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={edgeRealization} margin={{ left: 10, right: 20, top: 4, bottom: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={T.border} />
                  <XAxis dataKey="range" tick={{ fontSize: 10, fill: T.textSub }} />
                  <YAxis tick={{ fontSize: 10, fill: T.textSub }} label={{ value: "Avg Profit", angle: -90, position: "insideLeft", offset: 10, fontSize: 11, fill: T.textSub }} />
                  <Tooltip
                    contentStyle={{ fontSize: 12, borderRadius: 6, border: `1px solid ${T.border}` }}
                    formatter={(v) => [`$${v.toFixed(2)}`, "Avg Profit"]}
                  />
                  <ReferenceLine y={0} stroke={T.textFaint} strokeDasharray="5 5" />
                  <Bar dataKey="roi" radius={[4, 4, 0, 0]} maxBarSize={40}>
                    {edgeRealization.map((b, i) => (
                      <Cell key={i} fill={b.roi >= 0 ? T.accent : T.danger} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </Card>

          {/* Section 8 — Projection Distribution */}
          <Card title="Projection Distribution">
            <div style={{ display: "flex", gap: 5, marginBottom: 14 }}>
              {STATS.map(s => (
                <StatPill key={s} stat={s} active={projDistStat === s} onClick={() => setProjDistStat(s)} />
              ))}
            </div>
            {projDist.length === 0 ? (
              <div style={{ color: T.textSub, fontSize: 13, padding: 12 }}>
                No projection data available.
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={projDist} margin={{ left: 10, right: 20, top: 4, bottom: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={T.border} />
                  <XAxis dataKey="range" tick={{ fontSize: 10, fill: T.textSub }} />
                  <YAxis tick={{ fontSize: 10, fill: T.textSub }} />
                  <Tooltip
                    contentStyle={{ fontSize: 12, borderRadius: 6, border: `1px solid ${T.border}` }}
                    formatter={(v) => [v, "Players"]}
                  />
                  <Bar dataKey="count" fill={T.blue} radius={[4, 4, 0, 0]} maxBarSize={40} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </Card>
        </div>

        {/* Section 9 — Global SHAP Drivers */}
        <Card title="Global SHAP Drivers (Avg |SHAP|)" style={{ marginBottom: 20 }}>
          <div style={{ display: "flex", gap: 5, marginBottom: 14 }}>
            {STATS.map(s => (
              <StatPill key={s} stat={s} active={globalDriversStat === s} onClick={() => setGlobalDriversStat(s)} />
            ))}
          </div>
          {globalDrivers.length === 0 ? (
            <div style={{ color: T.textSub, fontSize: 13, padding: 12 }}>
              No SHAP data available. Run the projection pipeline to generate explanations.
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={320}>
              <BarChart
                data={globalDrivers.map(d => ({
                  name: FEATURE_LABELS[d.feature] || d.feature,
                  value: d.avg_shap,
                }))}
                layout="vertical"
                margin={{ left: 10, right: 20, top: 4, bottom: 4 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke={T.border} horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 10, fill: T.textSub }} />
                <YAxis
                  type="category" dataKey="name" width={120}
                  tick={{ fontSize: 10, fill: T.textMid }}
                />
                <Tooltip
                  contentStyle={{ fontSize: 12, borderRadius: 6, border: `1px solid ${T.border}` }}
                  formatter={(v) => [v.toFixed(4), "Avg |SHAP|"]}
                />
                <Bar dataKey="value" radius={[0, 4, 4, 0]} maxBarSize={18}>
                  {globalDrivers.map((_, i) => (
                    <Cell key={i} fill={i < 3 ? T.warn : i < 6 ? T.blue : T.textFaint} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </Card>
      </div>
    </div>
  );
}
