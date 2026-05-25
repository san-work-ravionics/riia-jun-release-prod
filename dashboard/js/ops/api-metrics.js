import { apiFetch } from './api.js';
import { setEl } from './utils.js';

let _lastItems = [];

export async function loadApiMetrics() {
  const data = await apiFetch('/api/experience/ops/api-metrics');
  if (!data) {
    setEl('ops-api-metrics-total', '—');
    setEl('ops-api-metrics-unique', '—');
    setEl('ops-api-metrics-error-rate', '—');
    const emptyEl = document.getElementById('ops-api-metrics-empty');
    if (emptyEl) emptyEl.style.display = '';
    return;
  }
  _lastItems = data.items || [];
  renderMetrics(_lastItems);
}

export function filterApiMetrics() {
  const method = document.getElementById('ops-api-metrics-filter-method')?.value?.trim() || '';
  const prefix = document.getElementById('ops-api-metrics-filter-prefix')?.value?.trim() || '';
  let items = _lastItems;
  if (method) items = items.filter(r => r.method.toUpperCase() === method.toUpperCase());
  if (prefix) items = items.filter(r => r.path.startsWith(prefix));
  renderMetrics(items, true);
}

function renderMetrics(items, isFilter = false) {
  const totalCalls = items.reduce((s, r) => s + r.call_count, 0);
  const uniqueEndpoints = items.length;
  const totalErrors = items.reduce((s, r) => s + r.error_count, 0);
  const errorRate = totalCalls > 0 ? ((totalErrors / totalCalls) * 100).toFixed(1) : '0.0';

  setEl('ops-api-metrics-total', totalCalls);
  setEl('ops-api-metrics-unique', uniqueEndpoints);
  setEl('ops-api-metrics-error-rate', errorRate + '%');

  const emptyEl = document.getElementById('ops-api-metrics-empty');
  const tbody = document.getElementById('ops-api-metrics-tbody');

  if (!items.length) {
    if (emptyEl) emptyEl.style.display = '';
    if (tbody) tbody.innerHTML = '';
    return;
  }
  if (emptyEl) emptyEl.style.display = 'none';

  if (tbody) {
    tbody.innerHTML = items.map(r => `
      <tr>
        <td>${r.path}</td>
        <td>${r.method}</td>
        <td>${r.call_count}</td>
        <td>${r.p50_ms != null ? r.p50_ms.toFixed(1) : '—'}</td>
        <td>${r.p95_ms != null ? r.p95_ms.toFixed(1) : '—'}</td>
        <td>${r.error_count}</td>
        <td>${r.error_rate_pct.toFixed(1)}%</td>
        <td>${r.last_called_at ? new Date(r.last_called_at).toLocaleString() : '—'}</td>
      </tr>`).join('');
  }
}
