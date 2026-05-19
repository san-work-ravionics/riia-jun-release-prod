// ── Overview ──────────────────────────────────────────────────────────────────
import { apiFetch } from './api.js';
import { fmt, badge, stepName } from './utils.js';

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
    txt.textContent = health.model_exists ? 'Model loaded' : 'API online';
  } else {
    dot.className = 'status-dot danger';
    txt.textContent = 'API offline';
  }

  // KPI strip
  const apiOk = health && health.status === 'ok';
  document.getElementById('kpi-status').textContent = apiOk ? 'Online' : 'Offline';
  document.getElementById('kpi-status').className = 'kpi-val ' + (apiOk ? 'ok' : 'danger');
  document.getElementById('kpi-status-sub').textContent = apiOk ? 'All systems nominal' : 'API unreachable';

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

    // Sidebar footer
    const allDone = completedCount >= total;
    document.getElementById('mc-status-text').textContent = allDone ? 'Pipeline Complete' : `${completedCount}/${total} Steps Done`;
    document.getElementById('mc-steps').textContent = `${completedCount} / ${total}`;
    document.getElementById('mc-bar').style.width = pctComplete + '%';
  }

  if (health) {
    document.getElementById('mc-model').textContent = health.model_exists
      ? (health.model_age_days != null ? `${health.model_age_days}d old` : 'exists')
      : 'not trained';
    document.getElementById('mc-model').className = 'mc-v ' + (health.model_exists ? 'ok' : 'warn');
    document.getElementById('mc-lastrun').textContent = health.last_pipeline_run
      ? health.last_pipeline_run.slice(0, 16) : 'never';
  }

  // Model card
  if (metrics && metrics.training && Object.keys(metrics.training).length) {
    const t = metrics.training;
    document.getElementById('mdl-sharpe').textContent = fmt(t.latest_backtest_sharpe);
    document.getElementById('mdl-mdd').textContent = fmt(t.latest_backtest_mdd_pct) + '%';
    document.getElementById('mdl-cagr').textContent = fmt(t.latest_backtest_cagr_pct) + '%';
    if (t.backtest_start_date && t.backtest_end_date) {
      document.getElementById('mdl-bt-range').textContent = `${t.backtest_start_date} → ${t.backtest_end_date}`;
    }

    const sharpePct = Math.min(100, (t.latest_backtest_sharpe / 1.5) * 100);
    document.getElementById('bar-sharpe').style.width = sharpePct + '%';
    document.getElementById('bar-sharpe-pct').textContent = fmt(t.latest_backtest_sharpe, 3);

    const mddPct = Math.max(0, 100 - (Math.abs(t.latest_backtest_mdd_pct) / 10) * 100);
    document.getElementById('bar-mdd').style.width = mddPct + '%';
    document.getElementById('bar-mdd-pct').textContent = fmt(t.latest_backtest_mdd_pct) + '%';
  }
  if (health) {
    document.getElementById('mdl-age').textContent = health.model_age_days != null
      ? `${health.model_age_days} days ago` : (health.model_exists ? 'exists' : 'not trained');
  }

  // Dataset card — derived from /health (data_freshness + csv_loaded)
  if (health) {
    const fresh = health.data_freshness || {};
    const daysOld = fresh.days_since_latest;
    const latestDate = fresh.latest_date ?? '—';

    const totalRows = fresh.total_rows;
    document.getElementById('ds-rows').textContent = totalRows != null && totalRows > 0 ? totalRows.toLocaleString() : '—';
    document.getElementById('ds-fresh').textContent = daysOld != null ? daysOld + 'd' : '—';
    document.getElementById('ds-fresh').style.color = daysOld != null && daysOld > 7 ? 'var(--warn)' : 'var(--ok)';
    document.getElementById('ds-range-text').textContent = `— → ${latestDate}`;

    const extAl = document.getElementById('ds-extended-al');
    if (health.csv_loaded) {
      extAl.innerHTML = `<div class="al ok" style="margin-top:0"><svg class="al-ic" width="13" height="13" viewBox="0 0 13 13" fill="none"><path d="M2.5 7l3 3 5-5.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>CSV data loaded — rita_input/ has source files</div>`;
    } else {
      extAl.innerHTML = `<div class="al i" style="margin-top:0"><svg class="al-ic" width="13" height="13" viewBox="0 0 13 13" fill="none"><circle cx="6.5" cy="6.5" r="5.5" stroke="currentColor" stroke-width="1.2"/><path d="M6.5 4v3M6.5 9h.01" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>No CSV files found in rita_input/ — add NSE data files to enable</div>`;
    }
  }

  // Recent activity from step log
  const stepLog = await apiFetch('/api/experience/ops/step-log');
  const actEl = document.getElementById('overview-activity');
  if (stepLog && stepLog.length) {
    const recent = stepLog.slice(-4).reverse();
    actEl.innerHTML = recent.map((row, i) => {
      const isLast = i === recent.length - 1;
      const isOk = row.status === 'completed';
      const dotColor = isOk ? 'var(--ok)' : 'var(--danger)';
      return `<div class="act-row">
        <div class="act-dot-wrap">
          <div class="act-dot" style="background:${dotColor}"></div>
          ${!isLast ? '<div class="act-line"></div>' : ''}
        </div>
        <div class="act-body">
          <div class="act-title">Step ${row.step_num ?? '?'}: ${row.step_name ?? stepName(row.step_num)} ${badge(row.status, isOk ? 'ok' : 'danger')}</div>
          <div class="act-desc">${fmt(row.duration_secs, 1)}s</div>
        </div>
        <div class="act-time">${(row.ended_at || row.started_at || '').slice(0, 16)}</div>
      </div>`;
    }).join('');
  } else {
    actEl.innerHTML = '<div class="empty">No pipeline steps logged yet</div>';
  }
}
