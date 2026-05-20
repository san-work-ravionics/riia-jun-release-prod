// SIGNAL-FEED (Novel) — 4 screens. Data-only copy. Full-bleed, severity-tinted.

const sfStyles = (dark) => {
  const t = dark ? window.RITA.dark : window.RITA.light;
  return { page: { minHeight:'100%', background:t.bg, color:t.text, fontFamily:window.RITA.fd, padding:0 } };
};

function SfTabBar({ dark, active='sig' }) {
  const t = dark ? window.RITA.dark : window.RITA.light;
  const tabs = [['home','Home'],['goal','Goal'],['market','Market'],['sig','Signals'],['strat','Strategy']];
  return (
    <div style={{ position:'absolute', bottom:0, left:0, right:0,
      background: dark ? 'rgba(22,20,15,0.85)' : 'rgba(245,243,238,0.9)',
      backdropFilter:'blur(18px)', WebkitBackdropFilter:'blur(18px)',
      borderTop:`1px solid ${t.border}`, display:'flex', padding:'10px 8px 28px' }}>
      {tabs.map(([k,label])=>(
        <div key={k} style={{ flex:1, textAlign:'center', fontSize:10,
          fontWeight: active===k?700:500, color: active===k?t.text:t.t4, letterSpacing:'0.04em' }}>
          <div style={{ width:20, height:3, margin:'0 auto 4px', borderRadius:2,
            background: active===k ? window.RITA.build : 'transparent' }} />
          {label}
        </div>
      ))}
    </div>
  );
}

function SfChat() {
  return (
    <div style={{ position:'absolute', right:16, bottom:92, zIndex:60,
      padding:'10px 14px 10px 12px', borderRadius:22,
      background:'rgba(255,255,255,0.22)', backdropFilter:'blur(14px)',
      border:'1px solid rgba(255,255,255,0.35)', color:'#fff',
      display:'flex', alignItems:'center', gap:6, fontSize:12, fontWeight:600,
      boxShadow:'0 6px 18px rgba(0,0,0,.18)' }}>
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 11.5a8.38 8.38 0 01-.9 3.8 8.5 8.5 0 01-7.6 4.7 8.38 8.38 0 01-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 01-.9-3.8 8.5 8.5 0 014.7-7.6 8.38 8.38 0 013.8-.9h.5a8.48 8.48 0 018 8v.5z"/>
      </svg>
      Ask Rita
    </div>
  );
}

function SfChatDark({ dark }) {
  const t = dark ? window.RITA.dark : window.RITA.light;
  return (
    <div style={{ position:'absolute', right:16, bottom:92, zIndex:60,
      width:52, height:52, borderRadius:26, background:window.RITA.chat, color:'#fff',
      display:'flex', alignItems:'center', justifyContent:'center',
      boxShadow:'0 10px 24px rgba(190,24,93,.4)' }}>
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 11.5a8.38 8.38 0 01-.9 3.8 8.5 8.5 0 01-7.6 4.7 8.38 8.38 0 01-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 01-.9-3.8 8.5 8.5 0 014.7-7.6 8.38 8.38 0 013.8-.9h.5a8.48 8.48 0 018 8v.5z"/>
      </svg>
    </div>
  );
}

// ── OVERVIEW (Novel) ────────────────────────────────────────
function SignalFeedOverview({ dark, data }) {
  const t = dark ? window.RITA.dark : window.RITA.light;
  const up = data.changeDir==='up', flat = data.changeDir==='flat';
  const pc = flat ? t.t2 : up ? window.RITA.build : window.RITA.danger;
  return (
    <div style={{ ...sfStyles(dark).page, position:'relative' }}>
      <div style={{ padding:'60px 22px 8px' }}>
        <div style={{ fontSize:11, color:t.t3, fontWeight:600, letterSpacing:'0.08em' }}>TUE · 21 APR</div>
        <div style={{ fontFamily:window.RITA.fs, fontSize:32, letterSpacing:'-0.02em', marginTop:6, lineHeight:1.1 }}>
          Today at a <span style={{ fontStyle:'italic', color:t.t2 }}>glance</span>
        </div>
      </div>

      {/* regime hero */}
      <div style={{ margin:'14px 16px 12px', padding:20, borderRadius:20,
        background: `linear-gradient(135deg, ${data.stateColor} 0%, ${data.stateColor}CC 100%)`, color:'#fff' }}>
        <div style={{ fontSize:10, fontWeight:700, letterSpacing:'0.12em', opacity:0.85 }}>REGIME</div>
        <div style={{ fontFamily:window.RITA.fs, fontSize:30, letterSpacing:'-0.01em', marginTop:2 }}>{data.state} market</div>
        <div style={{ display:'flex', alignItems:'baseline', gap:10, marginTop:14 }}>
          <span style={{ fontSize:12, opacity:0.85 }}>{data.instrument}</span>
          <span style={{ fontFamily:window.RITA.fm, fontSize:22, fontWeight:500, letterSpacing:'-0.01em' }}>{data.price}</span>
          <span style={{ fontFamily:window.RITA.fm, fontSize:12, opacity:0.9 }}>{data.changePct}</span>
        </div>
        <svg width="100%" height="40" viewBox="0 0 280 40" style={{ marginTop:10, display:'block' }}>
          <polyline fill="none" stroke="#fff" strokeOpacity="0.9" strokeWidth="1.8" strokeLinecap="round"
            points={data.sparkline.map((v,i)=>`${i*(280/19)},${40-(v/34)*32-2}`).join(' ')} />
        </svg>
      </div>

      {/* goal */}
      <div style={{ margin:'0 16px 12px', padding:16, borderRadius:16, background:t.surface,
        border:`1px solid ${t.border}`, display:'flex', alignItems:'center', gap:14 }}>
        <div style={{ position:'relative', width:52, height:52 }}>
          <svg width="52" height="52" viewBox="0 0 52 52">
            <circle cx="26" cy="26" r="22" fill="none" stroke={t.surface2} strokeWidth="5"/>
            <circle cx="26" cy="26" r="22" fill="none" stroke={window.RITA.build} strokeWidth="5"
              strokeDasharray={`${(data.goal.progress/100)*2*Math.PI*22} 999`} strokeLinecap="round"
              transform="rotate(-90 26 26)" />
          </svg>
          <div style={{ position:'absolute', inset:0, display:'flex', alignItems:'center', justifyContent:'center',
            fontFamily:window.RITA.fm, fontSize:12, fontWeight:600, color:t.text }}>{data.goal.progress}%</div>
        </div>
        <div style={{ flex:1 }}>
          <div style={{ fontSize:10, color:t.t3, letterSpacing:'0.06em', textTransform:'uppercase' }}>Yearly goal {data.goal.target}</div>
          <div style={{ fontSize:16, fontWeight:700, marginTop:2 }}>{data.goal.current} YTD</div>
        </div>
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke={t.t4} strokeWidth="2" strokeLinecap="round">
          <path d="M5 3l4 4-4 4"/></svg>
      </div>

      {/* signals compact list */}
      <div style={{ padding:'0 22px 6px', display:'flex', justifyContent:'space-between', alignItems:'baseline' }}>
        <div style={{ fontSize:14, fontWeight:700 }}>Signals · {data.signals.length}</div>
        <div style={{ fontSize:11, color:t.t3, fontFamily:window.RITA.fm }}>last 4 hrs</div>
      </div>
      <div style={{ padding:'8px 16px 0' }}>
        {data.signals.slice(0,3).map((sig,i)=>{
          const c = window.RITA[sig.sev] || t.text;
          return (
            <div key={i} style={{ display:'flex', gap:12, padding:'12px 0',
              borderBottom: i<2 ? `1px solid ${t.border}` : 'none', alignItems:'flex-start' }}>
              <div style={{ width:4, alignSelf:'stretch', background:c, borderRadius:2, marginTop:2 }}/>
              <div style={{ flex:1 }}>
                <div style={{ display:'flex', gap:8, alignItems:'center', marginBottom:3 }}>
                  <span style={{ fontFamily:window.RITA.fm, fontSize:9, fontWeight:600, color:c, letterSpacing:'0.08em' }}>{sig.tag}</span>
                  <span style={{ fontFamily:window.RITA.fm, fontSize:9, color:t.t4 }}>{sig.when}</span>
                </div>
                <div style={{ fontSize:13, fontWeight:600, color:t.text, lineHeight:1.3 }}>{sig.title}</div>
              </div>
            </div>
          );
        })}
      </div>
      <SfChatDark dark={dark} />
      <SfTabBar dark={dark} active="home" />
    </div>
  );
}

// ── SIGNAL HERO (single signal owns screen) ────────────────
function SignalFeedHero({ dark, data, index=0 }) {
  const t = dark ? window.RITA.dark : window.RITA.light;
  const sig = data.signals[index] || data.signals[0];
  const c = window.RITA[sig.sev] || window.RITA.run;
  return (
    <div style={{ ...sfStyles(dark).page, color:'#fff',
      background:`linear-gradient(180deg, ${c} 0%, ${c} 40%, ${t.bg} 100%)`, position:'relative' }}>
      <div style={{ padding:'58px 22px 0', display:'flex', justifyContent:'space-between',
        alignItems:'center', color:'rgba(255,255,255,.85)' }}>
        <div style={{ fontSize:11, fontWeight:600, letterSpacing:'0.12em' }}>SIGNAL {index+1} / {data.signals.length}</div>
        <div style={{ display:'flex', gap:4 }}>
          {data.signals.map((_,i)=>(
            <div key={i} style={{ width: i===index?20:6, height:3, borderRadius:2,
              background: i===index ? '#fff' : 'rgba(255,255,255,.35)' }} />
          ))}
        </div>
      </div>

      <div style={{ padding:'28px 22px 0' }}>
        <div style={{ display:'inline-block', padding:'4px 10px', borderRadius:100,
          background:'rgba(255,255,255,.22)', border:'1px solid rgba(255,255,255,.3)',
          fontSize:10, fontWeight:700, letterSpacing:'0.12em', color:'#fff' }}>{sig.tag}</div>
      </div>

      <div style={{ padding:'20px 22px 0' }}>
        <div style={{ fontFamily:window.RITA.fs, fontSize:44, lineHeight:1.05,
          letterSpacing:'-0.02em', color:'#fff', textWrap:'pretty', fontWeight:400 }}>{sig.title}</div>
        <div style={{ fontSize:13, color:'rgba(255,255,255,.9)', marginTop:16, lineHeight:1.6 }}>{sig.body}</div>
      </div>

      <div style={{ margin:'28px 22px 0', padding:'16px 18px', borderRadius:18,
        background:'rgba(255,255,255,0.14)', border:'1px solid rgba(255,255,255,.2)',
        display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:10 }}>
        {[['Instrument', data.instrument.split(' ')[0]], ['Confidence','0.78'], ['Regime', data.state]].map(([k,v])=>(
          <div key={k}>
            <div style={{ fontSize:10, color:'rgba(255,255,255,.7)', letterSpacing:'0.06em', textTransform:'uppercase' }}>{k}</div>
            <div style={{ fontFamily:window.RITA.fm, fontSize:16, fontWeight:500, marginTop:2 }}>{v}</div>
          </div>
        ))}
      </div>

      <div style={{ margin:'12px 22px 0', padding:'14px 18px', borderRadius:18,
        background:'rgba(255,255,255,0.14)', border:'1px solid rgba(255,255,255,.2)' }}>
        <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:8 }}>
          <span style={{ fontSize:11, color:'rgba(255,255,255,.75)' }}>{data.instrument} · today</span>
          <span style={{ fontFamily:window.RITA.fm, fontSize:13, fontWeight:500 }}>{data.price}</span>
        </div>
        <svg width="100%" height="40" viewBox="0 0 280 40">
          <polyline fill="none" stroke="#fff" strokeWidth="1.6" strokeLinecap="round"
            points={data.sparkline.map((v,i)=>`${i*(280/19)},${40-(v/34)*32-2}`).join(' ')} />
        </svg>
      </div>

      <div style={{ position:'absolute', bottom:146, left:0, right:0, textAlign:'center',
        fontSize:11, color:'rgba(255,255,255,.7)', letterSpacing:'0.08em' }}>swipe up for next signal ↑</div>
      <SfChat />
      <SfTabBar dark={dark} active="sig" />
    </div>
  );
}

// ── MARKET ANALYSIS (Novel) — factor breakdown + regime + Rita explains ──
function SignalFeedMarket({ dark, data }) {
  const t = dark ? window.RITA.dark : window.RITA.light;
  const bdKey = data.stateColor===window.RITA.build?'buildBd':data.stateColor===window.RITA.danger?'dangerBd':'warnBd';
  const bgKey = data.stateColor===window.RITA.build?'buildBg':data.stateColor===window.RITA.danger?'dangerBg':'warnBg';
  return (
    <div style={{ ...sfStyles(dark).page, position:'relative' }}>
      <div style={{ padding:'60px 22px 8px' }}>
        <div style={{ fontSize:12, color:t.t3, fontWeight:600, letterSpacing:'0.06em' }}>MARKET ANALYSIS</div>
        <div style={{ fontFamily:window.RITA.fs, fontSize:30, letterSpacing:'-0.01em', marginTop:4 }}>
          What Rita sees, <span style={{ fontStyle:'italic', color:t.t2 }}>explained</span>.
        </div>
      </div>

      <div style={{ padding:'8px 22px 14px' }}>
        <div style={{ padding:'14px 16px', borderRadius:18, background:window.RITA[bgKey], border:`1px solid ${window.RITA[bdKey]}` }}>
          <div style={{ fontSize:10, color:data.stateColor, fontWeight:700, letterSpacing:'0.08em', marginBottom:4 }}>CURRENT REGIME</div>
          <div style={{ fontSize:20, fontWeight:700, color:data.stateColor }}>{data.state} market</div>
          <div style={{ fontSize:12, color:t.t2, marginTop:6, lineHeight:1.5 }}>
            Momentum is dominant and volatility is
            {data.state==='Bull'?' compressed':data.state==='Bear'?' rising':' elevated'}.
          </div>
        </div>
      </div>

      <div style={{ padding:'4px 22px 14px' }}>
        <div style={{ fontSize:13, fontWeight:700, marginBottom:10 }}>Factor breakdown</div>
        {[['Momentum',0.72,window.RITA.build],['Value',0.41,window.RITA.run],['Quality',0.58,window.RITA.mon],['Volatility',0.33,window.RITA.warn]].map(([k,v,c])=>(
          <div key={k} style={{ marginBottom:10 }}>
            <div style={{ display:'flex', justifyContent:'space-between', fontSize:12, marginBottom:4 }}>
              <span style={{ color:t.t2 }}>{k}</span>
              <span style={{ fontFamily:window.RITA.fm, color:t.text, fontWeight:500 }}>{v.toFixed(2)}</span>
            </div>
            <div style={{ height:6, borderRadius:3, background:t.surface2, overflow:'hidden' }}>
              <div style={{ height:'100%', width:`${v*100}%`, background:c, borderRadius:3 }} />
            </div>
          </div>
        ))}
      </div>

      <div style={{ margin:'4px 16px 14px', padding:18, borderRadius:18, background:window.RITA.chatBg, border:`1px solid ${window.RITA.chatBd}` }}>
        <div style={{ display:'flex', alignItems:'center', gap:8, marginBottom:8 }}>
          <div style={{ width:28, height:28, borderRadius:14, background:window.RITA.chat, color:'#fff',
            display:'flex', alignItems:'center', justifyContent:'center', fontFamily:window.RITA.fs, fontSize:14 }}>R</div>
          <div style={{ fontSize:11, fontWeight:700, color:window.RITA.chat, letterSpacing:'0.04em' }}>RITA EXPLAINS</div>
        </div>
        <div style={{ fontSize:13, color:t.t2, lineHeight:1.55, fontStyle:'italic', fontFamily:window.RITA.fs }}>
          "Momentum is doing most of the work today. Volatility is compressed and breadth is positive — that combination is what Rita classifies as a {data.state.toLowerCase()} regime."
        </div>
      </div>

      <SfChatDark dark={dark} />
      <SfTabBar dark={dark} active="market" />
    </div>
  );
}

Object.assign(window, { SignalFeedOverview, SignalFeedHero, SignalFeedMarket, SfTabBar, SfChat, SfChatDark });
