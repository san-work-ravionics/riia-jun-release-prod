// ── Observability ──────────────────────────────────────────
import { api } from './api.js';
import { badge, setEl } from './utils.js';

export async function loadObservability() {
  try {
    const [metrics, drift, stepLog] = await Promise.all([
      api('/api/experience/ops/metrics/summary').catch(() => ({})),
      api('/api/v1/drift').catch(() => null),
      api('/api/experience/ops/step-log').catch(() => []),
    ]);

    // Drift report — API returns { summary: {overall}, checks: {...} }
    if (drift) {
      const h = (drift.summary && drift.summary.overall) || 'unknown';
      document.getElementById('drift-badge').className = 'badge ' + (h === 'ok' ? 'ok' : h === 'warn' ? 'warn' : 'err');
      setEl('drift-badge', h.toUpperCase());
      const r = drift.checks || {};
      setEl('drift-details', `
        <div style="display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--t2)">
          ${Object.entries(r).filter(([k, v]) => v && typeof v === 'object' && v.status).map(([k, v]) => `
            <div style="display:flex;justify-content:space-between;gap:8px">
              <span>${k.replace(/_/g, ' ')}</span>
              <span class="badge ${v.status === 'ok' ? 'ok' : 'warn'}">${v.status}</span>
            </div>`).join('')}
        </div>`);
    }

    // API stats
    const a = metrics.api_requests || {};
    setEl('api-stats', `
      <div style="display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--t2)">
        <div style="display:flex;justify-content:space-between"><span>Total requests</span><span style="font-family:var(--fm)">${a.total_requests != null ? a.total_requests : '—'}</span></div>
        <div style="display:flex;justify-content:space-between"><span>Avg latency</span><span style="font-family:var(--fm)">${a.avg_latency_ms != null ? Math.round(a.avg_latency_ms) + ' ms' : '—'}</span></div>
        <div style="display:flex;justify-content:space-between"><span>Error rate</span><span style="font-family:var(--fm)">${a.error_rate_pct != null ? a.error_rate_pct.toFixed(1) + '%' : '—'}</span></div>
        <div style="display:flex;justify-content:space-between"><span>Error count</span><span style="font-family:var(--fm)">${a.error_count != null ? a.error_count : '—'}</span></div>
      </div>`);

    // Pipeline stats
    const p = metrics.pipeline || {};
    const t = metrics.training || {};
    setEl('pipeline-stats', `
      <div style="display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--t2)">
        <div style="display:flex;justify-content:space-between"><span>Training rounds</span><span style="font-family:var(--fm)">${t.rounds != null ? t.rounds : '—'}</span></div>
        <div style="display:flex;justify-content:space-between"><span>Completed runs</span><span style="font-family:var(--fm)">${p.completed_steps != null ? p.completed_steps : '—'}</span></div>
        <div style="display:flex;justify-content:space-between"><span>Failed runs</span><span class="badge ${p.failed_steps ? 'err' : 'ok'}">${p.failed_steps != null ? p.failed_steps : 0}</span></div>
        ${t.latest_backtest_sharpe != null ? `<div style="display:flex;justify-content:space-between"><span>Latest Sharpe</span><span style="font-family:var(--fm)">${parseFloat(t.latest_backtest_sharpe).toFixed(3)}</span></div>` : ''}
      </div>`);

    // Step log table
    if (stepLog && stepLog.length) {
      const recent = stepLog.slice(-30).reverse();
      setEl('step-log-wrap', `
        <table>
          <thead><tr><th>Step</th><th>Name</th><th>Status</th><th>Started</th><th>Duration (s)</th><th>Summary</th></tr></thead>
          <tbody>${recent.map(r => `
            <tr>
              <td class="td-mono">${r.step_num || '—'}</td>
              <td>${r.step_name || '—'}</td>
              <td>${badge(r.status)}</td>
              <td class="td-mono" style="font-size:11px">${(r.started_at || '').slice(0, 19)}</td>
              <td class="td-mono">${r.duration_secs != null ? parseFloat(r.duration_secs).toFixed(2) : '—'}</td>
              <td style="font-size:11px;color:var(--t3)">${r.summary || '—'}</td>
            </tr>`).join('')}
          </tbody>
        </table>`);
    } else {
      setEl('step-log-wrap', '<div class="empty">No step log entries found.</div>');
    }
  } catch (e) {
    console.warn('observability error', e);
    setEl('step-log-wrap', `<div class="empty">Error loading observability data: ${e.message}</div>`);
  }
}
