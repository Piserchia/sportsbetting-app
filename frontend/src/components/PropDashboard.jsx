import { useState, useEffect, useCallback } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ReferenceLine, ResponsiveContainer, AreaChart, Area, Cell,
} from "recharts";

const API = "http://localhost:8000";
const CURRENT_SEASON = "2025-26";

// ── Utilities ──────────────────────────────────────────────────────────────
const formatOdds = (n) => {
  if (n === null || n === undefined) return "—";
  return n > 0 ? `+${n}` : `${n}`;
};
const edgeColor = (edge) => {
  if (edge === null || edge === undefined) return "#444";
  const e = parseFloat(edge);
  if (e >= 5)  return "#00ff88";
  if (e >= 2)  return "#aaff44";
  if (e <= -5) return "#ff4455";
  if (e <= -2) return "#ff8844";
  return "#666";
};
const severityColor = (s) => ({ HIGH:"#00ff88",GOOD:"#00ff88",NEUTRAL:"#888",CAUTION:"#ffaa00",BAD:"#ff4455" }[s]||"#666");

// ── Sub-components ─────────────────────────────────────────────────────────
const StatBadge = ({ label, value, sub }) => (
  <div style={{ background:"rgba(255,255,255,0.04)", border:"1px solid rgba(255,255,255,0.08)", borderRadius:4, padding:"10px 16px", minWidth:90 }}>
    <div style={{ color:"#555", fontSize:10, letterSpacing:"0.12em", fontFamily:"monospace", marginBottom:4 }}>{label}</div>
    <div style={{ color:"#e8e8e8", fontSize:22, fontFamily:"monospace", fontWeight:700, lineHeight:1 }}>{value??'—'}</div>
    {sub && <div style={{ color:"#444", fontSize:10, fontFamily:"monospace", marginTop:3 }}>{sub}</div>}
  </div>
);

const SectionLabel = ({ children }) => (
  <div style={{ color:"#333", fontSize:10, letterSpacing:"0.18em", fontFamily:"monospace", textTransform:"uppercase", marginBottom:12, paddingBottom:6, borderBottom:"1px solid #1a1a1a" }}>{children}</div>
);

const Spinner = () => (
  <div style={{ color:"#333", fontFamily:"monospace", fontSize:11, padding:40, textAlign:"center" }}>LOADING...</div>
);

const DistTooltip = ({ active, payload, ladder }) => {
  if (!active||!payload?.length) return null;
  const x = payload[0]?.payload?.x;
  const nearby = ladder?.find(p => Math.abs(p.line - x) < 0.6);
  return (
    <div style={{ background:"#0e0e0e", border:"1px solid #222", borderRadius:4, padding:"8px 12px", fontFamily:"monospace", fontSize:11 }}>
      <div style={{ color:"#666" }}>score: <span style={{ color:"#e8e8e8" }}>{x}</span></div>
      {nearby && <div style={{ color:"#00ff88", marginTop:2 }}>P(≥{nearby.line}) = {(nearby.probability*100).toFixed(0)}%</div>}
    </div>
  );
};

// ── Player Search ──────────────────────────────────────────────────────────
function PlayerSearch({ onSelect }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (query.length < 2) { setResults([]); return; }
    const t = setTimeout(async () => {
      try {
        const r = await fetch(`${API}/players?q=${encodeURIComponent(query)}&limit=10`);
        setResults(await r.json());
        setOpen(true);
      } catch { setResults([]); }
    }, 250);
    return () => clearTimeout(t);
  }, [query]);

  return (
    <div style={{ position:"relative", width:300 }}>
      <input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search player..."
        style={{ width:"100%", background:"#0e0e0e", border:"1px solid #222", borderRadius:4, padding:"8px 14px", color:"#e8e8e8", fontFamily:"monospace", fontSize:12, outline:"none" }}
        onFocus={() => results.length && setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)} />
      {open && results.length > 0 && (
        <div style={{ position:"absolute", top:"100%", left:0, right:0, zIndex:100, background:"#0e0e0e", border:"1px solid #222", borderRadius:4, marginTop:2, maxHeight:280, overflowY:"auto" }}>
          {results.map(p => (
            <div key={p.player_id} onMouseDown={() => { onSelect(p); setQuery(p.full_name); setOpen(false); }}
              style={{ padding:"8px 14px", cursor:"pointer", fontSize:12, fontFamily:"monospace", borderBottom:"1px solid #141414", display:"flex", justifyContent:"space-between" }}
              onMouseEnter={e=>e.currentTarget.style.background="#151515"}
              onMouseLeave={e=>e.currentTarget.style.background="transparent"}>
              <span style={{ color:"#ccc" }}>{p.full_name}</span>
              <span style={{ color:"#333" }}>{p.team}</span>
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
      const [p, log, sim, props] = await Promise.all([pRes.json(), lRes.json(), sRes.ok?sRes.json():null, prRes.ok?prRes.json():null]);
      setProfile(p); setGameLog(Array.isArray(log)?log:[]); setSimData(sim); setPropsData(props);
      if (sim?.ladder?.length) {
        const closest = sim.ladder.reduce((prev, curr) => Math.abs(curr.line - sim.mean) < Math.abs(prev.line - sim.mean) ? curr : prev);
        setSelectedLine(closest.line);
      }
      if (p.next_game_id) {
        const fRes = await fetch(`${API}/games/${p.next_game_id}/matchup-flags?player_id=${pid}`);
        if (fRes.ok) { const fd = await fRes.json(); setFlags(fd.flags||[]); }
      } else { setFlags([]); }
    } catch(e) { setError(e.message); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { if (playerId) loadPlayer(playerId, activeStat); }, [activeStat, playerId]);

  const handleSelect = (p) => { setPlayerId(p.player_id); loadPlayer(p.player_id, activeStat); };

  const ladder    = propsData?.lines || simData?.ladder || [];
  const selProp   = ladder.find(p => p.line === selectedLine);
  const logStat   = activeStat;
  const logValues = gameLog.map(g => g[logStat]??0);
  const hit10     = selectedLine ? gameLog.filter(g => (g[logStat]??0) >= selectedLine).length : 0;
  const bookKeys  = selProp ? Object.keys(selProp.books||{}) : [];

  return (
    <div style={{ background:"#080808", minHeight:"100vh", color:"#e8e8e8", fontFamily:"'IBM Plex Mono','Courier New',monospace" }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@300;400;500;600;700&family=Bebas+Neue&display=swap');
        *{box-sizing:border-box}
        ::-webkit-scrollbar{width:4px}::-webkit-scrollbar-track{background:#0e0e0e}::-webkit-scrollbar-thumb{background:#222;border-radius:2px}
        .prop-row:hover{background:rgba(0,255,136,0.04)!important;cursor:pointer}
        .stat-tab{transition:all 0.15s;cursor:pointer}
        .flag-row:hover{background:rgba(255,255,255,0.03)!important}
        .hover-row:hover{background:rgba(255,255,255,0.02)!important}
      `}</style>

      <div style={{ maxWidth:1400, margin:"0 auto", padding:"24px 28px" }}>

        {/* Header */}
        <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:24, paddingBottom:18, borderBottom:"1px solid #141414" }}>
          <div style={{ display:"flex", alignItems:"center", gap:24 }}>
            <span style={{ fontFamily:"'Bebas Neue',sans-serif", fontSize:22, letterSpacing:"0.1em", color:"#00ff88" }}>PROPMODEL</span>
            <PlayerSearch onSelect={handleSelect} />
          </div>
          <div style={{ color:"#222", fontSize:10, letterSpacing:"0.1em" }}>{new Date().toLocaleTimeString()} · {CURRENT_SEASON}</div>
        </div>

        {!playerId && !loading && (
          <div style={{ display:"flex", alignItems:"center", justifyContent:"center", height:"60vh", color:"#222", fontSize:13, letterSpacing:"0.1em" }}>
            SEARCH FOR A PLAYER TO BEGIN
          </div>
        )}
        {error && <div style={{ color:"#ff4455", fontFamily:"monospace", fontSize:12, padding:20 }}>ERROR: {error}</div>}
        {loading && <Spinner />}

        {profile && !loading && (
          <>
            {/* Player header */}
            <div style={{ display:"flex", justifyContent:"space-between", alignItems:"flex-start", marginBottom:24 }}>
              <div>
                <div style={{ display:"flex", alignItems:"center", gap:12, marginBottom:6 }}>
                  <span style={{ fontFamily:"'Bebas Neue',sans-serif", fontSize:40, letterSpacing:"0.04em", lineHeight:1 }}>{profile.full_name}</span>
                  {profile.is_active && <span style={{ background:"#00ff88", color:"#000", fontSize:10, fontWeight:700, padding:"3px 8px", borderRadius:2, letterSpacing:"0.1em" }}>ACTIVE</span>}
                </div>
                <div style={{ color:"#444", fontSize:11, letterSpacing:"0.08em" }}>
                  {profile.team}{profile.opponent&&` · vs ${profile.opponent}`}{profile.next_game_date&&` · ${profile.next_game_date}`}
                </div>
              </div>
              <div style={{ display:"flex", gap:10, flexWrap:"wrap", justifyContent:"flex-end" }}>
                <StatBadge label="L10 AVG"   value={profile.l10_avg_pts}         sub="pts" />
                <StatBadge label="L5 AVG"    value={profile.l5_avg_pts}          sub="pts" />
                <StatBadge label="SEASON"    value={profile.season_avg_pts}      sub="pts avg" />
                <StatBadge label="MIN PROJ"  value={profile.minutes_projection}  sub="minutes" />
              </div>
            </div>

            {/* Stat tabs */}
            <div style={{ display:"flex", gap:4, marginBottom:24 }}>
              {["points","rebounds","assists"].map(s => (
                <button key={s} className="stat-tab" onClick={()=>setActiveStat(s)} style={{
                  background:activeStat===s?"#00ff88":"transparent",
                  color:activeStat===s?"#000":"#444",
                  border:`1px solid ${activeStat===s?"#00ff88":"#1e1e1e"}`,
                  borderRadius:2, padding:"6px 18px", fontSize:11, fontFamily:"monospace",
                  letterSpacing:"0.12em", textTransform:"uppercase",
                  fontWeight:activeStat===s?700:400, cursor:"pointer",
                }}>{s}</button>
              ))}
              <div style={{ marginLeft:"auto", color:"#2a2a2a", fontSize:10, alignSelf:"center" }}>
                {propsData?.source==="model_only"?"MODEL ONLY · NO SPORTSBOOK DATA":"LIVE SPORTSBOOK DATA"}
              </div>
            </div>

            {/* Main grid */}
            <div style={{ display:"grid", gridTemplateColumns:"1fr 380px", gap:20, marginBottom:20 }}>

              {/* Left */}
              <div style={{ display:"flex", flexDirection:"column", gap:20 }}>

                {/* Distribution */}
                {simData && (
                  <div style={{ background:"#0a0a0a", border:"1px solid #151515", borderRadius:6, padding:"20px 20px 12px" }}>
                    <SectionLabel>Monte Carlo Distribution · 10,000 Simulations</SectionLabel>
                    <div style={{ display:"flex", gap:20, marginBottom:14 }}>
                      <div><span style={{ color:"#333", fontSize:10 }}>MEAN </span><span style={{ color:"#00ff88", fontSize:13, fontWeight:700 }}>{simData.mean}</span></div>
                      <div><span style={{ color:"#333", fontSize:10 }}>σ </span><span style={{ color:"#666", fontSize:13 }}>{simData.std_dev}</span></div>
                      {selectedLine&&selProp&&<div><span style={{ color:"#333", fontSize:10 }}>P(≥{selectedLine}) </span><span style={{ color:"#00ff88", fontSize:13, fontWeight:700 }}>{selProp.model_prob?(selProp.model_prob*100).toFixed(0)+"%" : "—"}</span></div>}
                    </div>
                    <ResponsiveContainer width="100%" height={180}>
                      <AreaChart data={simData.curve} margin={{ top:0, right:0, left:-30, bottom:0 }}>
                        <defs>
                          <linearGradient id="dg" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%"  stopColor="#00ff88" stopOpacity={0.3}/>
                            <stop offset="95%" stopColor="#00ff88" stopOpacity={0.02}/>
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="2 4" stroke="#111" vertical={false}/>
                        <XAxis dataKey="x" stroke="#222" tick={{ fill:"#333", fontSize:9, fontFamily:"monospace" }} tickLine={false} interval={9}/>
                        <YAxis stroke="transparent" tick={false}/>
                        <Tooltip content={<DistTooltip ladder={ladder}/>}/>
                        {selectedLine&&<ReferenceLine x={selectedLine} stroke="#00ff88" strokeWidth={1.5} strokeDasharray="4 3" label={{ value:`${selectedLine}`, fill:"#00ff88", fontSize:10, fontFamily:"monospace" }}/>}
                        <ReferenceLine x={simData.mean} stroke="#fff" strokeWidth={1} strokeDasharray="2 4" label={{ value:"μ", fill:"#555", fontSize:10 }}/>
                        {ladder.filter(p=>p.line!==selectedLine).map(p=>(
                          <ReferenceLine key={p.line} x={p.line} stroke="#1e3a28" strokeWidth={1} strokeDasharray="1 5"/>
                        ))}
                        <Area type="monotone" dataKey="y" stroke="#00ff88" strokeWidth={1.5} fill="url(#dg)" dot={false}/>
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                )}

                {/* Bar chart */}
                {gameLog.length > 0 && (
                  <div style={{ background:"#0a0a0a", border:"1px solid #151515", borderRadius:6, padding:"20px 20px 12px" }}>
                    <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:4 }}>
                      <SectionLabel>Last {gameLog.length} Games · {activeStat}</SectionLabel>
                      {selectedLine&&<div style={{ color:"#333", fontSize:10, marginBottom:12 }}>
                        {hit10}/{gameLog.length} hit {selectedLine}+
                        <span style={{ marginLeft:8, color:hit10/gameLog.length>=0.6?"#00ff88":hit10/gameLog.length>=0.4?"#ffaa00":"#ff4455", fontWeight:700 }}>
                          ({(hit10/gameLog.length*100).toFixed(0)}%)
                        </span>
                      </div>}
                    </div>
                    <ResponsiveContainer width="100%" height={160}>
                      <BarChart data={[...gameLog].reverse()} margin={{ top:4, right:0, left:-30, bottom:0 }}>
                        <CartesianGrid strokeDasharray="2 4" stroke="#111" vertical={false}/>
                        <XAxis dataKey="matchup" stroke="#222" tick={{ fill:"#333", fontSize:9, fontFamily:"monospace" }} tickLine={false}/>
                        <YAxis stroke="transparent" tick={{ fill:"#333", fontSize:9, fontFamily:"monospace" }}/>
                        <Tooltip/>
                        {selectedLine&&<ReferenceLine y={selectedLine} stroke="#00ff88" strokeWidth={1} strokeDasharray="4 3" label={{ value:`${selectedLine}`, fill:"#00ff88", fontSize:9, fontFamily:"monospace", position:"right" }}/>}
                        <Bar dataKey={logStat} name={activeStat.toUpperCase()} radius={[2,2,0,0]}>
                          {[...gameLog].reverse().map((g,i)=>(
                            <Cell key={i} fill={selectedLine&&(g[logStat]??0)>=selectedLine?"#00ff88":"#1a2a1a"}/>
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                )}

                {/* Game log table */}
                {gameLog.length > 0 && (
                  <div style={{ background:"#0a0a0a", border:"1px solid #151515", borderRadius:6, padding:"20px" }}>
                    <SectionLabel>Game Log · Last {gameLog.length}</SectionLabel>
                    <table style={{ width:"100%", borderCollapse:"collapse", fontSize:11 }}>
                      <thead>
                        <tr style={{ color:"#2a2a2a", borderBottom:"1px solid #151515" }}>
                          {["DATE","MATCHUP","MIN","PTS","REB","AST","STL","BLK","TOV"].map(h=>(
                            <th key={h} style={{ textAlign:"right", padding:"4px 8px", fontWeight:400, letterSpacing:"0.08em", fontSize:9 }}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {gameLog.map((g,i)=>(
                          <tr key={i} className="hover-row" style={{ borderBottom:"1px solid #0d0d0d" }}>
                            <td style={{ padding:"6px 8px", color:"#444", textAlign:"right", fontSize:10 }}>{g.date}</td>
                            <td style={{ padding:"6px 8px", color:"#555", textAlign:"right" }}>{g.matchup}</td>
                            <td style={{ padding:"6px 8px", color:"#555", textAlign:"right" }}>{g.minutes}</td>
                            {["points","rebounds","assists","steals","blocks","turnovers"].map(s=>(
                              <td key={s} style={{ padding:"6px 8px", textAlign:"right", fontWeight:s===logStat?700:400,
                                color:s===logStat?(selectedLine&&g[s]>=selectedLine?"#00ff88":selectedLine&&g[s]>=selectedLine*0.85?"#ffaa00":"#666"):"#444" }}>
                                {g[s]??'—'}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

              {/* Right */}
              <div style={{ display:"flex", flexDirection:"column", gap:20 }}>

                {/* Flags */}
                <div style={{ background:"#0a0a0a", border:"1px solid #151515", borderRadius:6, padding:"20px" }}>
                  <SectionLabel>Matchup Intelligence{profile.opponent?` · vs ${profile.opponent}`:""}</SectionLabel>
                  {flags.length===0
                    ? <div style={{ color:"#2a2a2a", fontSize:11 }}>{profile.opponent?"No flags — build more data.":"No upcoming game found."}</div>
                    : <div style={{ display:"flex", flexDirection:"column", gap:8 }}>
                        {flags.map((flag,i)=>(
                          <div key={i} className="flag-row" style={{ display:"flex", alignItems:"flex-start", gap:10, padding:"10px 12px", borderRadius:4,
                            border:`1px solid ${severityColor(flag.severity)}22`, background:`${severityColor(flag.severity)}08` }}>
                            <span style={{ fontSize:14, lineHeight:1.4 }}>{flag.icon}</span>
                            <div>
                              <div style={{ color:severityColor(flag.severity), fontSize:9, letterSpacing:"0.1em", marginBottom:2 }}>{flag.type}</div>
                              <div style={{ color:"#888", fontSize:11, lineHeight:1.4 }}>{flag.label}</div>
                            </div>
                          </div>
                        ))}
                      </div>
                  }
                </div>

                {/* Prop ladder */}
                <div style={{ background:"#0a0a0a", border:"1px solid #151515", borderRadius:6, padding:"20px" }}>
                  <SectionLabel>Alternate Lines · Click to Analyze</SectionLabel>

                  {selProp && (
                    <div style={{ background:"#050505", border:"1px solid #00ff8833", borderRadius:4, padding:"14px 16px", marginBottom:16 }}>
                      <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:10 }}>
                        <div>
                          <span style={{ color:"#444", fontSize:10, letterSpacing:"0.1em" }}>LINE </span>
                          <span style={{ color:"#e8e8e8", fontSize:20, fontWeight:700 }}>{selProp.line}</span>
                          <span style={{ color:"#444", fontSize:11, marginLeft:4 }}>{activeStat.slice(0,3)}</span>
                        </div>
                        <div style={{ textAlign:"right" }}>
                          <div style={{ color:"#444", fontSize:9, letterSpacing:"0.1em", marginBottom:2 }}>MODEL PROB</div>
                          <div style={{ color:"#00ff88", fontSize:18, fontWeight:700 }}>{selProp.model_prob?(selProp.model_prob*100).toFixed(0)+"%":"—"}</div>
                        </div>
                      </div>
                      <div style={{ display:"flex", gap:8 }}>
                        <div style={{ flex:1, background:"#0a0a0a", borderRadius:3, padding:"8px 10px" }}>
                          <div style={{ color:"#333", fontSize:9, letterSpacing:"0.08em", marginBottom:3 }}>FAIR ODDS</div>
                          <div style={{ color:"#e8e8e8", fontSize:14, fontWeight:700 }}>{formatOdds(selProp.fair_odds)}</div>
                        </div>
                        {bookKeys.slice(0,2).map(book=>(
                          <div key={book} style={{ flex:1, background:"#0a0a0a", borderRadius:3, padding:"8px 10px" }}>
                            <div style={{ color:"#333", fontSize:9, letterSpacing:"0.08em", marginBottom:3 }}>{book.toUpperCase().slice(0,6)} EDGE</div>
                            <div style={{ color:edgeColor(selProp.books[book].edge), fontSize:14, fontWeight:700 }}>
                              {selProp.books[book].edge!==null?`${selProp.books[book].edge>0?"+":""}${selProp.books[book].edge}%`:"—"}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  <table style={{ width:"100%", borderCollapse:"collapse", fontSize:11 }}>
                    <thead>
                      <tr style={{ color:"#2a2a2a", borderBottom:"1px solid #141414" }}>
                        {["LINE","MODEL","FAIR",...(propsData?.source!=="model_only"?bookKeys.slice(0,2).map(b=>b.toUpperCase().slice(0,6)):[]),"EDGE"].map(h=>(
                          <th key={h} style={{ textAlign:"right", padding:"4px 6px", fontWeight:400, fontSize:9 }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {ladder.map((p,i)=>{
                        const isSelected = p.line===selectedLine;
                        const bArr = Object.values(p.books||{});
                        const topEdge = bArr.length?Math.max(...bArr.map(b=>b.edge??-99)):null;
                        return (
                          <tr key={i} className="prop-row" onClick={()=>setSelectedLine(p.line)}
                            style={{ borderBottom:"1px solid #0d0d0d", background:isSelected?"rgba(0,255,136,0.06)":"transparent" }}>
                            <td style={{ padding:"7px 6px", textAlign:"right", fontWeight:isSelected?700:400, color:isSelected?"#00ff88":"#666" }}>{p.line}+</td>
                            <td style={{ padding:"7px 6px", textAlign:"right", color:"#00ff88", fontWeight:600 }}>{p.model_prob?(p.model_prob*100).toFixed(0)+"%":"—"}</td>
                            <td style={{ padding:"7px 6px", textAlign:"right", color:"#555" }}>{formatOdds(p.fair_odds)}</td>
                            {propsData?.source!=="model_only"&&bookKeys.slice(0,2).map(book=>(
                              <td key={book} style={{ padding:"7px 6px", textAlign:"right", color:"#555" }}>{p.books?.[book]?formatOdds(p.books[book].over_odds):"—"}</td>
                            ))}
                            <td style={{ padding:"7px 6px", textAlign:"right", fontWeight:700, color:edgeColor(topEdge) }}>
                              {topEdge!==null&&topEdge>-99?`${topEdge>0?"+":""}${topEdge}%`:"—"}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>

                {/* Model info */}
                <div style={{ background:"#0a0a0a", border:"1px solid #151515", borderRadius:6, padding:"16px 20px" }}>
                  <SectionLabel>Model Info</SectionLabel>
                  <div style={{ display:"flex", flexDirection:"column", gap:8 }}>
                    {[
                      { label:"Games in sample",    value:profile.games_played },
                      { label:"Points projection",  value:profile.points_projection?`${profile.points_projection} pts`:"—" },
                      { label:"Minutes projection", value:profile.minutes_projection?`${profile.minutes_projection} min`:"—" },
                      { label:"Simulations",        value:"10,000" },
                    ].map((item,i)=>(
                      <div key={i} style={{ display:"flex", justifyContent:"space-between" }}>
                        <span style={{ color:"#333", fontSize:10 }}>{item.label}</span>
                        <span style={{ color:"#666", fontSize:10 }}>{item.value}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>

            <div style={{ borderTop:"1px solid #111", paddingTop:14, display:"flex", justifyContent:"space-between" }}>
              <div style={{ color:"#1e1e1e", fontSize:9, letterSpacing:"0.1em" }}>DATA: NBA.COM · ODDS: SPORTSGAMEODDS · MODEL: MONTE CARLO v1.2</div>
              <div style={{ color:"#1e1e1e", fontSize:9, letterSpacing:"0.1em" }}>FOR ANALYTICAL USE ONLY</div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
