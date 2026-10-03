// ── Unified FnO Hedge Workflow — shell + Exposure step (F39 Phase 2/3) ───────
//
// Shell: 4-step stepper (#hw-stepper → #hw-step-exposure/recommendation/whatif/save).
// Exposure is built here; Recommendation / What-if / Save live in
// hedge-workflow-recommendation.js / -whatif.js / -save.js (Phase 3) and are loaded
// on step entry by hwGoToStep().
//
// Exposure reuses 3 existing read-only sources (same "parallel fetch, partial
// fallback" pattern as my-portfolio.js) — user-portfolio, portfolio-analytics,
// geography-overview — plus the kite-live endpoint for a best-effort live
// quote/lot-size overlay. The saved hedge plan (hedge-plan GET) is read once per
// section entry by loadHedgeWorkflow() for last_step / coverage / hedged ids.
// All calls run via Promise.allSettled; a failed/slow source degrades only its
// own piece of the UI (inline "—"/badge) — it never blanks the whole step.
//
// No-flash rule (binding, not left to judgment): liveData is never cleared
// before a new kite-live fetch resolves — the previous value stays rendered
// until the new one replaces it in place.
//
// Refresh strategy: on step entry, no polling. hwRefreshStep() re-runs the current
// step on demand.

import { apiFetch } from './api.js';
import { setEl, badge } from '../shared/utils.js';
import { state } from './state.js';
import { renderInstrumentTiles } from './hedge-instrument-tiles.js';
import { loadRecommendationStep } from './hedge-workflow-recommendation.js';
import { loadWhatIfStep } from './hedge-workflow-whatif.js';
import { loadSaveStep, hwScheduleSave, authHeaders as _authHeaders } from './hedge-workflow-save.js';

const STEPS = ['exposure', 'recommendation', 'whatif', 'save'];
const STEP_LABELS = {
  exposure: '1. Exposure',
  recommendation: '2. Recommendation',
  whatif: '3. What-if',
  save: '4. Save',
};

function _fmt(v, d = 2) {
  return v == null || v === '' ? '—' : parseFloat(v).toFixed(d);
}

// ── Persistent shell (#hw-stepper) ───────────────────────────────────────────
function _renderStepper() {
  const current = state.hedgeWorkflow.step;
  const reached = state.hedgeWorkflow.reached;
  const html = STEPS.map((step) => {
    let cls = 'hw-step hw-step--pending';
    if (step === current) cls = 'hw-step hw-step--active';
    else if (reached.has(step)) cls = 'hw-step hw-step--reached';
    return `<span class="${cls}" onclick="hwGoToStep('${step}')" style="cursor:pointer;padding:4px 10px;font-family:var(--fm);font-size:11px;font-weight:600;">${STEP_LABELS[step]}</span>`;
  }).join('<span style="opacity:.4;">&raquo;</span>');
  setEl('hw-stepper', html);
}

function _showStepPanel(step) {
  STEPS.forEach((s) => {
    const el = document.getElementById(`hw-step-${s}`);
    if (el) el.style.display = s === step ? '' : 'none';
  });
}

// ── Exposure data guard ─────────────────────────────────────────────────────
// Steps 2-4 depend on holdings/instruments loaded by the Exposure loader, so any
// step entry (including a restore straight to whatif/save) awaits this first.
export async function ensureExposure() {
  if (state.hedgeWorkflow.exposureLoadedAt == null) await _loadExposure();
}

// First visit with no saved plan: every holding starts hedged. With a saved plan
// the stored hedged_ids are respected, even if empty.
function _applyHedgedDefault() {
  const hw = state.hedgeWorkflow;
  if (!hw.savedPlan && !hw.hedgedDefaulted && hw.portfolioHoldings.length) {
    hw.hedgedIds = hw.portfolioHoldings.map((h) => h.instrument_id);
    hw.hedgedDefaulted = true;
  }
}

let _navToken = 0;

// ── window.hwGoToStep(step, persist = true) ─────────────────────────────────
// persist=false is used by the restore path so reloading never rewrites last_step.
export async function hwGoToStep(step, persist = true) {
  const target = STEPS.includes(step) ? step : 'exposure';
  const hw = state.hedgeWorkflow;
  hw.step = target;
  hw.reached.add(target);
  _renderStepper();
  _showStepPanel(target);
  const token = ++_navToken;
  try {
    if (target === 'exposure') await _loadExposure();
    else await ensureExposure();
    if (token !== _navToken) return; // user navigated elsewhere meanwhile
    _applyHedgedDefault();
    if (persist && (hw.dirty || hw.savedPlan)) hwScheduleSave();
    if (target === 'recommendation') await loadRecommendationStep();
    else if (target === 'whatif') await loadWhatIfStep();
    else if (target === 'save') await loadSaveStep();
  } catch (e) {
    console.warn('[hedge-workflow] step load failed', target, e);
  }
}

// ── window.hwRefreshStep() — manual refresh of the current step ─────────────
export function hwRefreshStep() {
  return hwGoToStep(state.hedgeWorkflow.step, false);
}

// ── window.hwSelectInstrument(id) ────────────────────────────────────────────
// Explicit user pick from knownInstruments[] — never a side-effecting call to
// /api/v1/instrument/select (Edge Case 4; also removes the inherited
// setUnderlying() bug's call site for this step, per the core design).
export function hwSelectInstrument(id) {
  state.hedgeWorkflow.instrumentId = id;
  _renderInstrumentSelect();
  const step = state.hedgeWorkflow.step;
  // What-if fetches kite-live itself (with the chosen hedge's strike); avoid a duplicate.
  if (step !== 'whatif') _fetchLiveData(id);
  if (step === 'recommendation') loadRecommendationStep();
  else if (step === 'whatif') loadWhatIfStep();
}

// ── Exposure step — hedge quality banner (#hw-exp-hqs-banner) ───────────────
function _renderHqsBanner() {
  const positions = state.hedgeWorkflow.hedgeQuality.positions || [];
  if (positions.length === 0) {
    setEl(
      'hw-exp-hqs-banner',
      `<div class="kpi-sub">No exposure yet — build a portfolio to see your Hedge Quality Score.</div>
       <button onclick="document.querySelector('.nav-item[data-page=\\'equity-scenarios\\']')?.click()"
         style="margin-top:8px;padding:6px 16px;border:none;border-radius:6px;background:var(--p03);color:#fff;font-family:var(--fm);font-size:12px;font-weight:600;cursor:pointer">
         Go to Portfolio Builder
       </button>`
    );
    return;
  }
  const avgHqs = Math.round(positions.reduce((s, p) => s + (p.hqs || 0), 0) / positions.length);
  const hedgedCount = positions.filter((p) => p.hedged).length;
  setEl(
    'hw-exp-hqs-banner',
    `<div class="kpi-val">Hedge Quality Score: ${avgHqs}</div>
     <div class="kpi-sub">${hedgedCount}/${positions.length} positions hedged</div>`
  );
}

// ── Exposure step — instrument tiles (#hw-exp-instrument-select) ───────────
function _renderInstrumentSelect() {
  renderInstrumentTiles('hw-exp-instrument-select', state.hedgeWorkflow);
  // Keep the other step's panel in sync (both are rendered from the same state).
  renderInstrumentTiles('hw-rec-instrument-select', state.hedgeWorkflow);
}

// ── Exposure step — net Greeks KPIs (#hw-exp-greeks-kpis) ──────────────────
function _renderGreeksKpis() {
  const g = state.hedgeWorkflow.netGreeks || {};
  setEl(
    'hw-exp-greeks-kpis',
    `<div class="kpi"><div class="kpi-label">Delta</div><div class="kpi-value">${_fmt(g.delta)}</div></div>
     <div class="kpi"><div class="kpi-label">Gamma</div><div class="kpi-value">${_fmt(g.gamma)}</div></div>
     <div class="kpi"><div class="kpi-label">Theta</div><div class="kpi-value">${_fmt(g.theta)}</div></div>
     <div class="kpi"><div class="kpi-label">Vega</div><div class="kpi-value">${_fmt(g.vega)}</div></div>`
  );
}

// ── Exposure step — live-data source badge (#hw-exp-live-badge) ────────────
// Addendum. Reads liveData.source via the existing badge() helper (shared/utils.js).
function _renderLiveBadge() {
  const live = state.hedgeWorkflow.liveData;
  setEl('hw-exp-live-badge', badge(live.available ? 'Live' : 'Estimated'));
}

// ── Exposure step — combined holdings table (#hw-exp-holdings-table) ───────
// Combined equity + options, one view (wireframe Q2 — not tabs). Segments rows
// by instrument; never merges equity and option rows into one computed row.
function _renderHoldingsTable() {
  const rows = state.hedgeWorkflow.holdings || [];
  if (rows.length === 0) {
    setEl(
      'hw-exp-holdings-table',
      `<div class="kpi-sub">No holdings or positions yet.</div>`
    );
    return;
  }
  const body = rows
    .map((r) => {
      const pnlCls = r.pnl == null ? '' : r.pnl >= 0 ? 'pos' : 'neg';
      return `<tr>
        <td>${r.instrument_id}</td>
        <td>${r.type}</td>
        <td>${r.qty_label}</td>
        <td>${_fmt(r.avg_price)}</td>
        <td>${_fmt(r.market_value)}</td>
        <td>${_fmt(r.delta)}</td>
        <td class="${pnlCls}">${_fmt(r.pnl)}</td>
      </tr>`;
    })
    .join('');
  setEl(
    'hw-exp-holdings-table',
    `<table style="width:100%;font-family:var(--fm);font-size:12px;border-collapse:collapse;">
       <thead><tr style="text-align:left;opacity:.7;">
         <th>Instrument</th><th>Type</th><th>Qty/Lots</th><th>Avg Px</th><th>Mkt Val</th><th>Delta</th><th>P&amp;L</th>
       </tr></thead>
       <tbody>${body}</tbody>
     </table>`
  );
}

function _renderExposureFromState() {
  _renderHqsBanner();
  _renderInstrumentSelect();
  _renderGreeksKpis();
  _renderLiveBadge();
  _renderHoldingsTable();
}

// ── kite-live fetch (addendum) — no-flash rule ──────────────────────────────
async function _fetchLiveData(instrumentId) {
  if (!instrumentId) return;
  // Binding no-flash rule: do NOT clear/reset state.hedgeWorkflow.liveData
  // before this resolves. On failure (data === null) the previous value is
  // left untouched below — that omission IS the no-flash behavior, not a bug.
  const data = await apiFetch(
    `/api/v1/experience/fno/kite-live?instrument_id=${encodeURIComponent(instrumentId)}`,
    { headers: _authHeaders() }
  );
  if (data) {
    state.hedgeWorkflow.liveData = {
      available: data.available,
      source: data.source,
      lotSize: data.lot_size,
      quote: data.quote,
      margin: data.margin,
      fetchedAt: data.fetched_at,
      instrumentId,
    };
  }
  _renderLiveBadge();
}

// ── Main Exposure loader ─────────────────────────────────────────────────────
async function _loadExposure() {
  const headers = _authHeaders();

  const [portfolioRes, analyticsRes, geoRes] = await Promise.allSettled([
    apiFetch('/api/v1/experience/user-portfolio', { headers }),
    apiFetch('/api/v1/experience/fno/portfolio-analytics?mode=real', { headers }),
    apiFetch('/api/v1/experience/rita/geography-overview', {}),
  ]);

  const portfolio = portfolioRes.status === 'fulfilled' ? portfolioRes.value : null;
  const analytics = analyticsRes.status === 'fulfilled' ? analyticsRes.value : null;
  const geo = geoRes.status === 'fulfilled' ? geoRes.value : null;

  // instMap: instrument_id -> full geography instrument + region (close price for the
  // equity market-value calc here; risk/return/region for the Phase 3 steps).
  const instMap = {};
  if (geo?.regions) {
    for (const reg of geo.regions) {
      for (const inst of reg.instruments ?? []) {
        instMap[inst.id] = { ...inst, region: reg.region };
      }
    }
  }

  const equityHoldings = portfolio?.holdings || [];
  const totalValueEur = portfolio?.total_value_eur ?? null;

  const equityRows = equityHoldings.map((h) => {
    const close = instMap[h.instrument_id]?.close;
    const marketValue =
      close != null && h.shares != null
        ? close * h.shares
        : totalValueEur != null
          ? (totalValueEur * h.allocation_pct) / 100
          : null;
    return {
      instrument_id: h.instrument_id,
      type: 'EQ',
      qty_label: h.shares != null ? String(h.shares) : '—',
      avg_price: null,
      market_value: marketValue,
      delta: null,
      pnl: null,
    };
  });

  const optionPositions = analytics?.positions || [];
  const greeksList = analytics?.greeks || [];
  const optionRows = optionPositions.map((p) => {
    const matchingGreeks = greeksList.filter((g) => g.und === p.und && g.exp === p.exp);
    const delta = matchingGreeks.length
      ? matchingGreeks.reduce((s, g) => s + (g.delta || 0), 0)
      : null;
    return {
      instrument_id: p.full || p.und,
      type: p.type,
      qty_label: `${p.qty} lots`,
      avg_price: p.avg,
      market_value: p.position_eur,
      delta,
      pnl: p.pnl,
    };
  });

  state.hedgeWorkflow.portfolioHoldings = equityHoldings;
  state.hedgeWorkflow.instruments = instMap;
  state.hedgeWorkflow.totalValueEur = totalValueEur;
  state.hedgeWorkflow.holdings = [...equityRows, ...optionRows];
  state.hedgeWorkflow.positions = optionPositions;
  state.hedgeWorkflow.cashEur = equityHoldings.reduce((s, h) => s + (h.cash_eur || 0), 0) || null;

  state.hedgeWorkflow.knownInstruments = [
    ...new Set([
      ...equityHoldings.map((h) => h.instrument_id),
      ...optionPositions.map((p) => p.und),
    ].filter(Boolean)),
  ];
  if (!state.hedgeWorkflow.instrumentId && state.hedgeWorkflow.knownInstruments.length > 0) {
    state.hedgeWorkflow.instrumentId = state.hedgeWorkflow.knownInstruments[0];
  }

  // NetGreeksSchema carries delta/theta/vega only — gamma is aggregated here
  // from the per-position greeks list (GreekItemSchema.gamma) as a reasonable
  // composite for the 4-KPI wireframe layout.
  const netGreeks = analytics?.net_greeks || {};
  state.hedgeWorkflow.netGreeks = {
    delta: netGreeks.delta ?? null,
    gamma: greeksList.length ? greeksList.reduce((s, g) => s + (g.gamma || 0), 0) : null,
    theta: netGreeks.theta ?? null,
    vega: netGreeks.vega ?? null,
  };

  state.hedgeWorkflow.hedgeQuality = {
    positions: analytics?.hedge_quality?.positions || [],
  };

  state.hedgeWorkflow.exposureLoadedAt = Date.now();

  _renderExposureFromState();

  if (state.hedgeWorkflow.instrumentId) {
    _fetchLiveData(state.hedgeWorkflow.instrumentId);
  }
}

// ── window.loadHedgeWorkflow(stepOverride) — section-loader entry point ────
// stepOverride (alias deep-links from nav.js / main.js) wins over the saved
// last_step. The step is entered exactly once, after the hedge plan has resolved,
// so an alias can never be overridden by a late-arriving plan (Phase 2 race).
export async function loadHedgeWorkflow(stepOverride) {
  const hw = state.hedgeWorkflow;
  let step = 'exposure';
  try {
    // hedge-plan GET returns null with HTTP 200 when no plan exists (or null on 404
    // via apiFetch) — both mean "no saved plan": default silently.
    const plan = await apiFetch('/api/v1/experience/fno/hedge-plan', { headers: _authHeaders() });
    if (plan && !hw.dirty) {
      hw.savedPlan = plan;
      hw.coverage = plan.coverage ?? 50;
      hw.scenarioTab = plan.scenario_tab || 'pp';
      hw.hedgedIds = plan.hedged_ids ?? [];
      hw.duration = '1y';
      hw.hedgedDefaulted = true;
    }
    if (STEPS.includes(stepOverride)) step = stepOverride;
    else if (plan?.last_step && STEPS.includes(plan.last_step)) step = plan.last_step;
  } catch (e) {
    console.warn('[hedge-workflow] load failed', e);
  }
  await hwGoToStep(step, false);
}
