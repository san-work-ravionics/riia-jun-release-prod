// ── Scenarios ──────────────────────────────────────────────
import { api } from './api.js';
import { setEl } from './utils.js';
import { mkChart, chartOpts, C } from './charts.js';
import { loadHealth, loadProgress } from './health.js';
import { createCache } from '../shared/api-cache.js';
import { t } from '../shared/i18n.js';

const cachedApi = createCache(api);

export function setScenarioPeriod(from, to) {
  document.getElementById('inp-bt-from').value = from;
  document.getElementById('inp-bt-to').value = to;
}

export async function loadScenarios() {
  // Show last backtest results on page load only when real data exists
  try {
    const perf  = await cachedApi('/api/v1/performance-summary', 120000);
    const daily = await cachedApi('/api/v1/experience/rita/backtest-daily', 120000);
    // total_days === 0 means no completed backtest — don't render garbage NaN KPIs
    const hasData = perf && typeof perf === 'object' && perf.total_days > 0;
    if (hasData) {
      renderScenarioResults(perf, daily);
      updateGoalRecommendation(perf);
    }
  } catch (_) {}
}

export async function runScenarioBacktest() {
  const from = document.getElementById('inp-bt-from').value;
  const to   = document.getElementById('inp-bt-to').value;
  if (!from || !to)   { alert(t('scenarios.alert_dates_required')); return; }
  if (from >= to)     { alert(t('scenarios.alert_date_order')); return; }

  const btn     = document.getElementById('btn-scenario');
  const spinner = document.getElementById('scenario-spinner');
  const badge   = document.getElementById('scenario-status');
  btn.disabled = true; btn.textContent = '⏳ ' + t('ui.loading');
  spinner.style.display = '';
  badge.className = 'badge run'; badge.textContent = t('status.running');
  setEl('scenario-result', '');

  try {
    const instrument = localStorage.getItem('ritaInstrument') || 'NIFTY';
    const submitted = await api('/api/v1/backtest', 'POST', { instrument, start_date: from, end_date: to });
    const runId = submitted.run_id;

    // Poll until complete or failed (max 3 min, 3 s interval)
    const MAX_POLLS = 60;
    let polls = 0;
    while (polls < MAX_POLLS) {
      await new Promise(r => setTimeout(r, 3000));
      const s = await api(`/api/v1/backtest-status/${runId}`);
      if (s.status === 'complete') break;
      if (s.status === 'failed') throw new Error('Backtest failed — check model files exist for this instrument.');
      polls++;
    }
    if (polls >= MAX_POLLS) throw new Error('Backtest timed out after 3 minutes.');

    const [perf, daily] = await Promise.all([
      api('/api/v1/performance-summary'),
      api('/api/v1/experience/rita/backtest-daily'),
    ]);
    badge.className = 'badge ok'; badge.textContent = t('status.complete');
    renderScenarioResults(perf, daily, from, to);
    updateGoalRecommendation(perf);
    loadProgress(); loadHealth();
  } catch (e) {
    badge.className = 'badge err'; badge.textContent = t('status.failed');
    setEl('scenario-result', `<div class="result-panel"><div style="color:var(--danger);font-size:12px">Error: ${e.message}</div></div>`);
  } finally {
    btn.disabled = false; btn.textContent = '▶ ' + t('btn.run_backtest');
    spinner.style.display = 'none';
  }
}

export function renderScenarioResults(perf, daily, from, to) {
  if (!perf || typeof perf !== 'object' || !Object.keys(perf).length) { setEl('scenario-result', `<div class="empty">${t('ui.no_data')}</div>`); return; }
  // perf is a flat dict {metric: value} from /api/v1/performance-summary.
  // Use null-safe helper: check the raw value before calling parseFloat so we
  // never produce "NaN" in the UI (parseFloat(null) === NaN, and NaN != null).
  const _f = v => (v !== null && v !== undefined) ? parseFloat(v) : null;

  const sharpe  = _f(perf.sharpe_ratio)               !== null ? _f(perf.sharpe_ratio).toFixed(3)                     : '—';
  const mdd     = _f(perf.max_drawdown_pct)            !== null ? _f(perf.max_drawdown_pct).toFixed(2) + '%'           : '—';
  const ret     = _f(perf.portfolio_total_return_pct)  !== null ? _f(perf.portfolio_total_return_pct).toFixed(2) + '%' : '—';
  const bnh     = _f(perf.benchmark_total_return_pct)  !== null ? _f(perf.benchmark_total_return_pct).toFixed(2) + '%' : '—';
  const cagr    = _f(perf.portfolio_cagr_pct)          !== null ? _f(perf.portfolio_cagr_pct).toFixed(2) + '%'         : '—';
  const trades  = perf.total_trades  !== null && perf.total_trades  !== undefined ? perf.total_trades  : '—';
  const wr      = _f(perf.win_rate_pct) !== null ? _f(perf.win_rate_pct).toFixed(1) + '%' : '—';
  const days    = perf.total_days    !== null && perf.total_days    !== undefined ? perf.total_days    : '—';
  const sharpeCls = _f(perf.sharpe_ratio) !== null && _f(perf.sharpe_ratio) >= 1.0 ? 'pos' : 'neu';
  const mddCls    = _f(perf.max_drawdown_pct) !== null && Math.abs(_f(perf.max_drawdown_pct)) <= 5 ? 'pos' : 'warn';
  const label = (from && to) ? `${from} → ${to}` : t('scenarios.last_backtest');

  let html = `
    <div class="card-hdr" style="margin-bottom:10px">
      <span class="card-title">${t('scenarios.results')} — ${label}</span>
      <span class="badge ok" style="margin-left:8px">${days} ${t('ui.days')}</span>
    </div>
    <div class="kpi-row-4" style="margin-bottom:14px">
      <div class="kpi"><div class="kpi-label">${t('kpi.sharpe_ratio')}</div><div class="kpi-value ${sharpeCls}">${sharpe}</div><div class="kpi-delta">target ≥ 1.0</div></div>
      <div class="kpi"><div class="kpi-label">${t('kpi.max_drawdown')}</div><div class="kpi-value ${mddCls}">${mdd}</div><div class="kpi-delta">target &lt; 10%</div></div>
      <div class="kpi"><div class="kpi-label">${t('scenarios.portfolio_return')}</div><div class="kpi-value neu">${ret}</div><div class="kpi-delta">${t('perf.bnh')} ${bnh}</div></div>
      <div class="kpi"><div class="kpi-label">${t('health.cagr')}</div><div class="kpi-value neu">${cagr}</div><div class="kpi-delta">${trades} trades · WR ${wr}</div></div>
    </div>`;

  if (daily && daily.length) {
    const labels = daily.map(r => r.date);
    const portVals = daily.map(r => r.portfolio_value != null ? ((parseFloat(r.portfolio_value) - 1) * 100).toFixed(2) : null);
    const bnhVals  = daily.map(r => r.benchmark_value  != null ? ((parseFloat(r.benchmark_value)  - 1) * 100).toFixed(2) : null);
    html += `<div class="chart-wrap"><div class="chart-title">Cumulative Return — RITA vs Buy &amp; Hold</div>
      <div class="chart-box"><canvas id="chart-scenario-returns"></canvas></div></div>`;
    setEl('scenario-result', html);
    mkChart('chart-scenario-returns', {
      type: 'line',
      data: {
        labels,
        datasets: [
          { label: 'RITA',      data: portVals, borderColor: C.build,  backgroundColor: 'rgba(26,107,60,0.07)', fill: true,  pointRadius: 0, borderWidth: 2 },
          { label: 'Nifty B&H', data: bnhVals,  borderColor: C.warn,   backgroundColor: 'transparent',          fill: false, pointRadius: 0, borderWidth: 1.5, borderDash: [4,3] },
        ],
      },
      options: chartOpts('Return (%)', v => v + '%', labels),
    });
  } else {
    setEl('scenario-result', html);
  }
}

export function updateGoalRecommendation(perf) {
  const goalResult = document.getElementById('goal-result');
  if (!goalResult || !perf) return;

  const _f = v => (v !== null && v !== undefined && !isNaN(parseFloat(v))) ? parseFloat(v) : null;
  const cagr   = _f(perf.portfolio_cagr_pct);
  const sharpe = _f(perf.sharpe_ratio);
  const mdd    = _f(perf.max_drawdown_pct);
  if (cagr === null) return;

  const targetEl = document.getElementById('inp-target');
  const target   = targetEl ? _f(targetEl.value) : null;

  const onTrack  = target === null || cagr >= target;
  const statusCls = onTrack ? 'ok' : 'warn';
  const statusLabel = onTrack ? t('scenarios.on_track') : t('scenarios.below_target');
  const advice = target !== null
    ? (onTrack
        ? `RITA's backtest CAGR of ${cagr.toFixed(1)}% meets your ${target.toFixed(1)}% target. Strategy is viable.`
        : `RITA's backtest CAGR (${cagr.toFixed(1)}%) is below your ${target.toFixed(1)}% target. Consider retraining or lowering the target.`)
    : `Latest backtest CAGR: ${cagr.toFixed(1)}%.`;

  const recHtml = `<div class="result-panel" id="backtest-recommendation">
    <div class="card-hdr" style="margin-bottom:10px">
      <span class="card-title">${t('scenarios.recommendation')}</span>
      <span class="badge ${statusCls}" style="margin-left:8px">${statusLabel}</span>
    </div>
    <div style="font-size:12px;color:var(--t2);margin-bottom:10px">${advice}</div>
    <div class="kpi-row-4">
      <div class="kpi"><div class="kpi-label">${t('scenarios.rita_cagr')}</div><div class="kpi-value ${onTrack ? 'pos' : 'neg'}">${cagr.toFixed(2)}%</div><div class="kpi-delta">${t('scenarios.from_backtest')}</div></div>
      ${target !== null ? `<div class="kpi"><div class="kpi-label">${t('scenarios.your_target')}</div><div class="kpi-value">${target.toFixed(1)}%</div><div class="kpi-delta">${t('scenarios.annual_return')}</div></div>` : ''}
      ${sharpe !== null ? `<div class="kpi"><div class="kpi-label">${t('kpi.sharpe_ratio')}</div><div class="kpi-value ${sharpe >= 1 ? 'pos' : 'neg'}">${sharpe.toFixed(3)}</div><div class="kpi-delta">target ≥ 1.0</div></div>` : ''}
      ${mdd !== null ? `<div class="kpi"><div class="kpi-label">${t('kpi.max_drawdown')}</div><div class="kpi-value ${Math.abs(mdd) < 10 ? 'pos' : 'warn'}">${mdd.toFixed(2)}%</div><div class="kpi-delta">target &lt; 10%</div></div>` : ''}
    </div>
  </div>`;

  const existing = document.getElementById('backtest-recommendation');
  if (existing) {
    existing.outerHTML = recHtml;
  } else {
    goalResult.insertAdjacentHTML('beforeend', recHtml);
  }
}
