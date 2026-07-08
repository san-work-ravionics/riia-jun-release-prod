// Model Evaluation — per-instrument RL diagnostic scorecard viewer
// Instrument selector (geo-tile pattern) + 10-parameter scorecard detail view.
import { api } from './api.js';
import { setEl } from '../shared/utils.js';
import { mkChart, C } from '../shared/charts.js';

let _scorecards = [];
let _selectedInstrument = null;

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
  let data;
  try {
    data = await api('/api/v1/experience/rita/agent-performance/scorecards');
  } catch {
    setEl('me-content', '<div class="empty">Model evaluation data unavailable.</div>');
    return;
  }

  _scorecards = (data && data.scorecards) || [];
  if (!_scorecards.length) {
    setEl('me-instrument-bar', '');
    setEl('me-content', '<div class="empty">No model evaluations yet — run a per-instrument training job to populate this view.</div>');
    return;
  }

  _renderInstrumentBar();

  if (!_selectedInstrument || !_scorecards.find(s => s.instrument === _selectedInstrument)) {
    _selectedInstrument = _scorecards[0].instrument;
  }
  _renderDetail(_selectedInstrument);
}

// ── Instrument selector bar (geo-tile pattern) ────────────────────────────────
function _renderInstrumentBar() {
  const bar = document.getElementById('me-instrument-bar');
  if (!bar) return;

  bar.innerHTML = _scorecards.map(sc => {
    const active = sc.instrument === _selectedInstrument ? ' me-inst-active' : '';
    const sharpe = sc.functional?.F1_sharpe_test?.value;
    const status = sc.overall_status || 'unknown';
    return `<div class="kpi me-inst-tile${active}" data-id="${sc.instrument}"
                 onclick="meSelectInstrument('${sc.instrument}')"
                 style="padding:8px 12px;cursor:pointer;min-width:90px">
      <div class="kpi-label" style="font-size:11px;font-weight:600">${sc.instrument}</div>
      <div class="kpi-value" style="font-size:15px">${sharpe != null ? sharpe.toFixed(3) : '—'}</div>
      <div style="margin-top:2px">${sevBadge(status)}</div>
    </div>`;
  }).join('');
}

export function meSelectInstrument(id) {
  _selectedInstrument = id;
  document.querySelectorAll('.me-inst-tile').forEach(el =>
    el.classList.toggle('me-inst-active', el.dataset.id === id)
  );
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

    <!-- Charts + tables in single row -->
    <div style="display:flex;gap:12px;align-items:flex-start">
      <div style="flex:1;min-width:0" class="chart-wrap">
        <div class="chart-title">Regime Sharpe (F3)</div>
        <div class="chart-box" style="height:180px"><canvas id="chart-me-regime-sharpe"></canvas></div>
      </div>
      <div style="flex:1;min-width:0" class="chart-wrap">
        <div class="chart-title">Action by Regime (T5)</div>
        <div class="chart-box" style="height:180px"><canvas id="chart-me-action-regime"></canvas></div>
      </div>
      <div style="flex:1;min-width:0">${_renderFunctionalTable(f)}</div>
      <div style="flex:1;min-width:0">${_renderTechnicalTable(t)}</div>
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

// ── Functional parameter table ────────────────────────────────────────────────
function _renderFunctionalTable(f) {
  const rows = [
    _paramRow('F1', 'Sharpe Ratio (Test)', f.F1_sharpe_test?.value, 3, f.F1_sharpe_test?.healthy, '> 1.0'),
    _paramRow('F2', 'Max Drawdown (Test)', f.F2_max_drawdown_test?.value != null ? (f.F2_max_drawdown_test.value * 100).toFixed(1) + '%' : null, null, f.F2_max_drawdown_test?.healthy, '> -10%'),
    _paramRow('F4', 'Win Rate', f.F4_win_rate?.value != null ? (f.F4_win_rate.value * 100).toFixed(1) + '%' : null, null, f.F4_win_rate?.healthy, '≥ 45%'),
    _paramRow('F5', 'Baseline Relative', f.F5_baseline_relative?.overall, 4, f.F5_baseline_relative?.healthy, '> 0'),
  ];

  return `<div class="card" style="padding:12px 16px">
    <div class="card-hdr"><span class="card-title">Functional (F1–F5)</span></div>
    <table class="data-tbl" style="margin-top:8px;font-size:12px;width:100%">
      <thead><tr><th>ID</th><th>Parameter</th><th style="text-align:right">Value</th><th style="text-align:center">Status</th><th>Threshold</th></tr></thead>
      <tbody>${rows.join('')}</tbody>
    </table>
  </div>`;
}

// ── Technical parameter table ─────────────────────────────────────────────────
function _renderTechnicalTable(t) {
  const t3 = t.T3_reward_convergence_pct || {};
  const t4 = t.T4_seed_consistency_cv || {};

  const rows = [
    _paramRow('T1', 'Action Entropy', t.T1_action_entropy?.value, 2, t.T1_action_entropy?.healthy, '0.5–1.8'),
    _paramRow('T2', 'Train-Test Gap', t.T2_train_test_sharpe_gap?.value, 2, t.T2_train_test_sharpe_gap?.healthy, '≤ 0.3'),
    _paramRow('T3', 'Convergence Rate', t3.value != null ? t3.value.toFixed(1) + '%' : null, null, t3.healthy, '20–80%'),
    _paramRow('T4', 'Seed Consistency (CV)', t4.value, 4, t4.healthy, '≤ 0.5'),
  ];

  return `<div class="card" style="padding:12px 16px">
    <div class="card-hdr"><span class="card-title">Technical (T1–T5)</span></div>
    <table class="data-tbl" style="margin-top:8px;font-size:12px;width:100%">
      <thead><tr><th>ID</th><th>Parameter</th><th style="text-align:right">Value</th><th style="text-align:center">Status</th><th>Threshold</th></tr></thead>
      <tbody>${rows.join('')}</tbody>
    </table>
  </div>`;
}

function _paramRow(id, name, value, decimals, healthy, threshold) {
  let display;
  if (value == null) {
    display = '—';
  } else if (decimals != null) {
    display = parseFloat(value).toFixed(decimals);
  } else {
    display = value;
  }
  return `<tr>
    <td style="font-weight:600;color:var(--t2)">${id}</td>
    <td>${name}</td>
    <td style="text-align:right;font-family:var(--fm)">${display}</td>
    <td style="text-align:center">${healthDot(healthy)}</td>
    <td style="font-size:10px;color:var(--t3)">${threshold || ''}</td>
  </tr>`;
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
