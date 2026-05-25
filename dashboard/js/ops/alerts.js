// ── Active Alerts ─────────────────────────────────────────────────────────────
import { badge } from './utils.js';

export async function loadAlerts() {
  const badgeEl = document.getElementById('alerts-badge');
  const tableEl = document.getElementById('alerts-table');

  try {
    const res = await fetch('/api/experience/ops/aws-alerts');
    const data = res.ok ? await res.json() : null;

    if (!data || !Array.isArray(data.alerts)) {
      if (badgeEl) badgeEl.innerHTML = '<span style="color:var(--t3)">Unavailable</span>';
      if (tableEl) tableEl.innerHTML = '<tr><td colspan="5" class="empty">Alert data unavailable</td></tr>';
      return;
    }

    const active = data.alerts.filter(a => a.status === 'active');
    const critical = active.filter(a => (a.severity || '').toLowerCase() === 'critical').length;
    const warning  = active.filter(a => (a.severity || '').toLowerCase() === 'warning').length;

    if (badgeEl) {
      if (active.length === 0) {
        badgeEl.innerHTML = '<span style="color:var(--t3)">0 Critical &nbsp; 0 Warning</span>';
      } else {
        const critStyle = critical > 0 ? 'color:#ef4444;font-weight:600' : 'color:var(--t3)';
        const warnStyle = warning  > 0 ? 'color:#f59e0b;font-weight:600' : 'color:var(--t3)';
        badgeEl.innerHTML =
          `<span style="${critStyle}">${critical} Critical</span>&nbsp;&nbsp;` +
          `<span style="${warnStyle}">${warning} Warning</span>`;
      }
    }

    if (tableEl) {
      if (active.length === 0) {
        tableEl.innerHTML = '<tr><td colspan="5" class="empty">All systems nominal</td></tr>';
      } else {
        tableEl.innerHTML = active.map(a => {
          const sev = (a.severity || 'unknown').toLowerCase();
          const sevStyle = sev === 'critical' ? 'color:#ef4444;font-weight:600'
                         : sev === 'warning'  ? 'color:#f59e0b;font-weight:600'
                         : 'color:var(--t3)';
          return `<tr>
            <td style="${sevStyle}">${a.severity ?? '—'}</td>
            <td style="font-family:var(--fm)">${a.rule ?? '—'}</td>
            <td>${a.component ?? '—'}</td>
            <td>${a.message ?? '—'}</td>
            <td style="font-family:var(--fm);color:var(--t3)">${(a.since || '').slice(0, 16)}</td>
          </tr>`;
        }).join('');
      }
    }
  } catch (e) {
    console.error('[RITA] loadAlerts failed', e);
    if (badgeEl) badgeEl.innerHTML = '<span style="color:var(--t3)">Unavailable</span>';
    if (tableEl) tableEl.innerHTML = '<tr><td colspan="5" class="empty">Alert data unavailable</td></tr>';
  }
}
