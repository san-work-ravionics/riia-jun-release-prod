// ── CI/CD ─────────────────────────────────────────────────────────────────────
import { apiFetch } from './api.js';
import { fmt, badge, stepName } from './utils.js';

export async function loadCICD() {
  const stepLog = await apiFetch('/api/experience/ops/step-log');
  const logEl = document.getElementById('cicd-steplog');
  if (stepLog && stepLog.length) {
    logEl.innerHTML = `<table>
      <thead><tr><th>Step</th><th>Name</th><th>Status</th><th>Duration</th><th>Ended</th></tr></thead>
      <tbody>${stepLog.slice().reverse().map(r => `<tr>
        <td>${r.step_num ?? '—'}</td>
        <td>${r.step_name ?? stepName(r.step_num)}</td>
        <td>${badge(r.status, r.status === 'completed' ? 'ok' : 'danger')}</td>
        <td style="font-family:var(--fm)">${fmt(r.duration_secs, 1)}s</td>
        <td style="font-family:var(--fm);color:var(--t3)">${(r.ended_at||'').slice(0,16)}</td>
      </tr>`).join('')}</tbody>
    </table>`;
  } else {
    logEl.innerHTML = '<div class="empty">No pipeline runs logged yet</div>';
  }
}
