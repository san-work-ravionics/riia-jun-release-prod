// ── Monitoring ────────────────────────────────────────────────────────────────
import { apiFetch } from './api.js';
import { fmt, badge, stepName } from './utils.js';

export async function loadMonitoring() {
  const [metrics, stepLog] = await Promise.all([
    apiFetch('/api/experience/ops/metrics/summary'),
    apiFetch('/api/experience/ops/step-log'),
  ]);

  if (metrics) {
    const req = metrics.api_requests || {};
    document.getElementById('mon-total').textContent = req.total_requests ?? '—';
    document.getElementById('mon-errors').textContent = req.error_count ?? '—';
    document.getElementById('mon-ips').textContent = req.avg_latency_ms != null ? req.avg_latency_ms.toFixed(0) + ' ms avg' : '—';

    // Top endpoint
    const topEps = req.endpoints || {};
    const topKeys = Object.keys(topEps).sort((a,b) => (topEps[b].count||0) - (topEps[a].count||0));
    if (topKeys.length) {
      const topK = topKeys[0];
      document.getElementById('mon-top-ep').textContent = topK;
      document.getElementById('mon-top-cnt').textContent = (topEps[topK].count || '—') + ' requests';
    }

    const pipe = metrics.pipeline || {};
    document.getElementById('mon-completed').textContent = pipe.completed_steps ?? '—';
    document.getElementById('mon-failed').textContent = pipe.failed_steps ?? '—';
    document.getElementById('mon-rounds').textContent = (metrics.training || {}).rounds ?? '—';

    // Step timing bars
    const timingEl = document.getElementById('mon-timing');
    const timing = pipe.step_timing || {};
    if (Object.keys(timing).length) {
      const maxAvg = Math.max(...Object.values(timing).map(v => v.mean || 0)) || 1;
      timingEl.innerHTML = Object.entries(timing).map(([step, v]) => {
        const pct = ((v.mean || 0) / maxAvg * 100).toFixed(1);
        return `<div class="bar-r">
          <span class="bar-lbl">${stepName(step)}</span>
          <div class="bar-track"><div class="bar-fill" style="width:${pct}%;background:var(--sense)"></div></div>
          <span class="bar-pct">${fmt(v.mean, 1)}s</span>
        </div>`;
      }).join('');
    } else {
      timingEl.innerHTML = '<div class="empty">No timing data yet</div>';
    }

    // Alerts
    const alertEl = document.getElementById('mon-alerts');
    let alerts = [];
    if (req.error_rate_pct > 5) {
      alerts.push({cls:'w', msg: `Error rate is ${req.error_rate_pct.toFixed(1)}% — above 5% threshold`});
    }
    if (pipe.failed_steps > 0) {
      alerts.push({cls:'w', msg: `${pipe.failed_steps} pipeline step(s) have failed — check step log`});
    }
    if (alerts.length === 0) {
      alerts.push({cls:'ok', msg: 'All metrics within normal ranges'});
    }
    alertEl.innerHTML = alerts.map(a => `<div class="al ${a.cls}">
      <svg class="al-ic" width="13" height="13" viewBox="0 0 13 13" fill="none">
        ${a.cls === 'ok'
          ? '<path d="M2.5 7l3 3 5-5.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>'
          : '<path d="M6.5 4v4M6.5 9.5h.01" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>'}
      </svg>${a.msg}</div>`).join('');
  }

  // Step log table
  const logEl = document.getElementById('mon-steplog');
  if (stepLog && stepLog.length) {
    logEl.innerHTML = `<table>
      <thead><tr><th>Step</th><th>Name</th><th>Status</th><th>Duration</th><th>Started</th></tr></thead>
      <tbody>${stepLog.slice(-20).reverse().map(r => `<tr>
        <td>${r.step_num ?? '—'}</td>
        <td>${r.step_name ?? stepName(r.step_num)}</td>
        <td>${badge(r.status, r.status === 'completed' ? 'ok' : 'danger')}</td>
        <td style="font-family:var(--fm)">${fmt(r.duration_secs, 1)}s</td>
        <td style="font-family:var(--fm);color:var(--t3)">${(r.started_at||'').slice(0,16)}</td>
      </tr>`).join('')}</tbody>
    </table>`;
  } else {
    logEl.innerHTML = '<div class="empty">No step log entries yet</div>';
  }
}
