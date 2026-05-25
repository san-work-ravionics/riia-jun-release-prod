// ── Monitoring ────────────────────────────────────────────────────────────────
import { apiFetch } from './api.js';
import { fmt, badge } from './utils.js';
import { loadApiMetrics } from './api-metrics.js';

export async function loadMonitoring() {
  const [metrics, deploys] = await Promise.all([
    apiFetch('/api/experience/ops/metrics/summary'),
    apiFetch('/api/experience/ops/github-deploys'),
  ]);

  const el = id => document.getElementById(id);

  if (metrics) {
    const req = metrics.api_requests || {};
    const pipe = metrics.pipeline || {};

    if (el('mon-total'))     el('mon-total').textContent     = req.total_requests ?? '—';
    if (el('mon-errors'))    el('mon-errors').textContent    = req.error_count ?? '—';
    if (el('mon-ips'))       el('mon-ips').textContent       = req.avg_latency_ms != null ? req.avg_latency_ms.toFixed(0) + ' ms' : '—';
    if (el('mon-completed')) el('mon-completed').textContent = pipe.completed_steps ?? '—';
    if (el('mon-failed'))    el('mon-failed').textContent    = pipe.failed_steps ?? '—';
    if (el('mon-rounds'))    el('mon-rounds').textContent    = (metrics.training || {}).rounds ?? '—';

    // Top endpoint
    const topEps = req.endpoints || {};
    const topKeys = Object.keys(topEps).sort((a,b) => (topEps[b].count||0) - (topEps[a].count||0));
    if (topKeys.length) {
      const topK = topKeys[0];
      if (el('mon-top-ep'))  el('mon-top-ep').textContent  = topK;
      if (el('mon-top-cnt')) el('mon-top-cnt').textContent = (topEps[topK].count || '—') + ' requests';
    }

    // Inline alerts
    const alertEl = el('mon-alerts');
    if (alertEl) {
      const alerts = [];
      if (req.error_rate_pct > 5) {
        alerts.push({cls:'w', msg: `Error rate ${req.error_rate_pct.toFixed(1)}% — above 5% threshold`});
      }
      if (pipe.failed_steps > 0) {
        alerts.push({cls:'w', msg: `${pipe.failed_steps} pipeline step(s) failed`});
      }
      if (alerts.length === 0) {
        alerts.push({cls:'ok', msg: 'All metrics within normal ranges'});
      }
      alertEl.innerHTML = alerts.map(a => {
        const icon = a.cls === 'ok'
          ? '<path d="M2.5 7l3 3 5-5.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>'
          : '<path d="M6.5 4v4M6.5 9.5h.01" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>';
        return `<div class="al ${a.cls}"><svg class="al-ic" width="13" height="13" viewBox="0 0 13 13" fill="none">${icon}</svg>${a.msg}</div>`;
      }).join('');
    }
  }

  // GitHub Deploys table
  const ghEl = el('mon-github-deploys');
  if (ghEl) {
    if (deploys && deploys.runs && deploys.runs.length) {
      ghEl.innerHTML = `<table>
        <thead><tr><th>Commit</th><th>SHA</th><th>Status</th><th>Duration</th><th>Deployed</th></tr></thead>
        <tbody>${deploys.runs.map(r => {
          const ok   = r.conclusion === 'success';
          const mins = r.duration_sec != null ? Math.floor(r.duration_sec / 60) : null;
          const secs = r.duration_sec != null ? r.duration_sec % 60 : null;
          const dur  = mins != null ? `${mins}m ${secs}s` : '—';
          const ts   = (r.created_at || '').slice(0, 16).replace('T', ' ');
          return `<tr>
            <td style="max-width:320px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${r.commit_message || ''}">${r.commit_message || '—'}</td>
            <td style="font-family:var(--fm);color:var(--t3)">${r.commit_sha || '—'}</td>
            <td>${badge(r.conclusion || r.status, ok ? 'ok' : (r.conclusion === 'failure' ? 'danger' : 'warn'))}</td>
            <td style="font-family:var(--fm)">${dur}</td>
            <td style="font-family:var(--fm);color:var(--t3)">${ts}</td>
          </tr>`;
        }).join('')}</tbody>
      </table>`;
    } else if (deploys && deploys.error) {
      ghEl.innerHTML = `<div class="empty">GitHub API unavailable — ${deploys.error}</div>`;
    } else {
      ghEl.innerHTML = '<div class="empty">No deploy runs found</div>';
    }
  }

  loadApiMetrics();
}
