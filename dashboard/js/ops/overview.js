// ── Overview ──────────────────────────────────────────────────────────────────
import { apiFetch } from './api.js';
import { fmt, badge, setEl } from './utils.js';
import { t } from '../shared/i18n.js';

export async function loadOverview() {
  const [health, metrics, progress] = await Promise.all([
    apiFetch('/health'),
    apiFetch('/api/experience/ops/metrics/summary'),
    apiFetch('/progress'),
  ]);

  // API status pill
  const dot = document.getElementById('api-dot');
  const txt = document.getElementById('api-text');
  if (health && health.status === 'ok') {
    dot.className = 'status-dot ok';
    txt.textContent = health.model_exists ? t('health.model_loaded') : t('health.api_online');
  } else {
    dot.className = 'status-dot danger';
    txt.textContent = t('health.api_offline');
  }

  // KPI strip
  const apiOk = health && health.status === 'ok';
  document.getElementById('kpi-status').textContent = apiOk ? t('status.active') : t('status.failed');
  document.getElementById('kpi-status').className = 'kpi-val ' + (apiOk ? 'ok' : 'danger');
  document.getElementById('kpi-status-sub').textContent = apiOk ? t('ops.all_systems_nominal') : t('ops.api_unreachable');

  if (metrics) {
    const req = metrics.api_requests || {};
    document.getElementById('kpi-requests').textContent = req.total_requests ?? '—';
    const errRate = req.error_rate_pct != null ? req.error_rate_pct.toFixed(1) + '%'
      : (req.total_requests > 0 ? ((req.error_count / req.total_requests) * 100).toFixed(1) + '%' : '0.0%');
    document.getElementById('kpi-errors').textContent = errRate;
    document.getElementById('kpi-errors').className = 'kpi-val ' + (parseFloat(errRate) > 5 ? 'warn' : 'ok');

    document.getElementById('kpi-pipeline').textContent = metrics.pipeline.completed_steps ?? '—';
  }

  const mcp = await apiFetch('/api/v1/mcp-calls');
  document.getElementById('kpi-mcp').textContent = mcp ? mcp.length : '—';

  if (progress && progress.steps) {
    const steps = progress.steps;
    const total = steps.length;
    const completedCount = steps.filter(s => s.status === 'completed').length;
    const pctComplete = total > 0 ? Math.round((completedCount / total) * 100) : 0;

    document.getElementById('kpi-pipeline').textContent = completedCount;
    document.getElementById('kpi-pipeline-sub').textContent = `of ${total} complete (${pctComplete}%)`;

    // Sidebar footer (elements are optional — ops.html may not include them)
    const allDone = completedCount >= total;
    const mcStatus = document.getElementById('mc-status-text');
    const mcSteps = document.getElementById('mc-steps');
    const mcBar = document.getElementById('mc-bar');
    if (mcStatus) mcStatus.textContent = allDone ? t('ops.pipeline_complete') : `${completedCount}/${total} Steps Done`;
    if (mcSteps) mcSteps.textContent = `${completedCount} / ${total}`;
    if (mcBar) mcBar.style.width = pctComplete + '%';
  }

  if (health) {
    const mcModel = document.getElementById('mc-model');
    const mcLastrun = document.getElementById('mc-lastrun');
    if (mcModel) {
      mcModel.textContent = health.model_exists
        ? (health.model_age_days != null ? `${health.model_age_days}d old` : 'exists')
        : t('ops.model_not_trained');
      mcModel.className = 'mc-v ' + (health.model_exists ? 'ok' : 'warn');
    }
    if (mcLastrun) mcLastrun.textContent = health.last_pipeline_run
      ? health.last_pipeline_run.slice(0, 16) : 'never';
  }

  // Model card
  if (metrics && metrics.training && Object.keys(metrics.training).length) {
    const tr = metrics.training;
    document.getElementById('mdl-sharpe').textContent = fmt(tr.latest_backtest_sharpe);
    document.getElementById('mdl-mdd').textContent = fmt(tr.latest_backtest_mdd_pct) + '%';
    document.getElementById('mdl-cagr').textContent = fmt(tr.latest_backtest_cagr_pct) + '%';
    if (tr.backtest_start_date && tr.backtest_end_date) {
      document.getElementById('mdl-bt-range').textContent = `${tr.backtest_start_date} → ${tr.backtest_end_date}`;
    }

    const sharpePct = Math.min(100, (tr.latest_backtest_sharpe / 1.5) * 100);
    document.getElementById('bar-sharpe').style.width = sharpePct + '%';
    document.getElementById('bar-sharpe-pct').textContent = fmt(tr.latest_backtest_sharpe, 3);

    const mddPct = Math.max(0, 100 - (Math.abs(tr.latest_backtest_mdd_pct) / 10) * 100);
    document.getElementById('bar-mdd').style.width = mddPct + '%';
    document.getElementById('bar-mdd-pct').textContent = fmt(tr.latest_backtest_mdd_pct) + '%';
  }
  if (health) {
    document.getElementById('mdl-age').textContent = health.model_age_days != null
      ? `${health.model_age_days} days ago` : (health.model_exists ? 'exists' : 'not trained');
  }

  // Instruments Data Summary — from model-eval-summary endpoint
  try {
    const evalData = await apiFetch('/api/v1/experience/rita/model-eval-summary');
    _renderInstrumentsTable(evalData);
  } catch (e) {
    setEl('ov-instruments-table', '---');
  }

  // Agent Build System — from agent-builds endpoint
  try {
    const buildsData = await apiFetch('/api/experience/ops/agent-builds');
    _renderAgentRuns(buildsData);
  } catch (e) {
    setEl('ov-agent-runs', '---');
  }
}

/* ── Private helpers ──────────────────────────────────────────────────────── */

function _renderInstrumentsTable(data) {
  if (!data || !data.rows || data.rows.length === 0) {
    setEl('ov-instruments-table', '<p>No instruments data available</p>');
    return;
  }
  const header = `<tr>
    <th>Instrument</th><th>Last Trained</th><th>Timesteps</th>
    <th>Val Sharpe</th><th>Val MDD%</th><th>BT Sharpe</th>
    <th>BT MDD%</th><th>BT Return%</th><th>Trades</th><th>Gate</th>
  </tr>`;
  const rows = data.rows.map(r => {
    let gateBadge;
    if (r.gate_pass === true) {
      gateBadge = badge('PASS', 'ok');
    } else if (r.gate_pass === false) {
      gateBadge = badge('BELOW GATE', 'warn');
    } else {
      gateBadge = badge('NO DATA', '');
    }
    return `<tr>
      <td>${r.instrument ?? '---'}</td>
      <td>${r.last_trained ?? '---'}</td>
      <td>${r.timesteps != null ? Number(r.timesteps).toLocaleString() : '---'}</td>
      <td>${r.val_sharpe != null ? fmt(r.val_sharpe) : '---'}</td>
      <td>${r.val_mdd_pct != null ? fmt(r.val_mdd_pct) : '---'}</td>
      <td>${r.backtest_sharpe != null ? fmt(r.backtest_sharpe) : '---'}</td>
      <td>${r.backtest_mdd_pct != null ? fmt(r.backtest_mdd_pct) : '---'}</td>
      <td>${r.backtest_return_pct != null ? fmt(r.backtest_return_pct) : '---'}</td>
      <td>${r.trade_count != null ? r.trade_count : '---'}</td>
      <td>${gateBadge}</td>
    </tr>`;
  }).join('');
  setEl('ov-instruments-table', `<table>${header}${rows}</table>`);
}

function _renderAgentRuns(data) {
  if (!data || !data.runs || data.runs.length === 0) {
    setEl('ov-agent-runs', '<p>No pipeline runs recorded</p>');
    return;
  }
  const recent = data.runs.slice(0, 5);
  const html = recent.map(run => {
    const date = _parseRunDate(run.run_id);
    const request = run.request
      ? (run.request.length > 80 ? run.request.slice(0, 80) + '...' : run.request)
      : 'Untitled run';
    const status = run.overall_status ?? 'unknown';
    const statusCls = status === 'completed' ? 'ok' : (status === 'failed' ? 'danger' : 'warn');
    const dur = run.duration_minutes != null ? fmt(run.duration_minutes, 0) + ' min' : '---';
    return `<div style="margin-bottom:6px">
      <span style="opacity:.6;font-size:.85em">${date}</span>
      <span style="margin-left:6px">${request}</span>
      <span style="margin-left:6px">${badge(status, statusCls)}</span>
      <span style="margin-left:6px;opacity:.7;font-size:.85em">${dur}</span>
    </div>`;
  }).join('');
  setEl('ov-agent-runs', html);
}

function _parseRunDate(runId) {
  if (!runId || runId.length < 13) return runId ?? '---';
  // Format: YYYYMMDD-HHMM...
  const y = runId.slice(0, 4);
  const m = runId.slice(4, 6);
  const d = runId.slice(6, 8);
  const hh = runId.slice(9, 11);
  const mm = runId.slice(11, 13);
  return `${y}-${m}-${d} ${hh}:${mm}`;
}
