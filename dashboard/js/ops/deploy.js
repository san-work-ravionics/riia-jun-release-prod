// ── Deployments ───────────────────────────────────────────────────────────────
import { apiFetch } from './api.js';
import { fmt, badge } from './utils.js';

export async function loadDeploy() {
  const [health, training] = await Promise.all([
    apiFetch('/health'),
    apiFetch('/api/v1/training-history'),
  ]);

  if (health) {
    document.getElementById('svc-api-badge').textContent = health.status === 'ok' ? 'online' : 'error';
    document.getElementById('svc-api-badge').className = 'badge ' + (health.status === 'ok' ? 'ok' : 'danger');
    const epEl = document.getElementById('svc-api-endpoint');
    if (epEl) epEl.textContent = window.RITA_API_BASE || window.location.origin;
    document.getElementById('svc-model-loaded').textContent = health.model_exists ? 'Yes' : 'No';
    document.getElementById('svc-model-age').textContent = health.model_age_days != null ? health.model_age_days + ' days' : '—';
    document.getElementById('svc-last-run').textContent = health.last_pipeline_run
      ? health.last_pipeline_run.slice(0, 16) : 'Never';
    document.getElementById('env-csv').textContent = health.output_dir ? health.output_dir + '/…' : '—';
    document.getElementById('env-output').textContent = health.output_dir ?? '—';
  }

  const trainEl = document.getElementById('deploy-training');
  if (training && training.length) {
    trainEl.innerHTML = `<table>
      <thead><tr><th>Round</th><th>Sharpe</th><th>MDD %</th><th>CAGR %</th><th>Constraints</th><th>Date</th></tr></thead>
      <tbody>${training.slice().reverse().slice(0,6).map(r => `<tr>
        <td style="font-family:var(--fm)">${r.round ?? '—'}</td>
        <td style="font-family:var(--fm)">${fmt(r.backtest_sharpe, 3)}</td>
        <td style="font-family:var(--fm)">${fmt(r.backtest_mdd_pct, 2)}</td>
        <td style="font-family:var(--fm)">${fmt(r.backtest_cagr_pct, 2)}</td>
        <td>${badge(r.backtest_constraints_met ? 'met' : 'failed', r.backtest_constraints_met ? 'ok' : 'warn')}</td>
        <td style="font-family:var(--fm);color:var(--t3)">${(r.trained_at || '').slice(0, 10)}</td>
      </tr>`).join('')}</tbody>
    </table>`;
  } else {
    trainEl.innerHTML = '<div class="empty">No training history yet — run a pipeline first</div>';
  }
}
