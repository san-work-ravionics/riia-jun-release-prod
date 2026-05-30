// ── Export & DevOps ────────────────────────────────────────
import { api } from './api.js';
import { setEl } from './utils.js';
import { renderGoalResult, renderMarketResult, renderStepResult } from './pipeline.js';
import { loadProgress } from './health.js';
import { showStrategyCommentary } from './commentary.js';

export async function loadExport() {
  try {
    const d = await api('/health');
    setEl('sys-info', `
      <div style="display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--t2)">
        <div style="display:flex;justify-content:space-between"><span>API version</span><span style="font-family:var(--fm)">0.2.0</span></div>
        <div style="display:flex;justify-content:space-between"><span>Status</span><span class="badge ok">${d.status}</span></div>
        <div style="display:flex;justify-content:space-between"><span>Timestamp</span><span style="font-family:var(--fm);font-size:11px">${d.timestamp}</span></div>
        <div style="display:flex;justify-content:space-between"><span>Model age</span><span style="font-family:var(--fm)">${d.model_age_days != null ? d.model_age_days + 'd' : '—'}</span></div>
        <div style="display:flex;justify-content:space-between"><span>Output dir</span><span style="font-family:var(--fm);font-size:11px">${d.output_dir}</span></div>
      </div>`);
  } catch (e) { }
}

// ── Pipeline step actions ──────────────────────────────────
function _inst() { return (localStorage.getItem('ritaInstrument') || 'NIFTY').toUpperCase(); }

export async function runGoal() {
  const btn = document.getElementById('btn-goal');
  btn.disabled = true; btn.textContent = 'Running...';
  setEl('goal-status-badge', 'Running'); document.getElementById('goal-status-badge').className = 'badge run';
  try {
    const d = await api('/api/v1/goal', 'POST', {
      target_return_pct: parseFloat(document.getElementById('inp-target').value),
      time_horizon_days: parseInt(document.getElementById('inp-horizon').value),
      risk_tolerance: document.querySelector('input[name="inp-risk"]:checked')?.value || 'moderate',
      instrument: _inst(),
    });
    document.getElementById('goal-status-badge').className = 'badge ok';
    setEl('goal-status-badge', 'Done');
    renderGoalResult('goal-result', d);
  } catch (e) {
    document.getElementById('goal-status-badge').className = 'badge err';
    setEl('goal-status-badge', 'Error');
    setEl('goal-result', `<div class="result-panel"><div style="color:var(--danger);font-size:12px">Error: ${e.message}</div></div>`);
  } finally {
    btn.disabled = false; btn.textContent = 'Set Goal →';
    loadProgress();
  }
}

export async function runMarket() {
  const bdg = document.getElementById('market-status-badge');
  if (bdg) { bdg.className = 'badge run'; bdg.textContent = 'Loading'; }
  try {
    const d = await api('/api/v1/market', 'POST', { instrument: _inst() });
    if (bdg) { bdg.className = 'badge ok'; bdg.textContent = 'Done'; }
    renderMarketResult(d);
  } catch (e) {
    if (bdg) { bdg.className = 'badge err'; bdg.textContent = 'Error'; }
  } finally {
    loadProgress();
  }
}

export async function runStrategy() {
  const btn = document.getElementById('btn-strategy');
  btn.disabled = true; btn.textContent = 'Running...';
  document.getElementById('strategy-status-badge').className = 'badge run';

  const instrument = _inst();

  // Fire commentary and strategy concurrently; strategy grid always renders
  const [commentaryResult, strategyResult] = await Promise.allSettled([
    api('/api/v1/commentary', 'POST', { app: 'rita', page: 'strategy', instrument }),
    api('/api/v1/strategy', 'POST', { instrument }),
  ]);

  // Show commentary before result grid — shows '—' on failure
  try {
    const commentaryText =
      commentaryResult.status === 'fulfilled' && commentaryResult.value?.commentary
        ? commentaryResult.value.commentary
        : '—';
    showStrategyCommentary(commentaryText);
  } catch (_) {
    showStrategyCommentary('—');
  }

  // Strategy result always renders regardless of commentary outcome
  try {
    if (strategyResult.status === 'fulfilled') {
      document.getElementById('strategy-status-badge').className = 'badge ok';
      setEl('strategy-status-badge', 'Done');
      renderStepResult('strategy-result', strategyResult.value);
    } else {
      throw strategyResult.reason;
    }
  } catch (e) {
    document.getElementById('strategy-status-badge').className = 'badge err';
    setEl('strategy-status-badge', 'Error');
    setEl('strategy-result', `<div class="card"><div style="color:var(--danger);font-size:12px">Error: ${e.message}</div></div>`);
  } finally {
    btn.disabled = false; btn.textContent = 'Design Strategy';
    loadProgress();
  }
}

export async function runFullPipeline() {
  const btn = document.querySelector('[onclick="runFullPipeline()"]');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Running...'; }
  try {
    await api('/api/v1/pipeline', 'POST', {
      target_return_pct: 15, time_horizon_days: 365,
      risk_tolerance: 'moderate', timesteps: 200000, force_retrain: false,
      instrument: _inst(),
    });
    await window._ritaRefresh();
    alert('Pipeline complete! Explore Performance and Risk tabs.');
  } catch (e) {
    alert('Pipeline error: ' + e.message);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '▶ Run Pipeline'; }
  }
}

export async function doReset() {
  if (!confirm('Reset session? This clears in-memory state but keeps saved model files.')) return;
  await api('/reset', 'POST');
  await window._ritaRefresh();
}
