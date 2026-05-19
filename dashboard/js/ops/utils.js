// ── Ops utilities (merged: formatting helpers + pipeline actions) ─────────────
import { api } from './api.js';

export { fmt, setEl } from '../shared/utils.js';

// Local two-argument badge — NOT the shared single-arg version
export function badge(text, cls) {
  return `<span class="badge ${cls}">${text}</span>`;
}

export function stepName(num) {
  const names = {1:'Set Goal',2:'Market Analysis',3:'Strategy',4:'Train Model',
                 5:'Set Period',6:'Backtest',7:'Results',8:'Update Goal'};
  return names[num] || ('Step ' + num);
}

// ── Pipeline action functions (formerly ops/utilities.js) ─────────────────────

function _inst() {
  return (localStorage.getItem('ritaInstrument') || 'NIFTY').toUpperCase();
}

function setStatus(msg, isError = false) {
  const el = document.getElementById('util-status');
  if (!el) return;
  el.textContent = msg;
  el.style.color = isError ? 'var(--danger)' : 'var(--build)';
  setTimeout(() => { el.textContent = ''; }, 5000);
}

export async function runGoal() {
  setStatus('Running goal…');
  try {
    await api('/api/v1/goal', 'POST', {
      target_return_pct: 15,
      time_horizon_days: 365,
      risk_tolerance: 'moderate',
      instrument: _inst(),
    });
    setStatus('Goal complete.');
  } catch (e) {
    setStatus('Error: ' + e.message, true);
  }
}

export async function runMarket() {
  setStatus('Analysing market…');
  try {
    await api('/api/v1/market', 'POST', { instrument: _inst() });
    setStatus('Market analysis complete.');
  } catch (e) {
    setStatus('Error: ' + e.message, true);
  }
}

export async function runStrategy() {
  setStatus('Running strategy…');
  try {
    await api('/api/v1/strategy', 'POST', { instrument: _inst() });
    setStatus('Strategy complete.');
  } catch (e) {
    setStatus('Error: ' + e.message, true);
  }
}

export async function runFullPipeline() {
  const btn = document.querySelector('[onclick="runFullPipeline()"]');
  if (btn) { btn.disabled = true; btn.textContent = 'Running…'; }
  setStatus('Running full pipeline…');
  try {
    await api('/api/v1/pipeline', 'POST', {
      target_return_pct: 15,
      time_horizon_days: 365,
      risk_tolerance: 'moderate',
      timesteps: 200000,
      force_retrain: false,
      instrument: _inst(),
    });
    setStatus('Pipeline complete.');
    alert('Pipeline complete! Check the ds.html Training Progress and Audit sections.');
  } catch (e) {
    setStatus('Error: ' + e.message, true);
    alert('Pipeline error: ' + e.message);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Run Full Pipeline'; }
  }
}

export async function doReset() {
  if (!confirm('Reset session? This clears in-memory state but keeps saved model files.')) return;
  setStatus('Resetting…');
  try {
    await api('/reset', 'POST');
    setStatus('Reset complete.');
  } catch (e) {
    setStatus('Error: ' + e.message, true);
  }
}

export function loadUtilities() {
  // No async data load needed — buttons are static HTML rendered in ops.html
}
