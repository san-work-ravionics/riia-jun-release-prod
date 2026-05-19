import { api } from './api.js';
import { DS_C, mkTbl } from './utils.js';

export async function loadModelObservability() {
  try {
    const [metrics, drift, stepLog] = await Promise.all([
      api('/api/experience/ops/metrics/summary').catch(() => ({})),
      api('/api/v1/drift').catch(() => null),
      api('/api/experience/ops/step-log').catch(() => []),
    ]);

    if (drift) {
      const h = (drift.summary && drift.summary.overall) || 'unknown';
      const badge = document.getElementById('mob-drift-badge');
      if (badge) { badge.className = 'badge ' + (h === 'ok' ? 'ok' : h === 'warn' ? 'warn' : 'err'); badge.textContent = h.toUpperCase(); }
      const r = drift.checks || {};
      document.getElementById('mob-drift-details').innerHTML = `
        <div style="display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--t2)">
          ${Object.entries(r).filter(([k, v]) => v && typeof v === 'object' && v.status).map(([k, v]) => `
            <div style="display:flex;justify-content:space-between;gap:8px">
              <span>${k.replace(/_/g, ' ')}</span>
              <span class="badge ${v.status === 'ok' ? 'ok' : 'warn'}">${v.status}</span>
            </div>`).join('')}
        </div>`;
    }

    const a = metrics.api_requests || {};
    document.getElementById('mob-api-stats').innerHTML = `
      <div style="display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--t2)">
        <div style="display:flex;justify-content:space-between"><span>Total requests</span><span style="font-family:var(--fm)">${a.total_requests != null ? a.total_requests : '—'}</span></div>
        <div style="display:flex;justify-content:space-between"><span>Avg latency</span><span style="font-family:var(--fm)">${a.avg_latency_ms != null ? Math.round(a.avg_latency_ms) + ' ms' : '—'}</span></div>
        <div style="display:flex;justify-content:space-between"><span>Error rate</span><span style="font-family:var(--fm)">${a.error_rate_pct != null ? a.error_rate_pct.toFixed(1) + '%' : '—'}</span></div>
        <div style="display:flex;justify-content:space-between"><span>Error count</span><span style="font-family:var(--fm)">${a.error_count != null ? a.error_count : '—'}</span></div>
      </div>`;

    const p = metrics.pipeline || {};
    const t = metrics.training || {};
    document.getElementById('mob-pipeline-stats').innerHTML = `
      <div style="display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--t2)">
        <div style="display:flex;justify-content:space-between"><span>Training rounds</span><span style="font-family:var(--fm)">${t.rounds != null ? t.rounds : '—'}</span></div>
        <div style="display:flex;justify-content:space-between"><span>Completed runs</span><span style="font-family:var(--fm)">${p.completed_steps != null ? p.completed_steps : '—'}</span></div>
        <div style="display:flex;justify-content:space-between"><span>Failed runs</span><span class="badge ${p.failed_steps ? 'err' : 'ok'}">${p.failed_steps != null ? p.failed_steps : 0}</span></div>
        ${t.latest_backtest_sharpe != null ? `<div style="display:flex;justify-content:space-between"><span>Latest Sharpe</span><span style="font-family:var(--fm)">${parseFloat(t.latest_backtest_sharpe).toFixed(3)}</span></div>` : ''}
      </div>`;

    if (stepLog && stepLog.length) {
      const recent = stepLog.slice(-30).reverse();
      document.getElementById('mob-step-log-wrap').innerHTML = mkTbl(recent, [
        { key: 'step_num', label: 'Step', mono: true },
        { key: 'step_name', label: 'Name' },
        { key: 'status', label: 'Status', badge: true },
        { key: 'started_at', label: 'Started', mono: true },
        { key: 'duration_secs', label: 'Duration (s)', mono: true, right: true },
        { key: 'summary', label: 'Summary' }
      ]);
    } else {
      document.getElementById('mob-step-log-wrap').innerHTML = '<div class="empty">No step log entries found.</div>';
    }
  } catch (e) {
    console.warn('model-observability error', e);
    document.getElementById('mob-step-log-wrap').innerHTML = `<div class="empty">Error loading observability data: ${e.message}</div>`;
  }
}
