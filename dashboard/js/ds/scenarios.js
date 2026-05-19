import { api } from './api.js';
import { DS_C } from './utils.js';

const C = DS_C;

export function loadScenariosPage() { /* section is ready on show — nothing to auto-load */ }

function scToggleInst(id) {
  const cb   = document.getElementById(`sc-inst-${id}`);
  const card = document.getElementById(`sc-card-${id}`);
  const sl   = document.getElementById(`sc-slider-${id}`);
  if (!cb || !card || !sl) return;
  const on = cb.checked;
  card.style.opacity   = on ? '' : '0.45';
  sl.disabled          = !on;
  sl.style.cursor      = on ? 'pointer' : 'not-allowed';
  scUpdateTotal();
}

function scUpdateTotal() {
  const ids     = ['nifty','banknifty','asml','nvidia'];
  const capital = parseFloat(document.getElementById('sc-capital')?.value || 1000);
  let allocatedPct = 0;
  ids.forEach(id => {
    const cb  = document.getElementById(`sc-inst-${id}`);
    const sl  = document.getElementById(`sc-slider-${id}`);
    const pct = sl ? parseFloat(sl.value) : 0;
    const pctEl = document.getElementById(`sc-pct-${id}`);
    if (pctEl) pctEl.textContent = pct;
    const eurEl = document.getElementById(`sc-eur-${id}`);
    if (eurEl) eurEl.textContent = '€' + Math.round(capital * pct / 100).toLocaleString();
    if (cb?.checked) allocatedPct += pct;
  });
  const remaining = 100 - allocatedPct;
  const remEl = document.getElementById('sc-remaining-lbl');
  if (remEl) {
    if (remaining < 0) {
      remEl.innerHTML = `<span style="color:var(--warn);font-weight:600">· ${Math.abs(remaining)}% over-allocated</span>`;
    } else {
      remEl.textContent = `· ${remaining}% stays as cash`;
    }
  }
}

export async function runPortfolioScenario() {
  const from = document.getElementById('sc-from').value;
  const to   = document.getElementById('sc-to').value;
  if (!from || !to) { alert('Select both start and end dates.'); return; }
  if (from >= to)   { alert('Start date must be before end date.'); return; }

  const ids = ['nifty','banknifty','asml','nvidia'];
  const selected = ids.filter(id => document.getElementById(`sc-inst-${id}`)?.checked);
  if (!selected.length) { alert('Select at least one instrument.'); return; }

  const capital = parseFloat(document.getElementById('sc-capital')?.value || 1000);
  const allocations = {};
  selected.forEach(id => {
    const pct = parseFloat(document.getElementById(`sc-slider-${id}`)?.value || 0);
    allocations[id] = Math.round(capital * pct / 100);
  });

  const btn     = document.getElementById('btn-sc');
  const spinner = document.getElementById('sc-spinner');
  const badge   = document.getElementById('sc-status');
  btn.disabled = true;
  spinner.style.display = '';
  badge.style.display = ''; badge.className = 'badge run'; badge.textContent = 'Running…';
  document.getElementById('sc-result').innerHTML = '';

  try {
    const result = await api('/api/v1/portfolio/backtest', 'POST', { instruments: selected, allocations_eur: allocations, start_date: from, end_date: to });
    badge.className = 'badge ok'; badge.textContent = 'Done';
    renderPortfolioScenarioResults(result, from, to, selected);
  } catch(e) {
    badge.className = 'badge err'; badge.textContent = 'Error';
    document.getElementById('sc-result').innerHTML =
      `<div class="card"><div style="color:var(--danger);font-size:12px">Error: ${e.message}</div></div>`;
  } finally {
    btn.disabled = false;
    spinner.style.display = 'none';
  }
}

function renderPortfolioScenarioResults(d, from, to, selected) {
  const resultEl = document.getElementById('sc-result');
  if (!d || !Object.keys(d).length) { resultEl.innerHTML = '<div class="empty">No results returned.</div>'; return; }
  const _f = v => (v !== null && v !== undefined && !isNaN(parseFloat(v))) ? parseFloat(v) : null;
  const sharpe = _f(d.sharpe_ratio);
  const mdd    = _f(d.max_drawdown_pct);
  const ret    = _f(d.portfolio_total_return_pct);
  const bnh    = _f(d.benchmark_total_return_pct);
  const cagr   = _f(d.portfolio_cagr_pct);

  let html = `
  <div class="card-hdr" style="margin-bottom:10px">
    <span class="card-title">Portfolio Results — ${from} → ${to}</span>
    <span class="badge ds" style="margin-left:8px">${d.instruments_count ?? selected?.length ?? ''} instruments · €${(d.total_eur_allocated??1000).toLocaleString()}</span>
  </div>
  <div class="kpi-row kpi-row-4" style="margin-bottom:14px">
    <div class="kpi"><div class="kpi-label">Portfolio Sharpe</div><div class="kpi-value ${sharpe!==null?(sharpe>=1?'pos':sharpe>=0?'neu':'neg'):''}">${sharpe!==null?sharpe.toFixed(3):'—'}</div><div class="kpi-delta">target ≥ 1.0</div></div>
    <div class="kpi"><div class="kpi-label">Max Drawdown</div><div class="kpi-value ${mdd!==null?(Math.abs(mdd)<=10?'pos':'warn'):''}">${mdd!==null?mdd.toFixed(2)+'%':'—'}</div><div class="kpi-delta">target &lt; 10%</div></div>
    <div class="kpi"><div class="kpi-label">Portfolio Return</div><div class="kpi-value neu">${ret!==null?ret.toFixed(2)+'%':'—'}</div><div class="kpi-delta">B&amp;H avg ${bnh!==null?bnh.toFixed(2)+'%':'—'}</div></div>
    <div class="kpi"><div class="kpi-label">CAGR</div><div class="kpi-value neu">${cagr!==null?cagr.toFixed(2)+'%':'—'}</div><div class="kpi-delta">annualised</div></div>
  </div>`;

  if (d.instruments?.length) {
    const INST_LABELS = {nifty:'NIFTY 50',banknifty:'BANKNIFTY',asml:'ASML',nvidia:'NVIDIA'};
    const trs = d.instruments.map(inst => {
      const r = _f(inst.return_pct); const s = _f(inst.sharpe); const w = _f(inst.weight_pct);
      return `<tr>
        <td class="td-mono">${INST_LABELS[inst.id]||inst.name||inst.id}</td>
        <td class="td-mono">${inst.currency||'—'}</td>
        <td class="td-mono" style="text-align:right">€${(inst.allocated_eur||0).toLocaleString()}</td>
        <td class="td-mono" style="text-align:right;color:${r!==null?(r>=0?'var(--build)':'var(--danger)'):'inherit'}">${r!==null?r.toFixed(2)+'%':'—'}</td>
        <td class="td-mono" style="text-align:right">${s!==null?s.toFixed(3):'—'}</td>
        <td class="td-mono" style="text-align:right">${w!==null?w.toFixed(1)+'%':'—'}</td>
      </tr>`;
    }).join('');
    html += `<div class="tbl-wrap" style="margin-bottom:14px"><table>
      <thead><tr><th>Instrument</th><th>Ccy</th><th style="text-align:right">Allocated</th><th style="text-align:right">Return</th><th style="text-align:right">Sharpe</th><th style="text-align:right">Weight</th></tr></thead>
      <tbody>${trs}</tbody></table></div>`;
  }

  if (d.daily?.length) {
    const labels   = d.daily.map(r => r.date);
    const portVals = d.daily.map(r => r.portfolio_value != null ? ((parseFloat(r.portfolio_value)-1)*100).toFixed(2) : null);
    const bnhVals  = d.daily.map(r => r.benchmark_value  != null ? ((parseFloat(r.benchmark_value) -1)*100).toFixed(2) : null);
    html += `<div class="chart-wrap"><div class="chart-title">Cumulative Return (%) — DDQN Portfolio vs Equal-Weight B&amp;H</div>
      <div class="chart-box h260"><canvas id="chart-sc-portfolio"></canvas></div></div>`;
    resultEl.innerHTML = html;
    const canvas = document.getElementById('chart-sc-portfolio');
    if (canvas) {
      const INST_COLORS = {nifty:C.build,banknifty:C.run,asml:C.ds,nvidia:C.warn};
      const INST_LABELS = {nifty:'NIFTY 50',banknifty:'BANKNIFTY',asml:'ASML',nvidia:'NVIDIA'};
      const sc = {
        x:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3,maxTicksLimit:12}},
        y:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3,callback:v=>v+'%'}}
      };
      const datasets = [
        {label:'RITA Portfolio',data:portVals,borderColor:C.ds,backgroundColor:C.dsBg,fill:true,pointRadius:0,borderWidth:2},
        {label:'Equal-Weight B&H',data:bnhVals,borderColor:C.warn,backgroundColor:'transparent',fill:false,pointRadius:0,borderWidth:1.5,borderDash:[4,3]},
      ];
      if (d.instrument_series) {
        Object.entries(d.instrument_series).forEach(([k, vals]) => {
          datasets.push({label:INST_LABELS[k]||k,
            data:vals.map(v=>v!=null?((parseFloat(v)-1)*100).toFixed(2):null),
            borderColor:INST_COLORS[k]||C.t3,backgroundColor:'transparent',
            fill:false,pointRadius:0,borderWidth:1,borderDash:[2,2]});
        });
      }
      new Chart(canvas, {
        type:'line',data:{labels,datasets},
        options:{responsive:true,maintainAspectRatio:false,
          plugins:{legend:{labels:{font:{family:"'IBM Plex Mono'",size:10},color:C.t2}}},
          scales:sc}
      });
    }
    return;
  }
  resultEl.innerHTML = html;
}
