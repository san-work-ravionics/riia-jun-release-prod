// ── Risk page: Instrument + Portfolio performance charts ──────────────────────
import { state } from './state.js';
import { apiBase } from './api.js';

let _instChart   = null;
let _portChart   = null;
let _normData    = null;   // cached normalized_returns from portfolio/overview
let _startPrices = {};    // {instrument_lower: starting_absolute_price}

const _COLORS = {
  nifty:     '#2563eb',
  banknifty: '#7c3aed',
  asml:      '#d97706',
  nvidia:    '#059669',
  reliance:  '#dc2626',
  tcs:       '#0891b2',
  hdfcbank:  '#be185d',
  infy:      '#16a34a',
  sbin:      '#ea580c',
};

function _colorFor(id) {
  return _COLORS[id.toLowerCase()] || '#64748b';
}

// One-time fetch — called once after portfolio data loads
export async function fetchAndRenderRiskCharts() {
  try {
    const ids = (state.portfolioGeoInstruments || []).map(g => g.id).join(',');
    const qs  = ids ? `?instruments=${encodeURIComponent(ids)}` : '';
    const data = await fetch(apiBase() + '/api/v1/portfolio/overview' + qs).then(r => r.ok ? r.json() : null);
    if (!data?.normalized_returns?.length) return;
    _normData    = data.normalized_returns;
    _startPrices = data.start_prices || {};
    _buildCharts();
  } catch { /* non-critical */ }
}

// Called on risk-filter-change — updates line styles without a full redraw
export function highlightRiskChart() {
  if (!_instChart) return;
  const sel = state.riskSelectedInstrument;
  // If selected instrument has no dataset, treat as no selection (avoid fading all lines)
  const hasMatch = sel
    ? _instChart.data.datasets.some(ds => ds.label.toLowerCase() === sel.toLowerCase())
    : true;
  const effectiveSel = hasMatch ? sel : null;
  _instChart.data.datasets.forEach(ds => {
    const key    = ds.label.toLowerCase();
    const isSel  = effectiveSel ? key === effectiveSel.toLowerCase() : false;
    const hasSel = !!effectiveSel;
    const base   = _colorFor(key);
    ds.borderColor = hasSel && !isSel ? base + '50' : base;
    ds.borderWidth = isSel ? 3 : hasSel ? 1 : 2;
  });
  _instChart.update('none');
}

function _buildCharts() {
  if (!_normData?.length) return;

  const series = _normData;
  const dates  = series.map(d => d.date);

  // Only chart instruments that are in the user's saved portfolio
  const portfolioIds = new Set(
    (state.portfolioGeoInstruments || []).map(g => g.id.toLowerCase())
  );
  const allKeys = Object.keys(series[0]).filter(k => k !== 'date');
  const instruments = portfolioIds.size > 0
    ? allKeys.filter(k => portfolioIds.has(k))
    : allKeys;

  // Allocation weights from portfolio (normalised to 1.0 sum)
  const geoInsts = state.portfolioGeoInstruments || [];
  const rawW = {};
  let totalW = 0;
  for (const g of geoInsts) {
    const k = g.id.toLowerCase();
    if (instruments.includes(k)) {
      rawW[k] = parseFloat(g.allocation_pct) || 0;
      totalW += rawW[k];
    }
  }
  if (totalW === 0) {
    instruments.forEach(k => { rawW[k] = 1; totalW = instruments.length; });
  }

  // Weighted portfolio series (normalised ratio, 1.0 at start)
  const portRatios = series.map(d => {
    let v = 0;
    instruments.forEach(k => { v += (rawW[k] || 0) / totalW * (d[k] ?? 1); });
    return v;
  });

  // Convert portfolio ratios to absolute EUR using current total_value_eur as anchor
  const totalEur = state.portfolioMeta?.total_value_eur ?? null;
  const lastRatio = portRatios[portRatios.length - 1] || 1;
  const portValues = totalEur != null
    ? portRatios.map(r => parseFloat(((r / lastRatio) * totalEur).toFixed(0)))
    : portRatios.map(r => parseFloat((r * 100).toFixed(2)));

  const sel = state.riskSelectedInstrument;

  if (_instChart) { _instChart.destroy(); _instChart = null; }
  if (_portChart) { _portChart.destroy(); _portChart = null; }

  // ── Instrument lines chart ───────────────────────────────────────────────────
  const instCtx = document.getElementById('risk-inst-chart');
  if (instCtx) {
    const datasets = instruments.map(key => {
      const isSel  = sel ? key === sel.toLowerCase() : false;
      const hasSel = !!sel;
      const color  = _colorFor(key);
      const sp     = _startPrices[key] ?? 1;
      return {
        label:           key.toUpperCase(),
        data:            series.map(d => parseFloat(((d[key] ?? 1) * sp).toFixed(2))),
        borderColor:     hasSel && !isSel ? color + '50' : color,
        backgroundColor: 'transparent',
        borderWidth:     isSel ? 3 : hasSel ? 1 : 2,
        pointRadius:     0,
        tension:         0.3,
        yAxisID:         'y',
      };
    });
    _instChart = new Chart(instCtx, {
      type: 'line',
      data: { labels: dates, datasets },
      options: _opts(true),
    });
  }

  // ── Portfolio composite chart ────────────────────────────────────────────────
  const portCtx = document.getElementById('risk-port-chart');
  if (portCtx) {
    _portChart = new Chart(portCtx, {
      type: 'line',
      data: {
        labels: dates,
        datasets: [{
          label:           'Portfolio',
          data:            portValues,
          borderColor:     '#be185d',
          backgroundColor: 'rgba(190,24,93,0.07)',
          borderWidth:     2,
          pointRadius:     0,
          tension:         0.3,
          fill:            true,
        }],
      },
      options: _opts(false, totalEur != null),
    });
  }
}

function _fmtAbs(v, decimals = 0) {
  return v >= 1000
    ? v.toLocaleString('en-IN', { maximumFractionDigits: 0 })
    : v.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

function _opts(showLegend, isPortEur = false) {
  const yFmt = isPortEur
    ? v => `€${_fmtAbs(v)}`
    : v => _fmtAbs(v, 2);
  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: showLegend
        ? { position: 'top', labels: { font: { family: 'IBM Plex Mono', size: 10 }, boxWidth: 10, padding: 10 } }
        : { display: false },
      tooltip: {
        mode: 'index', intersect: false,
        callbacks: { label: ctx => `${ctx.dataset.label}: ${isPortEur ? '€' : ''}${_fmtAbs(ctx.raw, isPortEur ? 0 : 2)}` },
      },
    },
    scales: {
      x: {
        grid: { display: false },
        ticks: { font: { family: 'IBM Plex Mono', size: 9 }, maxTicksLimit: 7, maxRotation: 0 },
      },
      y: {
        grid: { color: 'rgba(0,0,0,.05)' },
        ticks: { font: { family: 'IBM Plex Mono', size: 9 }, callback: yFmt },
      },
    },
  };
}
