// ── Observability ─────────────────────────────────────────────────────────────
import { apiFetch } from './api.js';
import { fmt, badge } from './utils.js';

export async function loadObservability() {
  const [drift, mcp, health] = await Promise.all([
    apiFetch('/api/v1/drift'),
    apiFetch('/api/v1/mcp-calls'),
    apiFetch('/health'),
  ]);

  const alertEl = document.getElementById('drift-alerts');
  const checksEl = document.getElementById('drift-checks');

  if (drift) {
    const overall = drift.summary?.overall ?? 'unknown';
    const alertCls = overall === 'ok' ? 'ok' : overall === 'warn' ? 'w' : overall === 'alert' ? 'd' : 'i';
    alertEl.innerHTML = `<div class="al ${alertCls}">
      <svg class="al-ic" width="13" height="13" viewBox="0 0 13 13" fill="none">
        ${alertCls === 'ok'
          ? '<path d="M2.5 7l3 3 5-5.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>'
          : '<path d="M6.5 3v4M6.5 9.5h.01" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>'}
      </svg>
      Overall system health: <strong>${overall.toUpperCase()}</strong>
    </div>`;

    const report = drift.checks || {};
    const checkOrder = ['sharpe_drift','return_degradation','data_freshness','pipeline_health','constraint_breach'];
    const checkLabels = {sharpe_drift:'Sharpe Drift',return_degradation:'Return Degradation',
      data_freshness:'Data Freshness',pipeline_health:'Pipeline Health',constraint_breach:'Constraint Breach'};
    const cells = checkOrder.map(key => {
      const val = report[key] || {};
      const st = val.status ?? 'unknown';
      const cls = st === 'ok' ? 'ok' : st === 'warn' ? 'warn' : st === 'alert' ? 'danger' : 'unknown';
      const msg = val.message ?? '';
      return `<div class="drift-cell ${cls}">
        <div class="drift-cell-name">${checkLabels[key]}</div>
        <div class="drift-cell-status ${cls}">${st.toUpperCase()}</div>
        <div class="drift-cell-msg">${msg}</div>
      </div>`;
    });
    checksEl.innerHTML = cells.length ? cells.join('') : `<div class="empty" style="grid-column:span 5">No drift checks available</div>`;

    const freshEl = document.getElementById('freshness-content');
    const fresh = report.data_freshness || {};
    freshEl.innerHTML = `
      <div class="svc-row"><span>Days since last data</span><span class="svc-val">${fresh.days_old ?? '—'} days</span></div>
      <div class="svc-row"><span>Latest date in CSV</span><span class="svc-val" style="font-family:var(--fm)">${fresh.latest_date ?? '—'}</span></div>
      <div class="svc-row"><span>Status</span><span class="svc-val">${badge(fresh.status ?? '—', fresh.status === 'ok' ? 'ok' : fresh.status === 'warn' ? 'warn' : 'danger')}</span></div>
      ${fresh.message ? `<div class="al ${fresh.status === 'ok' ? 'ok' : 'w'}" style="margin-top:10px;margin-bottom:0">
        <svg class="al-ic" width="13" height="13" viewBox="0 0 13 13" fill="none"><circle cx="6.5" cy="6.5" r="5.5" stroke="currentColor" stroke-width="1.2"/><path d="M6.5 4v3M6.5 9h.01" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>
        ${fresh.message}
      </div>` : ''}
    `;

    const trendEl = document.getElementById('sharpe-trend');
    const trend = health && health.sharpe_trend_last5 || [];
    if (trend.length) {
      const max = Math.max(...trend) || 1;
      trendEl.innerHTML = trend.map((v, i) => `
        <div class="bar-r">
          <span class="bar-lbl">Run ${trend.length - trend.length + i + 1}</span>
          <div class="bar-track"><div class="bar-fill" style="width:${(v/max*100).toFixed(1)}%;background:${v >= 1 ? 'var(--ok)' : 'var(--warn)'}"></div></div>
          <span class="bar-pct">${fmt(v, 3)}</span>
        </div>`).join('');
    } else {
      trendEl.innerHTML = '<div class="empty">No training history yet</div>';
    }
  } else {
    alertEl.innerHTML = '<div class="al w"><svg class="al-ic" width="13" height="13" viewBox="0 0 13 13" fill="none"><path d="M6.5 3v4M6.5 9.5h.01" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>Drift data unavailable — run a pipeline first</div>';
    checksEl.innerHTML = '';
    document.getElementById('freshness-content').innerHTML = '<div class="empty">No data</div>';
    document.getElementById('sharpe-trend').innerHTML = '<div class="empty">No data</div>';
  }

  const mcpEl = document.getElementById('obs-mcp');
  if (mcp && mcp.length) {
    mcpEl.innerHTML = `<table>
      <thead><tr><th>Tool</th><th>Duration (ms)</th><th>Status</th><th>Called At</th></tr></thead>
      <tbody>${mcp.slice().reverse().slice(0, 50).map(r => `<tr>
        <td style="font-family:var(--fm)">${r.tool_name ?? '—'}</td>
        <td style="font-family:var(--fm)">${r.duration_ms != null ? Number(r.duration_ms).toFixed(0) : '—'}</td>
        <td>${badge(r.status ?? 'ok', r.status === 'ok' ? 'ok' : 'danger')}</td>
        <td style="font-family:var(--fm);color:var(--t3)">${(r.called_at || '').slice(0, 16)}</td>
      </tr>`).join('')}</tbody>
    </table>`;
  } else {
    mcpEl.innerHTML = '<div class="empty">No MCP calls logged yet</div>';
  }
}
