import { api } from './api.js';
import { DS_C } from './utils.js';

// ── Module-scoped state ──────────────────────────────────────────────────────
let _vizSelectedInstrument = null;
const VIZ_CHARTS = {};
const CHARTS = {};  // local chart registry for understand section

// ── Color palette alias ──────────────────────────────────────────────────────
const C = DS_C;

// ── destroyChart (local) ─────────────────────────────────────────────────────
function destroyChart(id) { if(CHARTS[id]){CHARTS[id].destroy();delete CHARTS[id];} }

// ── UNDERSTAND DATA ──────────────────────────────────────────────────────────
export function loadUnderstand() {
  Promise.all([
    api('/api/v1/instruments'),
    api('/api/v1/instrument/active').catch(() => null)
  ]).then(([instruments, active]) => {
    const list = document.getElementById('viz-instrument-list');
    if (!list) return;
    if (!instruments || !instruments.length) {
      list.innerHTML = '<span style="font-size:12px;color:var(--t4)">No instruments found.</span>';
      return;
    }
    if (!_vizSelectedInstrument && active?.id) {
      _vizSelectedInstrument = active.id;
    }
    const portfolioSel = _vizSelectedInstrument === '__portfolio__';
    list.innerHTML = instruments.map(inst => {
      const ready = inst.data_ready !== false;
      const sel = _vizSelectedInstrument === inst.id;
      return `<button class="viz-pill${sel?' selected':''}${!ready?' disabled':''}"
        title="${ready?'':'Data not prepared yet'}"
        onclick="vizSelectInstrument('${inst.id}',this)"
        ${!ready?'disabled':''}>${inst.name||inst.id}</button>`;
    }).join('') +
      `<span style="display:inline-block;width:1px;height:22px;background:var(--border2);margin:0 6px;vertical-align:middle;"></span>` +
      `<button class="viz-pill${portfolioSel?' selected':''}" title="Cross-instrument portfolio view" onclick="vizSelectInstrument('__portfolio__',this)">📊 Portfolio</button>`;
    if (!_vizSelectedInstrument) {
      const first = instruments.find(i => i.data_ready !== false);
      if (first) {
        _vizSelectedInstrument = first.id;
        list.querySelector('.viz-pill')?.classList.add('selected');
      }
    }
  }).catch(() => {
    const list = document.getElementById('viz-instrument-list');
    if (list) list.innerHTML = '<span style="font-size:12px;color:var(--danger)">Could not load instruments.</span>';
  });
}

export function vizSelectInstrument(id, el) {
  _vizSelectedInstrument = id;
  document.querySelectorAll('#viz-instrument-list .viz-pill').forEach(p => p.classList.remove('selected'));
  el?.classList.add('selected');
}

export async function runUnderstand() {
  if (!_vizSelectedInstrument) {
    document.getElementById('viz-status').textContent = 'Select an instrument first.';
    return;
  }
  if (_vizSelectedInstrument === '__portfolio__') {
    return runPortfolioOverview();
  }
  const statusEl = document.getElementById('viz-status');
  statusEl.innerHTML = '<span class="spinner"></span>Loading…';
  document.getElementById('viz-empty').style.display = 'none';
  document.getElementById('viz-results').style.display = 'none';
  document.getElementById('viz-portfolio-results').style.display = 'none';

  try {
    const d = await api(`/api/v1/data-understanding?instrument_id=${_vizSelectedInstrument}`);
    statusEl.textContent = '';
    renderVizKPIs(d.summary);
    renderDistributions(d.distributions);
    renderCorrelation(d.correlation);
    renderTimeSeries(d.timeseries);
    renderClustering(d.clustering);
    document.getElementById('viz-results').style.display = '';
  } catch(e) {
    statusEl.textContent = 'Error: ' + e.message;
    document.getElementById('viz-empty').style.display = '';
  }
}

// ── KPIs ─────────────────────────────────────────────────────────────────────
function renderVizKPIs(s) {
  if (!s) return;
  document.getElementById('vk-rows').textContent     = s.rows?.toLocaleString() ?? '—';
  document.getElementById('vk-features').textContent = s.features ?? '—';
  document.getElementById('vk-from').textContent     = s.date_from || '—';
  document.getElementById('vk-to').textContent       = s.date_to   || '—';
  const mp = s.missing_pct ?? null;
  const mpEl = document.getElementById('vk-missing');
  mpEl.textContent = mp !== null ? mp.toFixed(2)+'%' : '—';
  mpEl.className = 'kpi-value ' + (mp > 5 ? 'neg' : mp > 1 ? 'warn' : 'pos');
  document.getElementById('vk-trends').textContent   = s.trend_classes || '—';
}

// ── Distributions ─────────────────────────────────────────────────────────────
const DIST_META = {
  close:         { desc:'Distribution of daily closing prices. Identifies price concentration zones and outliers.' },
  daily_return:  { desc:'Daily % returns. Bell-shaped distribution centred near zero is expected for equities.' },
  rsi_14:        { desc:'RSI(14) distribution. Values cluster below 30 or above 70 indicate trending regimes.' },
  volume:        { desc:'Trade volume distribution. Right-skewed — a few sessions dominate activity.' },
  macd:          { desc:'MACD line distribution. Values near zero show periods of low momentum.' },
  macd_12_26:    { desc:'MACD line distribution. Values near zero show periods of low momentum.' },
  log_return:    { desc:'Log returns are more symmetric than simple returns and used in risk models.' },
  macd_hist:     { desc:'MACD histogram — difference between MACD and signal line. Positive = bullish momentum.' },
  macd_histogram_12_26: { desc:'MACD histogram — difference between MACD and signal line.' },
  bb_pct_b:      { desc:'Bollinger Band %B. Values near 1 = price at upper band; near 0 = lower band.' },
  volatility_20: { desc:'20-day rolling volatility. Clusters at higher values mark stressed market regimes.' },
};

function renderDistributions(dists) {
  const grid = document.getElementById('viz-dist-grid');
  if (!grid || !dists) return;
  grid.innerHTML = '';
  Object.entries(dists).forEach(([col, d]) => {
    const meta = DIST_META[col] || {};
    const cardId = 'vdist-' + col;
    const card = document.createElement('div');
    card.className = 'viz-card';
    card.innerHTML = `
      <span class="badge ds">Distribution</span>
      <div class="viz-card-title">${d.label}</div>
      <div class="viz-canvas-wrap" onclick="openVizModal('${cardId}','${d.label}','${(meta.desc||'').replace(/'/g,"\\'")}')">
        <canvas id="${cardId}"></canvas>
      </div>
      <div class="viz-desc">${meta.desc||''}</div>`;
    grid.appendChild(card);
    _makeBarChart(cardId, d.labels, d.values, d.label);
  });
}

function _makeBarChart(id, labels, values, label) {
  destroyChart(id);
  const canvas = document.getElementById(id);
  if (!canvas) return;
  VIZ_CHARTS[id] = { type:'bar', labels, values, label };
  CHARTS[id] = new Chart(canvas, {
    type: 'bar',
    data: { labels, datasets:[{ data:values, backgroundColor: C.dsBg, borderColor: C.ds, borderWidth:1, borderRadius:2 }] },
    options:{
      responsive:true, maintainAspectRatio:false,
      plugins:{ legend:{display:false} },
      scales:{
        x:{ display:false },
        y:{ grid:{color:C.grid}, ticks:{font:{family:"'IBM Plex Mono'",size:8},color:C.t3,maxTicksLimit:4} }
      }
    }
  });
}

// ── Correlation heatmap ───────────────────────────────────────────────────────
function renderCorrelation(corr) {
  const wrap = document.getElementById('viz-corr-table');
  const badge = document.getElementById('viz-corr-badge');
  if (!wrap || !corr || !corr.features?.length) return;
  const feats = corr.features;
  badge.textContent = feats.length + ' features';

  const hdr = '<th></th>' + feats.map(f => `<th title="${f}">${f.replace(/_/g,' ')}</th>`).join('');
  const rows = corr.matrix.map((row, i) => {
    const cells = row.map((v, j) => {
      const abs = Math.abs(v);
      const alpha = i === j ? 0.15 : abs * 0.7;
      const color = i === j ? 'var(--t4)' : v > 0 ? `rgba(26,107,60,${alpha})` : `rgba(155,28,28,${alpha})`;
      const txt = i === j ? '—' : v.toFixed(2);
      return `<td style="background:${color}">${txt}</td>`;
    }).join('');
    return `<tr><th>${feats[i].replace(/_/g,' ')}</th>${cells}</tr>`;
  }).join('');

  wrap.innerHTML = `<table class="corr-table"><thead><tr>${hdr}</tr></thead><tbody>${rows}</tbody></table>`;
}

// ── Time Series ───────────────────────────────────────────────────────────────
const TS_META = [
  { key:'close',  label:'Close Price',   desc:'OHLCV closing price over the full history of the instrument.' },
  { key:'volume', label:'Volume',        desc:'Daily traded volume. Spikes often coincide with significant price moves.' },
  { key:'rsi',    label:'RSI (14)',      desc:'Relative Strength Index. Dashed lines at 30 and 70 mark extremes.' },
  { key:'macd',   label:'MACD (12/26)',  desc:'MACD line. Crosses above zero indicate bullish momentum shifts.' },
];

function renderTimeSeries(ts) {
  const grid = document.getElementById('viz-ts-grid');
  if (!grid || !ts?.dates?.length) return;
  grid.innerHTML = '';
  TS_META.forEach(m => {
    if (!ts[m.key]?.length) return;
    const cardId = 'vts-' + m.key;
    const card = document.createElement('div');
    card.className = 'viz-card';
    card.innerHTML = `
      <span class="badge run">Time Series</span>
      <div class="viz-card-title">${m.label}</div>
      <div class="viz-canvas-wrap" onclick="openVizModal('${cardId}','${m.label}','${m.desc.replace(/'/g,"\\'")}')">
        <canvas id="${cardId}"></canvas>
      </div>
      <div class="viz-desc">${m.desc}</div>`;
    grid.appendChild(card);
    _makeLineChart(cardId, ts.dates, ts[m.key], m.label, m.key === 'rsi');
  });
}

function _makeLineChart(id, dates, values, label, isRsi) {
  destroyChart(id);
  const canvas = document.getElementById(id);
  if (!canvas) return;
  VIZ_CHARTS[id] = { type:'line', dates, values, label, isRsi };
  const annotations = isRsi ? {
    line30:{ type:'line', yMin:30, yMax:30, borderColor:'rgba(155,28,28,.4)', borderWidth:1, borderDash:[3,3] },
    line70:{ type:'line', yMin:70, yMax:70, borderColor:'rgba(26,107,60,.4)', borderWidth:1, borderDash:[3,3] }
  } : {};
  CHARTS[id] = new Chart(canvas, {
    type:'line',
    data:{ labels:dates, datasets:[{ data:values, borderColor:C.run, borderWidth:1.5, pointRadius:0, fill:false, tension:0.2 }] },
    options:{
      responsive:true, maintainAspectRatio:false,
      plugins:{ legend:{display:false}, annotation:{annotations} },
      scales:{
        x:{ display:false },
        y:{ grid:{color:C.grid}, ticks:{font:{family:"'IBM Plex Mono'",size:8},color:C.t3,maxTicksLimit:4} }
      }
    }
  });
}

// ── Clustering ────────────────────────────────────────────────────────────────
const CLUSTER_COLORS = ['rgba(14,116,144,.7)','rgba(26,107,60,.7)','rgba(155,28,28,.7)'];

function renderClustering(cl) {
  const grid = document.getElementById('viz-cluster-grid');
  if (!grid || !cl) return;
  grid.innerHTML = '';

  if (cl.elbow?.k?.length) {
    const cid = 'vcl-elbow';
    const card = document.createElement('div');
    card.className = 'viz-card';
    card.innerHTML = `
      <span class="badge mon">Clustering</span>
      <div class="viz-card-title">Elbow Method</div>
      <div class="viz-canvas-wrap" onclick="openVizModal('${cid}','Elbow Method','Inertia vs number of clusters. The elbow point suggests the optimal k.')">
        <canvas id="${cid}"></canvas>
      </div>
      <div class="viz-desc">Inertia vs k. The elbow suggests the optimal number of market regime clusters.</div>`;
    grid.appendChild(card);
    destroyChart(cid);
    const canvas = document.getElementById(cid);
    VIZ_CHARTS[cid] = { type:'elbow', ...cl.elbow };
    CHARTS[cid] = new Chart(canvas, {
      type:'line',
      data:{ labels:cl.elbow.k, datasets:[{ data:cl.elbow.inertia, borderColor:C.mon, borderWidth:2, pointRadius:4, pointBackgroundColor:C.mon, fill:false }] },
      options:{
        responsive:true, maintainAspectRatio:false,
        plugins:{ legend:{display:false} },
        scales:{
          x:{ title:{display:true,text:'k',font:{family:"'IBM Plex Mono'",size:9},color:C.t3}, grid:{color:C.grid}, ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3} },
          y:{ title:{display:true,text:'Inertia',font:{family:"'IBM Plex Mono'",size:9},color:C.t3}, grid:{color:C.grid}, ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3} }
        }
      }
    });
  }

  if (cl.pca?.x?.length) {
    const cid = 'vcl-pca';
    const card = document.createElement('div');
    card.className = 'viz-card';
    card.innerHTML = `
      <span class="badge mon">Clustering</span>
      <div class="viz-card-title">PCA Cluster Scatter</div>
      <div class="viz-canvas-wrap" onclick="openVizModal('${cid}','PCA Cluster Scatter','2D PCA projection of all features coloured by K-Means cluster (k=3).')">
        <canvas id="${cid}"></canvas>
      </div>
      <div class="viz-desc">2D PCA projection coloured by K-Means cluster (k=3). Distinct regions indicate separable market regimes.</div>`;
    grid.appendChild(card);
    destroyChart(cid);
    const canvas = document.getElementById(cid);
    VIZ_CHARTS[cid] = { type:'pca', ...cl.pca };
    const byCluster = {};
    cl.pca.cluster.forEach((c, i) => {
      if (!byCluster[c]) byCluster[c] = [];
      byCluster[c].push({ x: cl.pca.x[i], y: cl.pca.y[i] });
    });
    const datasets = Object.entries(byCluster).map(([c, pts]) => ({
      label: 'Cluster ' + c,
      data: pts,
      backgroundColor: CLUSTER_COLORS[+c] || 'rgba(100,100,100,.6)',
      pointRadius: 3,
    }));
    CHARTS[cid] = new Chart(canvas, {
      type:'scatter',
      data:{ datasets },
      options:{
        responsive:true, maintainAspectRatio:false,
        plugins:{ legend:{labels:{font:{family:"'IBM Plex Mono'",size:9},color:C.t2}} },
        scales:{
          x:{ title:{display:true,text:'PCA 1',font:{family:"'IBM Plex Mono'",size:9},color:C.t3}, grid:{color:C.grid}, ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3} },
          y:{ title:{display:true,text:'PCA 2',font:{family:"'IBM Plex Mono'",size:9},color:C.t3}, grid:{color:C.grid}, ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3} }
        }
      }
    });
  }
}

// ── Viz Modal ─────────────────────────────────────────────────────────────────
let _vmChart = null;

export function openVizModal(chartId, title, desc) {
  document.getElementById('vm-title').textContent = title;
  document.getElementById('vm-desc').textContent = desc;
  document.getElementById('viz-modal').classList.add('open');

  if (_vmChart) { _vmChart.destroy(); _vmChart = null; }
  const src = VIZ_CHARTS[chartId];
  if (!src) return;
  const canvas = document.getElementById('vm-canvas');

  if (src.type === 'bar') {
    _vmChart = new Chart(canvas, {
      type:'bar',
      data:{ labels:src.labels, datasets:[{ data:src.values, backgroundColor:C.dsBg, borderColor:C.ds, borderWidth:1, borderRadius:2 }] },
      options:{
        responsive:true, maintainAspectRatio:false,
        plugins:{ legend:{display:false} },
        scales:{
          x:{ grid:{color:C.grid}, ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3,maxTicksLimit:10} },
          y:{ grid:{color:C.grid}, ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3} }
        }
      }
    });
  } else if (src.type === 'line') {
    const annotations = src.isRsi ? {
      line30:{ type:'line', yMin:30, yMax:30, borderColor:'rgba(155,28,28,.4)', borderWidth:1, borderDash:[3,3] },
      line70:{ type:'line', yMin:70, yMax:70, borderColor:'rgba(26,107,60,.4)', borderWidth:1, borderDash:[3,3] }
    } : {};
    _vmChart = new Chart(canvas, {
      type:'line',
      data:{ labels:src.dates, datasets:[{ data:src.values, borderColor:C.run, borderWidth:1.5, pointRadius:0, fill:false, tension:0.2 }] },
      options:{
        responsive:true, maintainAspectRatio:false,
        plugins:{ legend:{display:false}, annotation:{annotations} },
        scales:{
          x:{ grid:{color:C.grid}, ticks:{font:{family:"'IBM Plex Mono'",size:8},color:C.t3,maxTicksLimit:12} },
          y:{ grid:{color:C.grid}, ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3} }
        }
      }
    });
  } else if (src.type === 'elbow') {
    _vmChart = new Chart(canvas, {
      type:'line',
      data:{ labels:src.k, datasets:[{ data:src.inertia, borderColor:C.mon, borderWidth:2, pointRadius:5, pointBackgroundColor:C.mon, fill:false }] },
      options:{
        responsive:true, maintainAspectRatio:false,
        plugins:{ legend:{display:false} },
        scales:{
          x:{ title:{display:true,text:'k'}, grid:{color:C.grid}, ticks:{font:{family:"'IBM Plex Mono'",size:10}} },
          y:{ title:{display:true,text:'Inertia'}, grid:{color:C.grid}, ticks:{font:{family:"'IBM Plex Mono'",size:10}} }
        }
      }
    });
  } else if (src.type === 'pca') {
    const byCluster = {};
    src.cluster.forEach((c, i) => {
      if (!byCluster[c]) byCluster[c] = [];
      byCluster[c].push({ x:src.x[i], y:src.y[i] });
    });
    const datasets = Object.entries(byCluster).map(([c, pts]) => ({
      label:'Cluster '+c, data:pts,
      backgroundColor: CLUSTER_COLORS[+c]||'rgba(100,100,100,.6)', pointRadius:4,
    }));
    _vmChart = new Chart(canvas, {
      type:'scatter',
      data:{ datasets },
      options:{
        responsive:true, maintainAspectRatio:false,
        plugins:{ legend:{labels:{font:{family:"'IBM Plex Mono'",size:10},color:C.t2}} },
        scales:{
          x:{ title:{display:true,text:'PCA 1'}, grid:{color:C.grid}, ticks:{font:{family:"'IBM Plex Mono'",size:10}} },
          y:{ title:{display:true,text:'PCA 2'}, grid:{color:C.grid}, ticks:{font:{family:"'IBM Plex Mono'",size:10}} }
        }
      }
    });
  }
}

export function closeVizModal() {
  document.getElementById('viz-modal').classList.remove('open');
  if (_vmChart) { _vmChart.destroy(); _vmChart = null; }
}

// ── Portfolio Overview ────────────────────────────────────────────────────────
export async function runPortfolioOverview() {
  const statusEl = document.getElementById('viz-status');
  statusEl.innerHTML = '<span class="spinner"></span>Loading portfolio data…';
  document.getElementById('viz-empty').style.display = 'none';
  document.getElementById('viz-results').style.display = 'none';
  document.getElementById('viz-portfolio-results').style.display = 'none';

  try {
    const d = await api('/api/v1/portfolio/overview');
    statusEl.textContent = '';
    renderPortfolioOverview(d);
    document.getElementById('viz-portfolio-results').style.display = '';
  } catch(e) {
    statusEl.innerHTML = '';
    document.getElementById('vp-days').textContent = '—';
    document.getElementById('vp-from').textContent = '—';
    document.getElementById('vp-to').textContent = '—';
    document.getElementById('vp-corr-table').innerHTML =
      `<div class="empty">Portfolio overview not available: ${e.message}<br><span style="color:var(--t3)">Build individual models first, then reload.</span></div>`;
    document.getElementById('vp-inst-grid').innerHTML = '';
    document.getElementById('viz-portfolio-results').style.display = '';
  }
}

function renderPortfolioOverview(d) {
  if (!d) return;
  const INST_COLORS = { nifty:C.build, banknifty:C.run, asml:C.ds, nvidia:C.warn };
  const INST_LABELS = { nifty:'NIFTY 50', banknifty:'BANKNIFTY', asml:'ASML', nvidia:'NVIDIA' };

  document.getElementById('vp-days').textContent = d.common_days?.toLocaleString() ?? '—';
  document.getElementById('vp-from').textContent = d.date_from ?? '—';
  document.getElementById('vp-to').textContent   = d.date_to   ?? '—';
  document.getElementById('vp-count').textContent = d.instruments?.length ?? 4;

  const grid = document.getElementById('vp-inst-grid');
  if (grid && d.instruments) {
    grid.innerHTML = d.instruments.map(inst => {
      const color = INST_COLORS[inst.id] || C.t3;
      const label = INST_LABELS[inst.id] || inst.name || inst.id;
      return `<div class="viz-card" style="border-top-color:${color}">
        <span class="badge ds">${inst.currency || ''}</span>
        <div class="viz-card-title">${label}</div>
        <div class="viz-desc">
          Rows: ${inst.rows?.toLocaleString() ?? '—'}<br>
          ${inst.date_from || ''} → ${inst.date_to || ''}
        </div>
      </div>`;
    }).join('');
  }

  if (d.normalized_returns?.length) {
    const labels = d.normalized_returns.map(r => r.date);
    const series = Object.keys(INST_COLORS).filter(k => d.normalized_returns[0]?.[k] != null);
    const datasets = series.map(k => ({
      label: INST_LABELS[k] || k,
      data: d.normalized_returns.map(r => r[k] != null ? parseFloat(r[k]).toFixed(4) : null),
      borderColor: INST_COLORS[k],
      backgroundColor: 'transparent',
      borderWidth: 1.5, pointRadius: 0, fill: false,
    }));
    if (CHARTS['chart-vp-returns']) { CHARTS['chart-vp-returns'].destroy(); delete CHARTS['chart-vp-returns']; }
    const canvas = document.getElementById('chart-vp-returns');
    if (canvas && datasets.length) {
      const sc = {
        x:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3,maxTicksLimit:12}},
        y:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3}}
      };
      CHARTS['chart-vp-returns'] = new Chart(canvas, {
        type:'line', data:{labels, datasets},
        options:{responsive:true,maintainAspectRatio:false,
          plugins:{legend:{labels:{font:{family:"'IBM Plex Mono'",size:10},color:C.t2}}},
          scales:sc}
      });
    }
  }

  const corrWrap = document.getElementById('vp-corr-table');
  if (corrWrap && d.correlation_matrix) {
    const names = Object.keys(d.correlation_matrix);
    const ths = names.map(n=>`<th>${INST_LABELS[n]||n}</th>`).join('');
    const rows = names.map(r => {
      const cells = names.map(c => {
        const v = d.correlation_matrix[r]?.[c];
        if (v == null) return '<td>—</td>';
        const n = parseFloat(v);
        const bg = n >= 0.7 ? '#B6DEC9' : n <= -0.4 ? '#FCA5A5' : n >= 0.4 ? '#FEF4EB' : '';
        return `<td style="${bg?`background:${bg};`:''}font-weight:${r===c?700:400}">${n.toFixed(2)}</td>`;
      }).join('');
      return `<tr><th>${INST_LABELS[r]||r}</th>${cells}</tr>`;
    }).join('');
    corrWrap.innerHTML = `<table class="corr-table"><thead><tr><th></th>${ths}</tr></thead><tbody>${rows}</tbody></table>`;
  }
}
