// ── Unified FnO Hedge Workflow — shell + Exposure step (F39 Phase 2) ─────────
//
// Shell: 4-step stepper (#hw-stepper → #hw-step-exposure/recommendation/whatif/save).
// Only the Exposure step is fully built this phase; Recommendation/What-if/Save are
// empty stub panels reachable via hwGoToStep() — their content is Phase 3 scope
// (hedge-workflow-recommendation.js / -whatif.js / -save.js, not yet written).
//
// Exposure reuses 3 existing read-only sources (same "parallel fetch, partial
// fallback" pattern as my-portfolio.js) — user-portfolio, portfolio-analytics,
// geography-overview — plus hedge-plan (for last_step restore) and the new
// kite-live endpoint for a best-effort live quote/lot-size overlay (addendum).
// All calls run via Promise.allSettled; a failed/slow source degrades only its
// own piece of the UI (inline "—"/badge) — it never blanks the whole step
// (Edge Case 3).
//
// No-flash rule (binding, not left to judgment): liveData is never cleared
// before a new kite-live fetch resolves — the previous value stays rendered
// until the new one replaces it in place (Edge Case 9).

import { apiFetch } from './api.js';
import { setEl, badge } from '../shared/utils.js';
import { state } from './state.js';

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

function _authHeaders() {
  const token = sessionStorage.getItem('auth_token');
  return token ? { Authorization: `Bearer ${token}` } : {};
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

// ── window.hwGoToStep(step) ──────────────────────────────────────────────────
export function hwGoToStep(step) {
  const target = STEPS.includes(step) ? step : 'exposure';
  state.hedgeWorkflow.step = target;
  state.hedgeWorkflow.reached.add(target);
  _renderStepper();
  _showStepPanel(target);
  if (target === 'exposure') {
    _loadExposure();
  }
  // Recommendation/What-if/Save panels are empty stubs in Phase 2 — nothing to
  // load for them yet; Phase 3 modules will register their own step-entry hooks.
}

// ── window.hwSelectInstrument(id) ────────────────────────────────────────────
// Explicit user pick from knownInstruments[] — never a side-effecting call to
// /api/v1/instrument/select (Edge Case 4; also removes the inherited
// setUnderlying() bug's call site for this step, per the core design).
export function hwSelectInstrument(id) {
  state.hedgeWorkflow.instrumentId = id;
  _renderInstrumentSelect();
  _fetchLiveData(id);
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

// ── Exposure step — instrument select (#hw-exp-instrument-select) ──────────
function _renderInstrumentSelect() {
  const known = state.hedgeWorkflow.knownInstruments || [];
  const active = state.hedgeWorkflow.instrumentId;
  if (known.length === 0) {
    setEl('hw-exp-instrument-select', `<div class="kpi-sub">—</div>`);
    return;
  }
  const options = known
    .map((id) => `<option value="${id}" ${id === active ? 'selected' : ''}>${id}</option>`)
    .join('');
  setEl(
    'hw-exp-instrument-select',
    `<div class="kpi-label">Instrument</div>
     <select onchange="hwSelectInstrument(this.value)" style="font-family:var(--fm);font-size:12px;padding:4px 8px;">${options}</select>`
  );
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
    };
  }
  _renderLiveBadge();
}

// ── Main Exposure loader ─────────────────────────────────────────────────────
async function _loadExposure() {
  const headers = _authHeaders();

  const [portfolioRes, analyticsRes, geoRes, hedgeRes] = await Promise.allSettled([
    apiFetch('/api/v1/experience/user-portfolio', { headers }),
    apiFetch('/api/v1/experience/fno/portfolio-analytics?mode=real', { headers }),
    apiFetch('/api/v1/experience/rita/geography-overview', {}),
    apiFetch('/api/v1/experience/fno/hedge-plan', { headers }),
  ]);

  const portfolio = portfolioRes.status === 'fulfilled' ? portfolioRes.value : null;
  const analytics = analyticsRes.status === 'fulfilled' ? analyticsRes.value : null;
  const geo = geoRes.status === 'fulfilled' ? geoRes.value : null;
  const hedgePlan = hedgeRes.status === 'fulfilled' ? hedgeRes.value : null;

  // instMap: instrument_id -> live close price (for equity market-value calc).
  const instMap = {};
  if (geo?.regions) {
    for (const reg of geo.regions) {
      for (const inst of reg.instruments ?? []) {
        instMap[inst.id] = { close: inst.close };
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

  if (hedgePlan) {
    state.hedgeWorkflow.coverage = hedgePlan.coverage ?? 50;
    state.hedgeWorkflow.scenarioTab = hedgePlan.scenario_tab ?? null;
    state.hedgeWorkflow.hedgedIds = hedgePlan.hedged_ids ?? [];
    state.hedgeWorkflow.duration = hedgePlan.duration ?? '1y';
  }

  _renderExposureFromState();

  if (state.hedgeWorkflow.instrumentId) {
    _fetchLiveData(state.hedgeWorkflow.instrumentId);
  }
}

// ── window.loadHedgeWorkflow — section-loader entry point ──────────────────
export async function loadHedgeWorkflow() {
  try {
    const headers = _authHeaders();
    // Edge Case 2: no saved plan yet (404) -> apiFetch returns null -> default
    // silently to lastStep="exposure" (and coverage/duration/hedgedIds defaults
    // already set in state.js's initial state.hedgeWorkflow shape).
    const hedgePlan = await apiFetch('/api/v1/experience/fno/hedge-plan', { headers });
    const lastStep =
      hedgePlan?.last_step && STEPS.includes(hedgePlan.last_step) ? hedgePlan.last_step : 'exposure';
    hwGoToStep(lastStep);
  } catch (e) {
    console.warn('[hedge-workflow] load failed', e);
    hwGoToStep('exposure');
  }
}
