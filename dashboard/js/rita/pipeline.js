// ── Pipeline result renderers ──────────────────────────────
import { badge, setEl } from './utils.js';
import { mkChart, C } from './charts.js';

export function renderGoalResult(containerId, d) {
  const r = d.result || d;
  const fv = (v, dec=1, sfx='') => (v != null && !isNaN(parseFloat(v))) ? parseFloat(v).toFixed(dec) + sfx : '—';
  const feasCls = {conservative:'ok', realistic:'ok', ambitious:'warn', unrealistic:'err'};
  const cls = feasCls[r.feasibility] || 'neu';

  const avgReturn = r.yearly_returns && r.yearly_returns.length
    ? r.yearly_returns.reduce((a, b) => a + b.return_pct, 0) / r.yearly_returns.length
    : null;
  const metrics = [
    {label:'Target Return',      value: fv(r.target_return_pct, 1, '%')},
    {label:'Time Horizon',       value: `${r.time_horizon_days ?? '—'}d`},
    {label:'Risk Tolerance',     value: r.risk_tolerance ? r.risk_tolerance.charAt(0).toUpperCase()+r.risk_tolerance.slice(1) : '—'},
    {label:'Annualised Target',  value: fv(r.annualised_target, 2, '%')},
    {label:'Req. Monthly Ret.',  value: fv(r.required_monthly, 3, '%')},
    {label:'Feasibility',        value: r.feasibility || '—', badge: cls},
    {label:'Suggested Target',   value: fv(avgReturn, 1, '%')},
    {label:'Last 12m Return',    value: fv(r.last_12m_return, 1, '%')},
  ];

  const mkMetric = m => `<div style="background:var(--surface);border:1.5px solid var(--border);border-radius:var(--r);padding:8px 12px">
    <div style="font-size:10px;text-transform:uppercase;letter-spacing:.05em;color:var(--t3);margin-bottom:3px;white-space:nowrap">${m.label}</div>
    ${m.badge ? `<span class="badge ${m.badge}" style="font-size:11px;padding:2px 7px">${m.value}</span>` :
      `<div style="font-family:var(--fm);font-size:15px;font-weight:500;color:var(--text)">${m.value}</div>`}
  </div>`;

  let html = `<div class="result-panel">
    <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:8px">
      <div class="result-title" style="margin-bottom:0">Step ${d.step || 1} — ${d.name || 'Financial Goal'} <span class="badge ok">Done</span></div>
      ${r.feasibility_note ? `<span style="font-size:11px;color:var(--t3)">${r.feasibility_note}</span>` : ''}
    </div>
    <div style="display:grid;grid-template-columns:repeat(8,1fr);gap:6px;margin-bottom:10px">${metrics.map(mkMetric).join('')}</div>`;

  // Annual returns chart
  if (r.yearly_returns && r.yearly_returns.length) {
    const instLabel = r.instrument || 'Instrument';
    html += `<div class="chart-wrap" style="margin:0"><div class="chart-title">${instLabel} Annual Returns — Last ${r.yearly_returns.length} Years
      <span style="font-weight:400;color:var(--t3);font-size:11px"> · <span style="color:var(--run)">─</span> Target <span style="color:var(--build)">─</span> Avg</span>
    </div><div class="chart-box" style="height:200px"><canvas id="chart-goal-returns"></canvas></div></div>`;
  }
  html += '</div>';
  setEl(containerId, html);

  if (r.yearly_returns && r.yearly_returns.length) {
    const labels = r.yearly_returns.map(y => y.year);
    const vals   = r.yearly_returns.map(y => y.return_pct);
    mkChart('chart-goal-returns', {
      type: 'bar',
      data: {
        labels,
        datasets: [{ label: 'Annual Return %', data: vals,
          backgroundColor: vals.map(v => v >= 0 ? 'rgba(26,107,60,0.55)' : 'rgba(155,28,28,0.55)'),
          borderColor:     vals.map(v => v >= 0 ? 'rgba(26,107,60,0.9)'  : 'rgba(155,28,28,0.9)'),
          borderWidth: 1.5 }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          annotation: { annotations: {
            target:    { type:'line', yMin: r.target_return_pct, yMax: r.target_return_pct, borderColor: C.run,   borderWidth:1.5, borderDash:[5,3], label:{content:'Target', display:true, position:'end', font:{size:10}} },
            suggested: { type:'line', yMin: avgReturn,           yMax: avgReturn,           borderColor: C.build, borderWidth:1.5, borderDash:[5,3], label:{content:'Avg',    display:true, position:'end', font:{size:10}} },
          }}
        },
        scales: {
          x: { grid:{display:false}, ticks:{font:{family:C.mono,size:10}} },
          y: { grid:{color:'rgba(0,0,0,.04)'}, ticks:{callback:v=>v.toFixed(0)+'%', font:{family:C.mono,size:10}} }
        }
      }
    });
  }
}

export function renderMarketResult(d) {
  const r = (d.result && d.result.latest) ? d.result.latest : (d.result || d);
  const fv = (v, dec=2) => (v != null && !isNaN(parseFloat(v))) ? parseFloat(v).toFixed(dec) : '—';

  const trendCls = {uptrend:'pos', sideways:'neu', downtrend:'neg'};
  const rsiCls   = {overbought:'neg', oversold:'pos', neutral:'neu'};
  const macdCls  = {bullish:'pos', bearish:'neg'};
  const bbCls    = {near_upper_band:'neg', near_lower_band:'pos', middle:'neu'};
  const sentCls  = {complacent:'pos', neutral:'neu', fearful:'neg'};

  const _set = (id, text, cls) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = text;
    if (cls) el.className = 'kpi-value ' + cls;
  };

  // Row 2
  _set('ma-date',        r.date || '—');
  _set('ma-close',       r.close != null ? r.close.toLocaleString('en-IN') : '—');
  _set('ma-trend',       (r.trend || '—').replace(/_/g,' '),  trendCls[r.trend] || 'neu');
  setEl('ma-trend-score', `score ${fv(r.trend_score, 2)}`);
  _set('ma-sentiment',   (r.sentiment_proxy || '—').replace(/_/g,' '), sentCls[r.sentiment_proxy] || 'neu');
  _set('ma-rsi',         fv(r.rsi_14, 1), rsiCls[r.rsi_signal] || 'neu');
  setEl('ma-rsi-sig',    r.rsi_signal || '—');

  // Row 3
  _set('ma-macd',        fv(r.macd, 3), macdCls[r.macd_signal] || 'neu');
  setEl('ma-macd-sig',   r.macd_signal || '—');
  _set('ma-bb',          fv(r.bb_pct_b, 3), bbCls[r.bb_position] || 'neu');
  setEl('ma-bb-sig',     (r.bb_position || '—').replace(/_/g,' '));
  _set('ma-atr',         fv(r.atr_14, 2));
  setEl('ma-atr-sig',    `pctl ${fv(r.atr_percentile, 2)}`);
  _set('ma-ema',         `${fv(r.ema_5,0)} / ${fv(r.ema_13,0)}`);
  _set('ma-ema2',        fv(r.ema_26, 0));
}

export function renderStepResult(containerId, d) {
  const result = d.result || d;
  const rows = Object.entries(result).filter(([, v]) => typeof v !== 'object' || v === null);
  const nested = Object.entries(result).filter(([, v]) => typeof v === 'object' && v !== null);
  setEl(containerId, `
    <div class="result-panel">
      <div class="result-title">Step ${d.step || ''} — ${d.name || 'Result'} ${badge(d.status || 'ok')}</div>
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:6px">
        ${rows.map(([k, v]) => `
          <div style="display:flex;justify-content:space-between;gap:8px;padding:4px 0;border-bottom:1px solid var(--border);font-size:12px">
            <span style="color:var(--t3)">${k.replace(/_/g, ' ')}</span>
            <span style="font-family:var(--fm);color:var(--text)">${v != null ? String(v).slice(0, 60) : '—'}</span>
          </div>`).join('')}
      </div>
      ${nested.length ? `<details style="margin-top:10px"><summary style="font-size:11px;color:var(--t3);cursor:pointer">Nested data (${nested.length} keys)</summary><pre style="font-size:10px;color:var(--t3);margin-top:8px;white-space:pre-wrap">${JSON.stringify(Object.fromEntries(nested), null, 2)}</pre></details>` : ''}
    </div>`);
}
