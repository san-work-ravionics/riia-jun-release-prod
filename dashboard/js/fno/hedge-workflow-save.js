// ── Hedge Workflow — Save step + autosave (F39 Phase 3) ──────────────────────
// Save step: summary of the chosen hedge, explicit Save (PUT hedge-plan with
// last_step:'save'), and history (the current saved plan as one row + the global
// Manoeuvre hedge-action log). Also owns the shared 400ms debounced autosave used
// by the Recommendation / What-if modules.
//
// History is "latest save only" (user decision D1, Option A): UserHedgePlanModel is
// one row per user, so there is no per-save history and the per-instrument strategy
// choice (state.hedgeWorkflow.selections) is not persisted across reloads.

import { api, apiFetch } from './api.js';
import { setEl } from '../shared/utils.js';
import { state } from './state.js';

const _SAVE_DEBOUNCE_MS = 400;
let _saveTimer = null;
let _saveToken = 0;

export const TAB_LABELS = { pp: 'Protective put', ps: 'Put spread', collar: 'Collar' };
export const STRATEGY_LABELS = { put_buy: 'Protective put', call_sell: 'Covered call' };

export function authHeaders() {
  const token = sessionStorage.getItem('auth_token');
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function _hw() { return state.hedgeWorkflow; }

function _planBody(lastStep) {
  const hw = _hw();
  const known = new Set((hw.portfolioHoldings || []).map((h) => h.instrument_id));
  // Stale ids (no longer in the portfolio) are dropped; before exposure data has
  // loaded (known empty) the in-memory ids are sent as-is.
  const ids = known.size ? hw.hedgedIds.filter((id) => known.has(id)) : [...hw.hedgedIds];
  return {
    hedged_ids: ids,
    coverage: hw.coverage,
    scenario_tab: hw.scenarioTab || 'pp',
    last_step: lastStep,
  };
}

// User changed coverage / hedged set / tab: flag dirty and queue the autosave.
export function hwMarkDirty() {
  const hw = _hw();
  hw.dirty = true;
  if (hw.saveStatus === 'saved') hw.saveStatus = 'idle';
  hwScheduleSave();
}

// Shared debounced PUT (400ms). Autosave never sets the 'saved' status.
export function hwScheduleSave() {
  clearTimeout(_saveTimer);
  _saveTimer = setTimeout(_autosave, _SAVE_DEBOUNCE_MS);
}

async function _autosave() {
  const hw = _hw();
  if (hw.saveStatus === 'saving') return;
  try {
    // Entering the Save step must not itself count as "Saved": only an explicit
    // hwSave() writes last_step:'save'.
    const step = hw.step === 'save' ? 'whatif' : hw.step;
    const res = await api('/api/v1/experience/fno/hedge-plan', 'PUT', _planBody(step));
    if (res) hw.savedPlan = res;
    hw.dirty = false;
  } catch (e) {
    console.warn('[hedge-workflow] autosave failed', e);
  }
}

// ── window.hwSave() — explicit Save ─────────────────────────────────────────
export async function hwSave() {
  const hw = _hw();
  if (hw.saveStatus === 'saving') return;
  clearTimeout(_saveTimer);
  hw.saveStatus = 'saving';
  _renderSaveStatus();
  try {
    const res = await api('/api/v1/experience/fno/hedge-plan', 'PUT', _planBody('save'));
    if (!res) throw new Error('Not signed in or no response');
    hw.savedPlan = res;
    hw.history = { ...hw.history, plan: res };
    hw.saveStatus = 'saved';
    hw.savedAt = res.updated_at || new Date().toISOString();
    hw.dirty = false;
  } catch (e) {
    console.warn('[hedge-workflow] save failed', e);
    hw.saveStatus = 'error';
    hw.saveError = e?.message || 'Save failed';
  }
  _renderSaveStatus();
  _renderHistoryTable();
}

// ── Rendering ────────────────────────────────────────────────────────────────
function _fmtDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? String(iso) : d.toLocaleString();
}

function _noHoldingsCta() {
  return `<div class="kpi-sub">No holdings yet — build a portfolio first.</div>
    <button onclick="document.querySelector('.nav-item[data-page=\\'equity-scenarios\\']')?.click()"
      style="margin-top:8px;padding:6px 16px;border:none;border-radius:6px;background:var(--p03);color:#fff;font-family:var(--fm);font-size:12px;font-weight:600;cursor:pointer">
      Go to Portfolio Builder
    </button>`;
}

function _renderSummary() {
  const hw = _hw();
  const noHoldings = !(hw.portfolioHoldings || []).length;
  const btn = document.getElementById('hw-save-btn');
  if (btn) btn.disabled = noHoldings || hw.saveStatus === 'saving';
  if (noHoldings) {
    setEl('hw-save-summary', _noHoldingsCta());
    return;
  }
  const known = new Set(hw.portfolioHoldings.map((h) => h.instrument_id));
  const hedged = hw.hedgedIds.filter((id) => known.has(id));
  const rows = hedged.length
    ? hedged
        .map((id) => `<tr><td>${id}</td><td>${STRATEGY_LABELS[hw.selections[id]] || '—'}</td></tr>`)
        .join('')
    : `<tr><td colspan="2" style="opacity:.7">No instruments hedged</td></tr>`;
  const m = hw.marginImpact;
  const marginTxt = m
    ? `${m.currency || ''} ${Number(m.amount).toLocaleString('en-US', { maximumFractionDigits: 0 })} (${m.source === 'kite' ? 'Live' : 'Estimated'}, ${m.instrumentId})`
    : '—';
  setEl(
    'hw-save-summary',
    `<table style="font-family:var(--fm);font-size:12px;border-collapse:collapse;margin-bottom:8px;">
       <thead><tr style="text-align:left;opacity:.7;"><th>Instrument</th><th>Strategy</th></tr></thead>
       <tbody>${rows}</tbody>
     </table>
     <div class="kpi-sub">Coverage: <strong>${hw.coverage}%</strong> &middot; Duration: <strong>1y</strong> &middot; Payoff view: <strong>${TAB_LABELS[hw.scenarioTab] || '—'}</strong></div>
     <div class="kpi-sub">Margin impact: ${marginTxt}</div>
     <div class="kpi-sub" style="opacity:.7">Strategy choice per instrument is not stored with the plan; instruments, coverage and payoff view are.</div>`
  );
}

function _renderSaveStatus() {
  const hw = _hw();
  let html = '';
  if (hw.saveStatus === 'saving') html = 'Saving…';
  else if (hw.saveStatus === 'saved') html = `Saved ${_fmtDate(hw.savedAt)}`;
  else if (hw.saveStatus === 'error') {
    html = `<span class="neg">Save failed: ${hw.saveError || 'error'}</span>
      <button onclick="hwSave()" style="margin-left:8px;padding:2px 10px;border:1px solid var(--p03);border-radius:6px;background:transparent;font-family:var(--fm);font-size:11px;cursor:pointer">Retry</button>`;
  }
  setEl('hw-save-status', html);
  const btn = document.getElementById('hw-save-btn');
  if (btn) btn.disabled = hw.saveStatus === 'saving' || !(hw.portfolioHoldings || []).length;
}

function _renderHistoryTable() {
  const plan = _hw().history.plan;
  if (!plan) {
    setEl('hw-save-history-table', `<div class="kpi-sub">No saved hedge plan yet.</div>`);
    return;
  }
  const ids = plan.hedged_ids || [];
  setEl(
    'hw-save-history-table',
    `<table style="width:100%;font-family:var(--fm);font-size:12px;border-collapse:collapse;">
       <thead><tr style="text-align:left;opacity:.7;">
         <th>Updated</th><th>Instruments</th><th>Payoff view</th><th>Coverage</th><th>Status</th>
       </tr></thead>
       <tbody><tr>
         <td>${_fmtDate(plan.updated_at)}</td>
         <td>${ids.length ? ids.join(', ') : '—'}</td>
         <td>${TAB_LABELS[plan.scenario_tab] || plan.scenario_tab || '—'}</td>
         <td>${plan.coverage != null ? plan.coverage + '%' : '—'}</td>
         <td>${plan.last_step === 'save' ? 'Saved' : 'In progress'}</td>
       </tr></tbody>
     </table>
     <div class="kpi-sub" style="opacity:.7;margin-top:4px;">Latest saved plan only.</div>`
  );
}

function _renderActionsTable() {
  const actions = _hw().history.actions || [];
  if (!actions.length) {
    setEl('hw-save-actions-table', `<div class="kpi-sub">No hedge actions recorded.</div>`);
    return;
  }
  const body = actions
    .map(
      (a) => `<tr><td>${a.date ?? '—'}</td><td>${a.action ?? '—'}</td><td>${a.lot_key ?? '—'}</td>
        <td>${a.from_group ?? '—'}</td><td>${a.to_group ?? '—'}</td><td>${a.nifty_spot ?? '—'}</td></tr>`
    )
    .join('');
  setEl(
    'hw-save-actions-table',
    `<div class="kpi-sub" style="margin-bottom:4px;">Hedge actions (Manoeuvre log) — global, not per user</div>
     <table style="width:100%;font-family:var(--fm);font-size:12px;border-collapse:collapse;">
       <thead><tr style="text-align:left;opacity:.7;">
         <th>Date</th><th>Action</th><th>Lot</th><th>From</th><th>To</th><th>NIFTY spot</th>
       </tr></thead>
       <tbody>${body}</tbody>
     </table>`
  );
}

// ── Step entry: re-fetch hedge-plan + hedge-history ─────────────────────────
export async function loadSaveStep() {
  const hw = _hw();
  const token = ++_saveToken;
  _renderSummary();
  _renderSaveStatus();
  _renderHistoryTable();
  _renderActionsTable();
  try {
    const [planRes, actionsRes] = await Promise.allSettled([
      apiFetch('/api/v1/experience/fno/hedge-plan', { headers: authHeaders() }),
      apiFetch('/api/v1/portfolio/hedge-history'),
    ]);
    if (token !== _saveToken) return; // stale — user moved on
    const plan = planRes.status === 'fulfilled' ? planRes.value : null;
    const actions = actionsRes.status === 'fulfilled' ? actionsRes.value : null;
    // A pending/failed autosave must not be clobbered by an older server copy.
    if (plan && !hw.dirty) hw.savedPlan = plan;
    hw.history = {
      plan: plan || hw.savedPlan || hw.history.plan,
      actions: Array.isArray(actions) ? actions : hw.history.actions,
    };
  } catch (e) {
    console.warn('[hedge-workflow] save step load failed', e);
  }
  if (token !== _saveToken) return;
  _renderHistoryTable();
  _renderActionsTable();
}
