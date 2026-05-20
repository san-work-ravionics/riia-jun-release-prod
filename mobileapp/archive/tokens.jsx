// Shared RITA design tokens. Data-only copy — no nudges, no "eligible",
// no "reduce exposure" — just observations.

const RITA = {
  light: { bg:'#F5F3EE', surface:'#FFFFFF', surface2:'#F9F8F5', border:'#E4E0D8', border2:'#D0CBBC',
           text:'#1A1814', t2:'#4A4640', t3:'#8C877A', t4:'#B8B2A6' },
  dark:  { bg:'#16140F', surface:'#1F1C16', surface2:'#26221B', border:'#2F2B22', border2:'#3D3828',
           text:'#F5F3EE', t2:'#C9C4B7', t3:'#8C877A', t4:'#5C584E' },
  build:'#1A6B3C', buildBg:'#EDF7F2', buildBd:'#B6DEC9',
  run:  '#0056B8', runBg:  '#EDF4FF', runBd:  '#AECBF5',
  mon:  '#6B2FA0', monBg:  '#F5EFFE', monBd:  '#CFADF0',
  warn: '#92480A', warnBg: '#FEF4EB', warnBd: '#F5C99A',
  danger:'#9B1C1C',dangerBg:'#FEF2F2',dangerBd:'#FCA5A5',
  chat: '#BE185D', chatBg: '#FFF0F5', chatBd: '#FBCFE8',
  fd: "'Epilogue', -apple-system, system-ui, sans-serif",
  fm: "'IBM Plex Mono', 'SF Mono', Menlo, monospace",
  fs: "'Instrument Serif', Georgia, serif",
};

// Data-only signals. Describe what happened/is happening — never recommend.
const RITA_DATA = {
  bull: {
    state:'Bull', stateColor:RITA.build, instrument:'NIFTY 50',
    price:'24,758.90', change:'+287.45', changePct:'+1.17%', changeDir:'up',
    goal:{ target:'12%', progress:74, current:'8.9%', runway:'14 months' },
    sparkline:[10,12,11,14,16,15,18,19,17,20,22,21,24,23,26,28,27,30,29,32],
    signals:[
      { tag:'MOMENTUM', sev:'build', title:'Momentum score at 75', body:'RSI above 70 on 3 of 4 tracked instruments for the last 2 sessions.', when:'12 min ago' },
      { tag:'ROTATION', sev:'run',   title:'IT leading broad market', body:'IT index outperformed by 2.1 standard deviations over the last 5 sessions.', when:'1 hr ago' },
      { tag:'VOLATILITY', sev:'neu', title:'VIX at 11.8', body:'Implied volatility is in the lowest quartile of its 1-year range.', when:'3 hr ago' },
      { tag:'BREADTH', sev:'build', title:'68% of stocks above 200-DMA', body:'Advance-decline ratio is 1,428 / 592 on the NSE today.', when:'4 hr ago' },
    ],
    strategy:{ name:'Swing-Momentum v3', status:'Active', winRate:'64%', sharpe:'1.82', pnl:'+₹82,400' },
  },
  bear: {
    state:'Bear', stateColor:RITA.danger, instrument:'NIFTY 50',
    price:'22,104.15', change:'-412.80', changePct:'-1.83%', changeDir:'down',
    goal:{ target:'12%', progress:31, current:'3.7%', runway:'22 months' },
    sparkline:[32,30,28,29,26,24,25,22,20,21,18,19,16,15,17,14,12,13,11,10],
    signals:[
      { tag:'DRAWDOWN', sev:'danger', title:'Portfolio down -4.2% this week', body:'Current drawdown is outside the 1-week historical band for this strategy.', when:'4 min ago' },
      { tag:'REVERSAL', sev:'warn',   title:'Three-session lower highs', body:'NIFTY has printed lower intraday highs for three consecutive sessions.', when:'27 min ago' },
      { tag:'FACTOR',   sev:'mon',    title:'Quality factor +3.8% vs market', body:'Low-volatility basket has outperformed the broad market over 2 weeks.', when:'2 hr ago' },
      { tag:'FLOW',     sev:'warn',   title:'FII net sellers 4 sessions', body:'Foreign institutional outflows totalling ₹8,200 cr over the last 4 sessions.', when:'5 hr ago' },
    ],
    strategy:{ name:'Mean-Revert v2', status:'Paused', winRate:'52%', sharpe:'0.74', pnl:'-₹31,200' },
  },
  volatile: {
    state:'Volatile', stateColor:RITA.warn, instrument:'NIFTY 50',
    price:'23,441.60', change:'+18.20', changePct:'+0.08%', changeDir:'flat',
    goal:{ target:'12%', progress:52, current:'6.2%', runway:'18 months' },
    sparkline:[18,22,16,24,14,26,12,28,20,14,24,18,26,16,22,20,24,18,22,19],
    signals:[
      { tag:'VOLATILITY', sev:'warn', title:'VIX up +38% intraday', body:'Regime classifier moved from "Quiet" to "Stressed" at 11:24.', when:'2 min ago' },
      { tag:'EVENT',     sev:'mon',  title:'Fed minutes at 19:30 IST', body:'Historical whipsaw on Fed-minutes days averages 1.4% range.', when:'38 min ago' },
      { tag:'RANGE',     sev:'run',  title:'NIFTY pinned at 23,400', body:'Gamma wall from monthly expiry concentrated at the 23,400 strike.', when:'1 hr ago' },
      { tag:'INTERNAL',  sev:'neu',  title:'Dispersion at 3-month high', body:'Single-stock variance is elevated relative to index variance.', when:'2 hr ago' },
    ],
    strategy:{ name:'Range-Fade v1', status:'Active', winRate:'58%', sharpe:'1.12', pnl:'+₹9,800' },
  },
};

Object.assign(window, { RITA, RITA_DATA });
