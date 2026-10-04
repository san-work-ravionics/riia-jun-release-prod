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
import { mkChart } from '../shared/charts.js';
import { state } from './state.js';
import { buildRows, hedgeImpact, buildVolMap, portfolioVolPct } from './hedge-calc.js';

const _SAVE_DEBOUNCE_MS = 400;
let _saveTimer = null;
let _saveToken = 0;
let _inflight = null; // promise of the autosave PUT currently on the wire

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

function _autosave() {
  const hw = _hw();
  if (hw.saveStatus === 'saving') return Promise.resolve();
  const p = _doAutosave(hw).finally(() => { if (_inflight === p) _inflight = null; });
  _inflight = p;
  return p;
}

async function _doAutosave(hw) {
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
  // An autosave PUT already on the wire must land BEFORE the explicit write, so the
  // final DB row (and savedPlan/UI) always carries last_step 'save'.
  if (_inflight) await _inflight.catch(() => {});
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
  const hedgedN = hw.hedgedIds.filter((id) => known.has(id)).length;
  const heldN = known.size;
  const m = hw.marginImpact;
  const marginTxt = m
    ? `${m.currency || ''} ${Number(m.amount).toLocaleString('en-US', { maximumFractionDigits: 0 })} (${m.source === 'kite' ? 'Live' : 'Estimated'}, ${m.instrumentId})`
    : '—';
  setEl(
    'hw-save-summary',
    `<div class="kpi-sub">${heldN} instrument${heldN !== 1 ? 's' : ''} held · ${hedgedN ? `${hedgedN} hedged` : 'none hedged'}</div>
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

// ── How this hedge helps (before Save) ───────────────────────────────────────
// Before/after of the chosen hedge (coverage + payoff view + hedged set) at monthly
// -1σ/-2σ/-3σ and flat. Same pure calc as the What-if step (hedgedPL / aggregates /
// buildRows); only the move inputs are σ-scaled. % are of total portfolio value, as in
// the What-if scenario table; € uses total_value_eur when known.
function _pct(v, d = 1) {
  return v == null || Number.isNaN(Number(v)) ? '—' : `${Number(v) > 0 ? '+' : ''}${Number(v).toFixed(d)}%`;
}
function _eur(v) {
  return v == null || Number.isNaN(Number(v)) ? '—' : (v < 0 ? '−' : '') + '€' + Math.abs(Number(v)).toLocaleString('en-US', { maximumFractionDigits: 0 });
}

// Rows of the merged table by key ('PORTFOLIO' or instrument id) so a row click can redraw
// the chart below for that row. _impactSel is the selected key (defaults to Portfolio).
let _impactRows = {};
let _impactSel = 'PORTFOLIO';

function _drawImpactChart() {
  const row = _impactRows[_impactSel] || _impactRows.PORTFOLIO;
  if (!row) return;
  const sc = row.scenarios;
  setEl('hw-save-impact-chart-title', `Monthly move P&amp;L — ${row.name} (% of ${row.name === 'Portfolio' ? 'portfolio' : 'position'})`);
  mkChart('hw-save-impact-chart', {
    type: 'bar',
    data: {
      labels: sc.map((s) => s.label),
      datasets: [
        { label: 'Unhedged', data: sc.map((s) => +s.unhedgedPct.toFixed(2)), backgroundColor: 'rgba(100,116,139,.55)' },
        { label: 'Hedged', data: sc.map((s) => +s.hedgedPct.toFixed(2)), backgroundColor: '#BE185D' },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: true, position: 'top' }, tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${c.parsed.y.toFixed(1)}%` } } },
      scales: { y: { title: { display: true, text: 'P&L %' }, ticks: { callback: (v) => v + '%' } } },
    },
  });
}

// window.hwSaveSelectRow(key) — row click in the merged table redraws the chart below.
export function hwSaveSelectRow(key) {
  if (!_impactRows[key]) return;
  _impactSel = key;
  _renderImpact();
}

function _esc(v) {
  return String(v ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function _renderImpact() {
  const hw = _hw();
  const rows = buildRows(hw.portfolioHoldings, hw.instruments, hw.apiHedge, new Set(hw.hedgedIds), hw.coverage);
  const vm = buildVolMap(hw.positions, hw.greeks, hw.apiHedge);
  const vol = portfolioVolPct(hw.greeks, hw.portfolioHoldings, vm);
  const imp = hedgeImpact(rows, hw.apiHedge, hw.scenarioTab || 'pp', vol, hw.totalValueEur);
  if (!imp) {
    setEl('hw-save-impact-kpis', `<div class="kpi-sub">No instruments hedged — nothing to compare yet.</div>`);
    setEl('hw-save-impact-table', '');
    setEl('hw-save-impact-note', '');
    _impactRows = {};
    setEl('hw-save-impact-chart-title', '');
    mkChart('hw-save-impact-chart', { type: 'bar', data: { labels: [], datasets: [] } });
    return;
  }
  setEl(
    'hw-save-impact-kpis',
    `<div class="kpi"><div class="kpi-label">Max drawdown</div>
       <div class="kpi-value">${imp.agg.maxDdHedged.toFixed(0)}%</div>
       <div class="kpi-sub">vs ${imp.agg.maxDdUnhedged.toFixed(0)}% unhedged (${_pct(imp.maxDdProtectedPct, 0)} protected)</div></div>
     <div class="kpi"><div class="kpi-label">Premium cost</div>
       <div class="kpi-value">${imp.premiumPct.toFixed(2)}%/mo</div>
       <div class="kpi-sub">${_eur(imp.premiumEur)} per month</div></div>`
  );
  // One merged table, one line per row: Portfolio first, then each hedged instrument.
  // Instrument rows reuse the same pure calc on that single row at weight 100 (its own
  // strike/cost/vol), with € on the instrument's position value; the Portfolio row is
  // the aggregate above. Each monthly move has an Unhedged and a Hedged column.
  const one = (pct, eur) => `${_pct(pct)}${eur != null ? ` <span class="kpi-sub">(${_eur(eur)})</span>` : ''}`;
  const scenCells = (scenarios) => scenarios.map((sc) =>
    `<td style="text-align:right;white-space:nowrap;border-left:1px solid var(--border)" class="${sc.unhedgedPct < 0 ? 'neg' : ''}">${one(sc.unhedgedPct, sc.unhedgedEur)}</td>
     <td style="text-align:right;white-space:nowrap">${one(sc.hedgedPct, sc.hedgedEur)}</td>`).join('');
  _impactRows = { PORTFOLIO: { name: 'Portfolio', scenarios: imp.scenarios } };
  const nKite = rows.filter((r) => r.costSource === 'kite').length;
  imp.costTag = nKite === rows.length ? 'Zerodha' : nKite ? 'mixed' : 'est.';
  imp.costTip = `${nKite} of ${rows.length} hedged instruments priced from live Zerodha option quotes; the rest use a model estimate`;
  const rowHtml = (key, name, strategy, expo, iv, bold) => `<tr data-key="${key}" onclick="hwSaveSelectRow(this.dataset.key)" title="Click to chart this row"
      style="border-top:1px solid var(--border);cursor:pointer;${bold ? 'font-weight:600;' : ''}${key === _impactSel ? 'background:var(--surface2);' : ''}">
      <td>${name}</td><td>${strategy}</td><td style="text-align:right;white-space:nowrap">${expo}</td>
      <td style="text-align:right;white-space:nowrap" title="${_esc(iv.costTip || '')}">${iv.premiumPct.toFixed(2)}%${iv.premiumEur != null ? ` <span class="kpi-sub">(${_eur(iv.premiumEur)})</span>` : ''} <span class="kpi-sub">${iv.costTag || ''}</span></td>
      ${scenCells(iv.scenarios)}</tr>`;
  const instRows = rows.map((r) => {
    const h = hw.portfolioHoldings.find((x) => x.instrument_id === r.id);
    const posEur = hw.totalValueEur != null && h ? (h.allocation_pct / 100) * hw.totalValueEur : null;
    const iv = hedgeImpact([{ ...r, weight: 100 }], hw.apiHedge, hw.scenarioTab || 'pp', vm[r.id], posEur);
    if (iv) {
      iv.costTag = r.costSource === 'kite' ? 'Zerodha' : 'est.';
      iv.costTip = r.costSource === 'kite' ? r.costDetail : 'Model estimate (1-month Black-Scholes) — no live Zerodha quote';
      _impactRows[r.id] = { name: r.id, scenarios: iv.scenarios };
    }
    return iv ? rowHtml(r.id, r.id, STRATEGY_LABELS[hw.selections[r.id]] || '—', _eur(posEur), iv, false) : '';
  }).join('');
  const th = 'text-align:right;white-space:nowrap';
  const groups = imp.scenarios.map((sc) => `<th colspan="2" style="${th};border-left:1px solid var(--border)">${sc.k ? `Monthly ${sc.label} move${sc.movePct != null ? ` (${_pct(sc.movePct)})` : ''}` : 'Flat (no move)'}</th>`).join('');
  const subs = imp.scenarios.map(() => `<th style="${th};border-left:1px solid var(--border)">Unhedged</th><th style="${th}">Hedged</th>`).join('');
  setEl(
    'hw-save-impact-table',
    `<div class="kpi-sub" style="margin-bottom:8px;line-height:1.5">
       What a typical bad month would do to your money, with and without the hedge. One row for the whole portfolio and one per hedged instrument.
       <strong>Monthly −1σ / −2σ / −3σ</strong> are a normal, a bad and a very bad month (about 1 in 6, 1 in 40 and 1 in 700 months).
       <strong>Unhedged</strong> is the P&amp;L (% of position, € in brackets) if you do nothing; <strong>Hedged</strong> is the P&amp;L with the ${TAB_LABELS[hw.scenarioTab] || 'hedge'}, including the monthly premium.
       <strong>Premium</strong> is the monthly cost of the hedge. <strong>Exposure</strong> is the position value the € figures apply to.
     </div>
     <div style="overflow-x:auto"><table style="width:100%;font-family:var(--fm);font-size:12px;border-collapse:collapse;">
       <thead>
         <tr style="text-align:left;opacity:.7;"><th rowspan="2" style="vertical-align:bottom">Level</th><th rowspan="2" style="vertical-align:bottom">Strategy</th><th rowspan="2" style="${th};vertical-align:bottom">Exposure</th><th rowspan="2" style="${th};vertical-align:bottom">Premium / mo</th>${groups}</tr>
         <tr style="opacity:.7;">${subs}</tr>
       </thead>
       <tbody>${rowHtml('PORTFOLIO', 'Portfolio', TAB_LABELS[hw.scenarioTab] || '—', _eur(hw.totalValueEur), imp, true)}${instRows}</tbody></table></div>`
  );
  setEl(
    'hw-save-impact-note',
    imp.monthlySigmaPct != null
      ? `Monthly 1σ = ${imp.monthlySigmaPct.toFixed(1)}% (portfolio annual vol ${Number(vol).toFixed(1)}% ÷ √12). Hedged P&L includes the monthly premium.`
      : 'Monthly σ unavailable (no volatility data) — only the flat case is shown.'
  );
  if (!_impactRows[_impactSel]) _impactSel = 'PORTFOLIO';
  _drawImpactChart();
}

// ── Step entry: re-fetch hedge-plan + hedge-history ─────────────────────────
export async function loadSaveStep() {
  const hw = _hw();
  const token = ++_saveToken;
  _renderSummary();
  _renderImpact();
  _renderSaveStatus();
  _renderHistoryTable();
  _renderActionsTable();
  try {
    // Restored straight to Save: portfolio-hedge may not be loaded; best-effort fetch so
    // the impact view uses the same server rows as the What-if step.
    if (!hw.apiHedge) {
      let u = `/api/v1/experience/fno/portfolio-hedge?coverage=${hw.coverage}`;
      if (hw.totalValueEur != null) u += `&total_value_eur=${hw.totalValueEur}`;
      const ph = await apiFetch(u, { headers: authHeaders() });
      if (ph && token === _saveToken) { hw.apiHedge = ph; _renderImpact(); }
    }
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
