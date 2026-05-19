// ── Sidebar refresh ───────────────────────────────────────────────────────────
import { apiFetch } from './api.js';

export async function refreshSidebar() {
  const [progress, health] = await Promise.all([
    apiFetch('/progress'),
    apiFetch('/health'),
  ]);
  if (progress) {
    const allDone = progress.steps_completed >= 8;
    document.getElementById('mc-status-text').textContent = allDone ? 'Pipeline Complete' : `${progress.steps_completed}/8 Steps Done`;
    document.getElementById('mc-steps').textContent = progress.steps_completed + ' / 8';
    document.getElementById('mc-bar').style.width = progress.pct_complete + '%';
  }
  if (health) {
    document.getElementById('mc-model').textContent = health.model_exists
      ? (health.model_age_days != null ? `${health.model_age_days}d old` : 'exists')
      : 'not trained';
    document.getElementById('mc-model').className = 'mc-v ' + (health.model_exists ? 'ok' : 'warn');
    document.getElementById('mc-lastrun').textContent = health.last_pipeline_run
      ? health.last_pipeline_run.slice(0, 16) : 'never';
  }
}
