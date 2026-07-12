// Model Evaluation — per-instrument RL diagnostic scorecard viewer
// Instrument selector (geo-tile pattern) + 10-parameter scorecard detail view.
// F34 Phase 2.5: per-instrument summary table (training_history latest round)
// + clickable rows loading equity/drawdown/actions evaluation plots.
import { api } from './api.js';
import { setEl, fmt, fmtPct } from '../shared/utils.js';
import { mkChart, C } from '../shared/charts.js';

let _scorecards = [];
let _selectedInstrument = null;
let _summaryRows = [];
let _summaryData = null;
let _selectedRowInstrument = null;

// ── Status helpers ────────────────────────────────────────────────────────────
const _SEV_CLS  = { fail: 'err', warn: 'warn', pass: 'ok', info: 'neu' };
const _SEV_ICON = { fail: '✖', warn: '⚠', pass: '✔', info: 'ℹ' };

function sevBadge(s) {
  return `<span class="badge ${_SEV_CLS[s] || 'neu'}">${(s || '—').toUpperCase()}</span>`;
}

function healthDot(healthy) {
  if (healthy === true)  return '<span style="color:#16a34a">●</span>';
  if (healthy === false) return '<span style="color:#dc2626">●</span>';
  return '<span style="color:var(--t4)">○</span>';
}

// ── Main loader ───────────────────────────────────────────────────────────────
export async function loadModelEval() {
  await Promise.all([_loadSummary(), _loadScorecards()]);
  _renderSummaryTable(_summaryData);
  _defaultSelectRow();
}

// ── F34 P2.5: summary table (latest training round per instrument) ───────────
async function _loadSummary() {
  try {
    _summaryData = await api('/api/v1/experience/rita/model-eval-summary');
    _summaryRows = (_summaryData && _summaryData.rows) || [];
  } catch {
    _summaryData = null;
    _summaryRows = [];
  }
}

function _gateBadge(gatePass) {
  if (gatePass === true)  return '<span class="badge ok">PASS</span>';
  if (gatePass === false) return '<span class="badge warn">BELOW GATE</span>';
  return '<span class="badge neu">NO DATA</span>';
}

let _mergedRows = [];
let _sortCol = null;
let _sortAsc = true;

const _COLS = [
  { key: 'instrument',   label: 'Instrument',     align: 'left' },
  { key: 'last_trained',  label: 'Last Trained',   align: 'left' },
  { key: 'timesteps',     label: 'Timesteps',      align: 'right' },
  { key: 'val_sharpe',    label: 'Val Sharpe',     align: 'right' },
  { key: 'val_mdd_pct',   label: 'Val MDD%',      align: 'right' },
  { key: 'bt_sharpe',     label: 'BT Sharpe',     align: 'right' },
  { key: 'bt_mdd_pct',    label: 'BT MDD%',       align: 'right' },
  { key: 'trades',        label: 'Trades',         align: 'right' },
  { key: 'f1_sharpe',     label: 'Sharpe (Test)',  align: 'right', sc: true },
  { key: 'f2_mdd',        label: 'Max DD (Test)',  align: 'right', sc: true },
  { key: 'f4_winrate',    label: 'Win Rate',       align: 'right', sc: true },
  { key: 'f5_baseline',   label: 'vs Baseline',    align: 'right', sc: true },
  { key: 't1_entropy',    label: 'Entropy',        align: 'right', sc: true },
  { key: 't2_gap',        label: 'Train-Test Gap', align: 'right', sc: true },
  { key: 't3_conv',       label: 'Convergence',    align: 'right', sc: true },
  { key: 't4_seedcv',     label: 'Seed CV',        align: 'right', sc: true },
];

function _buildMergedRows(data) {
  const rows = (data && data.rows) || [];
  return rows.map(r => {
    const sc = _scorecards.find(s => s.instrument === r.instrument);
    const f = sc?.functional || {};
    const t = sc?.technical || {};
    const t3 = t.T3_reward_convergence_pct || {};
    const t4 = t.T4_seed_consistency_cv || {};
    return {
      raw: r, sc,
      instrument: r.instrument,
      last_trained: r.last_trained || null,
      timesteps: r.timesteps,
      val_sharpe: r.val_sharpe,
      val_mdd_pct: r.val_mdd_pct,
      bt_sharpe: r.backtest_sharpe,
      bt_mdd_pct: r.backtest_mdd_pct,
      trades: r.trade_count,
      f1_sharpe: f.F1_sharpe_test?.value ?? null,
      f1_h: f.F1_sharpe_test?.healthy,
      f2_mdd: f.F2_max_drawdown_test?.value ?? null,
      f2_h: f.F2_max_drawdown_test?.healthy,
      f4_winrate: f.F4_win_rate?.value ?? null,
      f4_h: f.F4_win_rate?.healthy,
      f5_baseline: f.F5_baseline_relative?.overall ?? null,
      f5_h: f.F5_baseline_relative?.healthy,
      t1_entropy: t.T1_action_entropy?.value ?? null,
      t1_h: t.T1_action_entropy?.healthy,
      t2_gap: t.T2_train_test_sharpe_gap?.value ?? null,
      t2_h: t.T2_train_test_sharpe_gap?.healthy,
      t3_conv: t3.value ?? null,
      t3_h: t3.healthy,
      t4_seedcv: t4.value ?? null,
      t4_h: t4.healthy,
    };
  });
}

function _fmtCell(m, col) {
  const v = m[col.key];
  const mono = 'font-family:var(--fm)';
  const al = col.align === 'right' ? 'text-align:right;' : '';
  if (col.key === 'instrument')
    return `<td style="font-weight:600">${v}</td>`;
  if (col.key === 'last_trained')
    return `<td style="${mono};font-size:11px">${v || '—'}</td>`;
  if (col.key === 'timesteps')
    return `<td style="${al}">${v != null ? v.toLocaleString() : '—'}</td>`;
  if (col.key === 'val_sharpe' || col.key === 'bt_sharpe')
    return `<td style="${al}${mono}">${fmt(v, 3)}</td>`;
  if (col.key === 'val_mdd_pct' || col.key === 'bt_mdd_pct')
    return `<td style="${al}${mono}">${fmtPct(v)}</td>`;
  if (col.key === 'trades')
    return `<td style="${al}${mono}">${v != null ? v : '—'}</td>`;
  if (col.key === 'f1_sharpe')
    return `<td style="${al}${mono}">${healthDot(m.f1_h)} ${v != null ? v.toFixed(3) : '—'}</td>`;
  if (col.key === 'f2_mdd')
    return `<td style="${al}${mono}">${healthDot(m.f2_h)} ${v != null ? (v*100).toFixed(1)+'%' : '—'}</td>`;
  if (col.key === 'f4_winrate')
    return `<td style="${al}${mono}">${healthDot(m.f4_h)} ${v != null ? (v*100).toFixed(1)+'%' : '—'}</td>`;
  if (col.key === 'f5_baseline')
    return `<td style="${al}${mono}">${healthDot(m.f5_h)} ${v != null ? v.toFixed(4) : '—'}</td>`;
  if (col.key === 't1_entropy')
    return `<td style="${al}${mono}">${healthDot(m.t1_h)} ${v != null ? v.toFixed(2) : '—'}</td>`;
  if (col.key === 't2_gap')
    return `<td style="${al}${mono}">${healthDot(m.t2_h)} ${v != null ? v.toFixed(2) : '—'}</td>`;
  if (col.key === 't3_conv')
    return `<td style="${al}${mono}">${healthDot(m.t3_h)} ${v != null ? v.toFixed(1)+'%' : '—'}</td>`;
  if (col.key === 't4_seedcv')
    return `<td style="${al}${mono}">${healthDot(m.t4_h)} ${v != null ? v.toFixed(4) : '—'}</td>`;
  return `<td style="${al}">${v ?? '—'}</td>`;
}

export function meSortTable(colIdx) {
  const col = _COLS[colIdx];
  if (_sortCol === col.key) { _sortAsc = !_sortAsc; }
  else { _sortCol = col.key; _sortAsc = true; }

  _mergedRows.sort((a, b) => {
    let va = a[col.key], vb = b[col.key];
    if (va == null && vb == null) return 0;
    if (va == null) return 1;
    if (vb == null) return -1;
    if (typeof va === 'string') return _sortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
    return _sortAsc ? va - vb : vb - va;
  });
  _renderTableHeaders();
  _renderTableBody();
}

function _renderTableHeaders() {
  const thead = document.querySelector('#me-summary-table thead tr');
  if (!thead) return;
  const thStyle = 'cursor:pointer;user-select:none;white-space:nowrap';
  thead.innerHTML = _COLS.map((c, i) => {
    const arrow = _sortCol === c.key ? (_sortAsc ? ' ▲' : ' ▼') : '';
    const al = c.align === 'right' ? 'text-align:right;' : '';
    return `<th style="${al}${thStyle}" onclick="meSortTable(${i})">${c.label}${arrow}</th>`;
  }).join('');
}

function _renderTableBody() {
  const tbody = document.querySelector('#me-summary-table tbody');
  if (!tbody) return;
  tbody.innerHTML = _mergedRows.map(m => {
    const r = m.raw;
    const click = r.has_history
      ? ` onclick="meSelectRow('${r.instrument}')" style="cursor:pointer"` : '';
    const tip = r.source
      ? ` title="source: ${r.source}${r.round != null ? ' · round ' + r.round : ''}"` : '';
    return `<tr class="me-sum-row" data-inst="${r.instrument}"${click}${tip}>${_COLS.map(c => _fmtCell(m, c)).join('')}</tr>`;
  }).join('');
  if (_selectedRowInstrument) {
    document.querySelectorAll('.me-sum-row').forEach(el =>
      el.classList.toggle('me-row-active', el.dataset.inst === _selectedRowInstrument));
  }
}

function _renderSummaryTable(data) {
  if (!data || !(data.rows || []).length) {
    setEl('me-summary-table', '<div class="empty">No instruments configured.</div>');
    return;
  }
  const metaEl = document.getElementById('me-window-meta');
  if (metaEl) metaEl.textContent = `Validation: ${data.val_window || '—'} · Backtest: ${data.backtest_window || '—'}`;

  _mergedRows = _buildMergedRows(data);

  const thStyle = 'cursor:pointer;user-select:none;white-space:nowrap';
  const headers = _COLS.map((c, i) => {
    const arrow = _sortCol === c.key ? (_sortAsc ? ' ▲' : ' ▼') : '';
    const al = c.align === 'right' ? 'text-align:right;' : '';
    return `<th style="${al}${thStyle}" onclick="meSortTable(${i})">${c.label}${arrow}</th>`;
  }).join('');

  setEl('me-summary-table', `<table class="data-tbl" style="font-size:12px;width:100%">
      <thead><tr>${headers}</tr></thead>
      <tbody></tbody>
    </table>`);
  _renderTableBody();
}

function _defaultSelectRow() {
  try {
    const withData = _summaryRows.filter(r => r.has_history);
    if (!withData.length) return;
    const target = withData.find(r => r.instrument === 'ASML') || withData[0];
    meSelectRow(target.instrument);
  } catch { /* default selection is best-effort */ }
}

export function meSelectRow(instrument) {
  _selectedRowInstrument = instrument;
  document.querySelectorAll('.me-sum-row').forEach(el =>
    el.classList.toggle('me-row-active', el.dataset.inst === instrument)
  );
  _renderEvalPlots(instrument);
  // Delegate to the existing scorecard view when one exists for this instrument.
  if (_scorecards.find(s => s.instrument === instrument)) {
    meSelectInstrument(instrument);
  }
}

async function _renderEvalPlots(instrument) {
  setEl('me-eval-plots-title', `Evaluation — ${instrument}`);
  let series = [];
  try {
    series = await api(`/api/v1/experience/rita/backtest-daily?instrument=${encodeURIComponent(instrument)}`);
  } catch {
    series = [];
  }
  if (instrument !== _selectedRowInstrument) return; // stale response — a newer row was clicked

  const msgEl    = document.getElementById('me-eval-plots-msg');
  const chartsEl = document.getElementById('me-eval-charts');
  if (!series || !series.length) {
    if (msgEl)    { msgEl.style.display = ''; msgEl.textContent = `No backtest series for ${instrument}.`; }
    if (chartsEl) chartsEl.style.display = 'none';
    return;
  }
  if (msgEl)    msgEl.style.display = 'none';
  if (chartsEl) chartsEl.style.display = 'flex';

  const labels = series.map(d => d.date);
  const pv     = series.map(d => d.portfolio_value);
  const bv     = series.map(d => d.benchmark_value);
  const alloc  = series.map(d => d.allocation);

  // Drawdown computed client-side from portfolio_value running max.
  let peak = -Infinity;
  const dd = pv.map(v => {
    if (v != null && v > peak) peak = v;
    return v != null && peak > 0 ? ((v / peak) - 1) * 100 : null;
  });

  const axis = { x: { grid: { display: false }, ticks: { maxTicksLimit: 8, font: { size: 9 } } },
                 y: { grid: { color: 'rgba(0,0,0,0.06)' }, ticks: { font: { size: 9 } } } };

  mkChart('chart-me-equity', {
    type: 'line',
    data: { labels, datasets: [
      { label: 'Portfolio', data: pv, borderColor: C.run,  backgroundColor: C.run + '22', borderWidth: 1.5, pointRadius: 0, tension: 0.15 },
      { label: 'Benchmark', data: bv, borderColor: C.t3,   borderDash: [4, 3], borderWidth: 1.2, pointRadius: 0, tension: 0.15 },
    ] },
    options: { responsive: true, maintainAspectRatio: false,
      plugins: { legend: { position: 'bottom', labels: { boxWidth: 10, font: { size: 10 } } } },
      scales: axis },
  });

  mkChart('chart-me-drawdown', {
    type: 'line',
    data: { labels, datasets: [
      { label: 'Drawdown %', data: dd, borderColor: C.danger, backgroundColor: C.danger + '22', fill: true, borderWidth: 1.2, pointRadius: 0, tension: 0.1 },
    ] },
    options: { responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false },
        tooltip: { callbacks: { label: ctx => `DD: ${ctx.parsed.y?.toFixed(2) ?? '—'}%` } } },
      scales: axis },
  });

  mkChart('chart-me-actions', {
    type: 'line',
    data: { labels, datasets: [
      { label: 'Allocation', data: alloc, borderColor: C.build, backgroundColor: C.build + '22', stepped: true, fill: true, borderWidth: 1.2, pointRadius: 0 },
    ] },
    options: { responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: axis },
  });
}

// ── Existing scorecard flow (unchanged behaviour) ─────────────────────────────
async function _loadScorecards() {
  let data;
  try {
    data = await api('/api/v1/experience/rita/agent-performance/scorecards');
  } catch {
    setEl('me-content', '<div class="empty">Model evaluation data unavailable.</div>');
    return;
  }

  _scorecards = (data && data.scorecards) || [];
  if (!_scorecards.length) {
    setEl('me-content', '<div class="empty">No model evaluations yet — run a per-instrument training job to populate this view.</div>');
    return;
  }

  if (!_selectedInstrument || !_scorecards.find(s => s.instrument === _selectedInstrument)) {
    _selectedInstrument = _scorecards[0].instrument;
  }
  _renderDetail(_selectedInstrument);
}

export function meSelectInstrument(id) {
  _selectedInstrument = id;
  _renderDetail(id);
}

// ── Detail renderer ───────────────────────────────────────────────────────────
function _renderDetail(instrumentId) {
  const sc = _scorecards.find(s => s.instrument === instrumentId);
  if (!sc) {
    setEl('me-content', '<div class="empty">No data for this instrument.</div>');
    return;
  }

  const f = sc.functional || {};
  const t = sc.technical || {};
  const insights = sc.insights || [];

  const html = `
    <div class="me-meta" style="display:flex;gap:16px;align-items:center;margin-bottom:16px;flex-wrap:wrap">
      <span style="font-size:18px;font-weight:700">${sc.instrument}</span>
      ${sevBadge(sc.overall_status)}
      <span style="font-size:11px;color:var(--t3);font-family:var(--fm)">Run: ${sc.run_id || '—'}</span>
      <span style="font-size:11px;color:var(--t3)">Config: ${sc.config_source || '—'}</span>
      <span style="font-size:11px;color:var(--t3)">${sc.generated_at ? new Date(sc.generated_at).toLocaleString() : ''}</span>
    </div>

    <!-- KPI strip -->
    <div class="kpi-row" style="grid-template-columns:repeat(6,1fr);margin-bottom:16px">
      ${_kpi('Sharpe (Test)', f.F1_sharpe_test?.value, 3, f.F1_sharpe_test?.healthy, '> 1.0')}
      ${_kpi('Max Drawdown', f.F2_max_drawdown_test?.value != null ? (f.F2_max_drawdown_test.value * 100).toFixed(1) + '%' : null, null, f.F2_max_drawdown_test?.healthy, '> -10%')}
      ${_kpi('Win Rate', f.F4_win_rate?.value != null ? (f.F4_win_rate.value * 100).toFixed(1) + '%' : null, null, f.F4_win_rate?.healthy, '≥ 45%')}
      ${_kpi('vs Baseline', f.F5_baseline_relative?.overall, 2, f.F5_baseline_relative?.healthy, '> 0')}
      ${_kpi('Action Entropy', t.T1_action_entropy?.value, 2, t.T1_action_entropy?.healthy, '0.5–1.8')}
      ${_kpi('Train-Test Gap', t.T2_train_test_sharpe_gap?.value, 2, t.T2_train_test_sharpe_gap?.healthy, '≤ 0.3')}
    </div>

    <!-- Three charts in single row -->
    <div style="display:flex;gap:12px;align-items:flex-start">
      <div style="flex:1;min-width:0" class="chart-wrap">
        <div class="chart-title">Regime Sharpe (F3)</div>
        <div class="chart-box" style="height:180px"><canvas id="chart-me-regime-sharpe"></canvas></div>
      </div>
      <div style="flex:1;min-width:0" class="chart-wrap">
        <div class="chart-title">Baseline Relative (F5)</div>
        <div class="chart-box" style="height:180px"><canvas id="chart-me-baseline"></canvas></div>
      </div>
      <div style="flex:1;min-width:0" class="chart-wrap">
        <div class="chart-title">Action by Regime (T5)</div>
        <div class="chart-box" style="height:180px"><canvas id="chart-me-action-regime"></canvas></div>
      </div>
    </div>

    <!-- Diagnostic Insights -->
    ${insights.length ? `
    <div class="card" style="margin-top:16px;padding:12px 16px">
      <div class="card-hdr"><span class="card-title">Diagnostic Insights</span></div>
      <div style="margin-top:8px;display:grid;grid-template-columns:1fr 1fr;gap:0 16px">
        ${insights.map(i => `<div style="padding:4px 0;font-size:12px;line-height:1.5;border-bottom:1px solid var(--border)">
          <span style="margin-right:6px">${_SEV_ICON[i.severity] || '·'}</span>
          ${sevBadge(i.severity)}
          <b style="margin:0 6px">${i.parameter}</b>
          <span style="color:var(--t2)">${i.message}</span>
          ${i.action ? `<div style="margin-left:24px;font-size:11px;color:var(--t3);margin-top:2px">↳ ${i.action}</div>` : ''}
        </div>`).join('')}
      </div>
    </div>` : ''}
  `;

  setEl('me-content', html);
  _renderRegimeSharpeChart(f);
  _renderBaselineChart(f);
  _renderActionRegimeChart(t);
}

// ── KPI card helper ───────────────────────────────────────────────────────────
function _kpi(label, value, decimals, healthy, threshold) {
  let display;
  if (value == null) {
    display = '—';
  } else if (decimals != null) {
    display = parseFloat(value).toFixed(decimals);
  } else {
    display = value;
  }
  return `<div class="kpi">
    <div class="kpi-label">${label}</div>
    <div class="kpi-value">${healthDot(healthy)} ${display}</div>
    <div class="kpi-delta" style="font-size:9px;color:var(--t3)">${threshold || ''}</div>
  </div>`;
}

// ── F3: Market Regime Sharpe chart ────────────────────────────────────────────
function _renderRegimeSharpeChart(f) {
  const f3 = f.F3_market_regime_performance || {};
  const regimes = ['bull', 'bear', 'sideways'];
  const labels = ['Bull', 'Bear', 'Sideways'];
  const values = regimes.map(r => f3[r]?.sharpe ?? null);
  const colors = [C.build, C.danger, C.t3];

  mkChart('chart-me-regime-sharpe', {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: colors.map(c => c + 'CC'),
        borderColor: colors,
        borderWidth: 1,
        borderRadius: 4,
      }],
    },
    options: {
      indexAxis: 'y',
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: ctx => `Sharpe: ${ctx.parsed.x?.toFixed(3) ?? '—'}` } },
      },
      scales: {
        x: { grid: { color: 'rgba(0,0,0,0.06)' }, title: { display: true, text: 'Sharpe Ratio', font: { size: 10 } } },
        y: { grid: { display: false } },
      },
    },
  });
}

// ── F5: Baseline Relative performance chart ──────────────────────────────────
function _renderBaselineChart(f) {
  const f5 = f.F5_baseline_relative || {};
  const regimes = ['bull', 'bear', 'sideways'];
  const labels = ['Bull', 'Bear', 'Sideways'];
  const values = regimes.map(r => f5[r] ?? null);
  const colors = values.map(v => v != null && v > 0 ? C.build : C.danger);

  mkChart('chart-me-baseline', {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: colors.map(c => c + 'CC'),
        borderColor: colors,
        borderWidth: 1,
        borderRadius: 4,
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: ctx => `Relative: ${ctx.parsed.y?.toFixed(4) ?? '—'}` } },
      },
      scales: {
        x: { grid: { display: false } },
        y: { grid: { color: 'rgba(0,0,0,0.06)' }, title: { display: true, text: 'vs Baseline', font: { size: 10 } } },
      },
    },
  });
}

// ── T5: Action distribution by regime chart ───────────────────────────────────
function _renderActionRegimeChart(t) {
  const t5 = t.T5_per_regime_action_distribution || {};
  const counts = t5.action_counts || {};
  const regimes = ['bull', 'bear', 'sideways'];
  const labels = ['Bull', 'Bear', 'Sideways'];
  const actions = ['cash', 'half', 'full', 'hedged'];
  const actionColors = ['#94a3b8', C.run, C.build, C.mon];

  const datasets = actions.map((action, i) => ({
    label: action.charAt(0).toUpperCase() + action.slice(1),
    data: regimes.map(r => counts[r]?.[action] ?? 0),
    backgroundColor: actionColors[i] + 'CC',
    borderColor: actionColors[i],
    borderWidth: 1,
    borderRadius: 2,
  }));

  mkChart('chart-me-action-regime', {
    type: 'bar',
    data: { labels, datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { position: 'bottom', labels: { boxWidth: 10, font: { size: 10 } } },
      },
      scales: {
        x: { stacked: true, grid: { display: false } },
        y: { stacked: true, grid: { color: 'rgba(0,0,0,0.06)' }, title: { display: true, text: 'Action Count', font: { size: 10 } } },
      },
    },
  });
}
