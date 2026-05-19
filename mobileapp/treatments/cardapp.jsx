// CARD-APP — 2 pages (Overview + Financial Goal). Warm, rounded, friendly.
// Data-only copy — no recommendations.

const caStyles = (dark) => {
  const t = dark ? window.RITA.dark : window.RITA.light;
  return { page:{ minHeight:'100%', background:t.bg, color:t.text, fontFamily:window.RITA.fd, padding:'0 0 90px' } };
};

function CaTabBar({ dark, active='home' }) {
  const t = dark ? window.RITA.dark : window.RITA.light;
  const tabs = [
    ['home','Home','M3 10l7-7 7 7v9a1 1 0 01-1 1h-4v-6h-4v6H4a1 1 0 01-1-1v-9z'],
    ['goal','Goal','M10 3v14M3 10h14'],
    ['market','Market','M3 14l4-4 3 3 7-7'],
    ['sig','Signals','M10 2l2 6h6l-5 4 2 6-5-4-5 4 2-6-5-4h6z'],
    ['strat','Strategy','M4 4h12v12H4zM4 10h12M10 4v12'],
  ];
  return (
    <div style={{ position:'absolute', bottom:16, left:12, right:12,
      background:t.surface, borderRadius:28,
      boxShadow:'0 8px 24px rgba(0,0,0,.12), 0 0 0 1px rgba(0,0,0,.04)',
      display:'flex', padding:'10px 6px 12px' }}>
      {tabs.map(([k,label,d])=>{
        const isActive = active===k;
        return (
          <div key={k} style={{ flex:1, display:'flex', flexDirection:'column', alignItems:'center', gap:3,
            padding:'6px 0', borderRadius:20, background: isActive ? window.RITA.buildBg : 'transparent' }}>
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none"
              stroke={isActive ? window.RITA.build : t.t3} strokeWidth="1.6"
              strokeLinecap="round" strokeLinejoin="round"><path d={d}/></svg>
            <span style={{ fontSize:10, fontWeight: isActive?700:500,
              color: isActive ? window.RITA.build : t.t3 }}>{label}</span>
          </div>
        );
      })}
    </div>
  );
}

function CaChat({ dark }) {
  return (
    <div style={{ position:'absolute', right:20, bottom:112, zIndex:60,
      width:56, height:56, borderRadius:28,
      background:`linear-gradient(135deg, ${window.RITA.chat}, #E94BA3)`,
      color:'#fff', display:'flex', alignItems:'center', justifyContent:'center',
      boxShadow:'0 10px 28px rgba(190,24,93,.45)' }}>
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 11.5a8.38 8.38 0 01-.9 3.8 8.5 8.5 0 01-7.6 4.7 8.38 8.38 0 01-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 01-.9-3.8 8.5 8.5 0 014.7-7.6 8.38 8.38 0 013.8-.9h.5a8.48 8.48 0 018 8v.5z"/>
      </svg>
    </div>
  );
}

function CardAppOverview({ dark, data }) {
  const t = dark ? window.RITA.dark : window.RITA.light;
  const up = data.changeDir==='up', flat = data.changeDir==='flat';
  const pc = flat ? t.t2 : up ? window.RITA.build : window.RITA.danger;
  const bgAccent = flat ? t.surface2 : up ? window.RITA.buildBg : window.RITA.dangerBg;

  return (
    <div style={caStyles(dark).page}>
      <div style={{ padding:'60px 22px 14px', display:'flex', justifyContent:'space-between', alignItems:'center' }}>
        <div>
          <div style={{ fontSize:12, color:t.t3, marginBottom:2 }}>Tuesday morning</div>
          <div style={{ fontSize:22, fontWeight:700, letterSpacing:'-0.01em' }}>Hi, Rita 👋</div>
        </div>
        <div style={{ width:40, height:40, borderRadius:20, background:t.surface,
          border:`1px solid ${t.border}`, display:'flex', alignItems:'center', justifyContent:'center',
          fontFamily:window.RITA.fs, fontSize:16, color:t.t2 }}>R</div>
      </div>

      <div style={{ margin:'6px 16px 14px', padding:22, borderRadius:22,
        background:bgAccent, position:'relative', overflow:'hidden' }}>
        <div style={{ display:'flex', alignItems:'center', gap:6, marginBottom:10 }}>
          <span style={{ width:6, height:6, borderRadius:'50%', background:data.stateColor }} />
          <span style={{ fontSize:11, fontWeight:600, color:data.stateColor, letterSpacing:'0.04em' }}>
            {data.state.toUpperCase()} MARKET
          </span>
        </div>
        <div style={{ fontSize:13, color:t.t2, marginBottom:4 }}>{data.instrument}</div>
        <div style={{ fontFamily:window.RITA.fm, fontSize:34, fontWeight:500, letterSpacing:'-0.02em' }}>{data.price}</div>
        <div style={{ fontFamily:window.RITA.fm, fontSize:13, color:pc, marginTop:3 }}>
          {data.change} · {data.changePct}
        </div>
        <svg width="100%" height="50" viewBox="0 0 280 50" style={{ marginTop:10, display:'block' }}>
          <defs>
            <linearGradient id={`grad-ca-${data.state}`} x1="0" x2="0" y1="0" y2="1">
              <stop offset="0" stopColor={pc} stopOpacity="0.25"/>
              <stop offset="1" stopColor={pc} stopOpacity="0"/>
            </linearGradient>
          </defs>
          <polygon fill={`url(#grad-ca-${data.state})`}
            points={`0,50 ${data.sparkline.map((v,i)=>`${i*(280/19)},${50-(v/34)*42-2}`).join(' ')} 280,50`} />
          <polyline fill="none" stroke={pc} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
            points={data.sparkline.map((v,i)=>`${i*(280/19)},${50-(v/34)*42-2}`).join(' ')} />
        </svg>
      </div>

      <div style={{ margin:'0 16px 14px', padding:18, borderRadius:18, background:t.surface,
        boxShadow:'0 2px 10px rgba(0,0,0,.04)', border:`1px solid ${t.border}` }}>
        <div style={{ display:'flex', justifyContent:'space-between', alignItems:'flex-start', marginBottom:10 }}>
          <div>
            <div style={{ fontSize:11, color:t.t3, letterSpacing:'0.04em', textTransform:'uppercase' }}>Your yearly goal</div>
            <div style={{ fontSize:18, fontWeight:700, marginTop:2 }}>{data.goal.current} of {data.goal.target}</div>
          </div>
          <div style={{ fontSize:11, fontWeight:700, padding:'4px 10px', borderRadius:100,
            background:window.RITA.buildBg, color:window.RITA.build }}>{data.goal.progress}%</div>
        </div>
        <div style={{ height:8, borderRadius:4, background:t.surface2, overflow:'hidden' }}>
          <div style={{ height:'100%', width:`${data.goal.progress}%`, borderRadius:4,
            background:`linear-gradient(90deg, ${window.RITA.build}, #2D9456)` }} />
        </div>
        <div style={{ fontSize:12, color:t.t3, marginTop:8 }}>
          Pace suggests {data.goal.runway} to reach target.
        </div>
      </div>

      <div style={{ padding:'0 22px 6px', display:'flex', justifyContent:'space-between', alignItems:'baseline' }}>
        <div style={{ fontSize:15, fontWeight:700 }}>Signals today</div>
        <div style={{ fontSize:12, color:window.RITA.run, fontWeight:600 }}>See all</div>
      </div>

      <div style={{ padding:'8px 16px 0', display:'flex', flexDirection:'column', gap:10 }}>
        {data.signals.slice(0,2).map((sig,i)=>{
          const c = window.RITA[sig.sev] || t.text;
          const bg = window.RITA[sig.sev + 'Bg'] || t.surface;
          return (
            <div key={i} style={{ padding:16, borderRadius:16, background:t.surface, border:`1px solid ${t.border}` }}>
              <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:8 }}>
                <div style={{ width:36, height:36, borderRadius:12, background:bg,
                  display:'flex', alignItems:'center', justifyContent:'center',
                  fontSize:16, fontWeight:700, color:c }}>•</div>
                <div style={{ flex:1 }}>
                  <div style={{ fontSize:10, fontWeight:700, color:c, letterSpacing:'0.06em' }}>{sig.tag}</div>
                  <div style={{ fontSize:14, fontWeight:600, color:t.text, lineHeight:1.3 }}>{sig.title}</div>
                </div>
                <div style={{ fontSize:10, color:t.t4 }}>{sig.when}</div>
              </div>
              <div style={{ fontSize:12, color:t.t2, lineHeight:1.5 }}>{sig.body}</div>
            </div>
          );
        })}
      </div>

      <CaChat dark={dark} />
      <CaTabBar dark={dark} active="home" />
    </div>
  );
}

function CardAppGoal({ dark, data }) {
  const t = dark ? window.RITA.dark : window.RITA.light;
  return (
    <div style={caStyles(dark).page}>
      <div style={{ padding:'60px 22px 10px' }}>
        <div style={{ fontSize:12, color:t.t3 }}>Financial Goal</div>
        <div style={{ fontSize:28, fontWeight:700, letterSpacing:'-0.02em', marginTop:4 }}>
          Target {data.goal.target} this year
        </div>
      </div>

      <div style={{ margin:'14px 16px', padding:22, borderRadius:22, background:t.surface,
        border:`1px solid ${t.border}`, display:'flex', gap:16, alignItems:'center' }}>
        <svg width="110" height="110" viewBox="0 0 110 110">
          <circle cx="55" cy="55" r="46" fill="none" stroke={t.surface2} strokeWidth="12"/>
          <circle cx="55" cy="55" r="46" fill="none" stroke={window.RITA.build} strokeWidth="12"
            strokeDasharray={`${(data.goal.progress/100)*2*Math.PI*46} 999`}
            strokeLinecap="round" transform="rotate(-90 55 55)" />
          <text x="55" y="58" textAnchor="middle" fontFamily={window.RITA.fm} fontSize="22" fontWeight="500" fill={t.text}>
            {data.goal.progress}%
          </text>
        </svg>
        <div style={{ flex:1 }}>
          <div style={{ fontSize:12, color:t.t3 }}>YTD return</div>
          <div style={{ fontFamily:window.RITA.fm, fontSize:24, fontWeight:500, color:window.RITA.build }}>
            {data.goal.current}
          </div>
          <div style={{ fontSize:12, color:t.t2, marginTop:6, lineHeight:1.4 }}>
            {data.goal.runway} to target at current pace.
          </div>
        </div>
      </div>

      <div style={{ padding:'6px 22px 8px', fontSize:14, fontWeight:700 }}>Milestones</div>
      <div style={{ padding:'0 16px' }}>
        {[
          { label:'First signal viewed', done:true },
          { label:'5 scenarios explored', done:true },
          { label:'10 trades logged', done:true, hint:'8 of 10' },
          { label:'6% YTD reached', done:data.goal.progress>=50 },
          { label:'12% YTD reached', done:data.goal.progress>=100 },
        ].map((m,i)=>(
          <div key={i} style={{ display:'flex', alignItems:'center', gap:12, padding:14,
            borderRadius:14, background:t.surface, border:`1px solid ${t.border}`, marginBottom:8 }}>
            <div style={{ width:24, height:24, borderRadius:12,
              background: m.done ? window.RITA.build : t.surface2,
              border: m.done ? 'none' : `1.5px solid ${t.border2}`,
              display:'flex', alignItems:'center', justifyContent:'center',
              color:'#fff', fontSize:13 }}>{m.done ? '✓' : ''}</div>
            <div style={{ flex:1, fontSize:14, color: m.done ? t.t2 : t.text,
              textDecoration: m.done ? 'line-through' : 'none' }}>{m.label}</div>
            {m.hint && <span style={{ fontSize:11, color:t.t3, fontFamily:window.RITA.fm }}>{m.hint}</span>}
          </div>
        ))}
      </div>

      <CaChat dark={dark} />
      <CaTabBar dark={dark} active="goal" />
    </div>
  );
}

Object.assign(window, { CardAppOverview, CardAppGoal, CaTabBar, CaChat });
