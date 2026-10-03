// ── Unified FnO Hedge Workflow — shell + Exposure step (F39 Phase 2/3) ───────
//
// Shell: 4-step stepper (#hw-stepper → #hw-step-exposure/recommendation/whatif/save).
// Exposure is built here; Recommendation / What-if / Save live in
// hedge-workflow-recommendation.js / -whatif.js / -save.js (Phase 3) and are loaded
// on step entry by hwGoToStep().
//
// Exposure = "your current challenge": net Greeks + monthly 1/2/3 sigma risk tiles on one
// row, a summary line, and the shared monthly candle / MoM charts (hedge-charts.js, same
// equity-hedge-scenarios source as the old Equity Hedge page) with monthly sigma bands.
// The old holdings table was removed (no decision value); "how the hedge helps" is
// shown on the Save step.
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

import { api, apiFetch } from './api.js';
import { setEl, badge } from '../shared/utils.js';
import { state } from './state.js';
import { renderInstrumentTiles } from './hedge-instrument-tiles.js';
import { computeNShares, monthlySigma, sigmaLevels, portfolioVolPct, buildVolMap } from './hedge-calc.js';
import { renderMonthlyCandles, renderMonthlyChange, BAND_COLORS } from './hedge-charts.js';
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
  if (step === 'exposure') _renderChallenge();
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

// ── Exposure step — current challenge (monthly σ tiles, summary, charts) ───
// Monthly σ = ann_vol_pct / 100 / sqrt(12) (hedge-calc.js monthlySigma). The Risk page's
// std-dev table is untouched; this is the monthly counterpart for the selected instrument.
const _CCY_SYMBOL = { EUR: '€', INR: '₹', USD: '$' };
let _candleChart = null;
let _changeChart = null;
let _histToken = 0;

function _esc(v) {
  return String(v ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function _sym(id) {
  const hw = state.hedgeWorkflow;
  const pos = (hw.positions || []).find((p) => p.und === id);
  return _CCY_SYMBOL[hw.instruments[id]?.currency || pos?.currency] || '';
}

function _price(id) {
  const hw = state.hedgeWorkflow;
  const close = hw.instruments[id]?.close;
  if (close != null) return parseFloat(close);
  const pos = (hw.positions || []).find((p) => p.und === id);
  const v = pos?.ltp ?? pos?.avg;
  return v != null ? parseFloat(v) : null;
}

function _fmtNum(v, d = 2) {
  return v == null || Number.isNaN(Number(v)) ? '—' : Number(v).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
}

function _eur(v) {
  return v == null || Number.isNaN(Number(v)) ? '—' : '€' + Number(v).toLocaleString('en-US', { maximumFractionDigits: 0 });
}

function _volFor(id) {
  const hw = state.hedgeWorkflow;
  return buildVolMap(hw.positions, hw.greeks, hw.apiHedge)[id] ?? null;
}

function _portfolioVolPct() {
  const hw = state.hedgeWorkflow;
  return portfolioVolPct(hw.greeks, hw.portfolioHoldings, buildVolMap(hw.positions, hw.greeks, hw.apiHedge));
}

function _renderSigmaKpis() {
  const hw = state.hedgeWorkflow;
  const id = hw.instrumentId;
  const lv = id ? sigmaLevels(_price(id), _volFor(id)) : null;
  if (!lv) {
    setEl('hw-exp-sigma-kpis', `<div class="kpi"><div class="kpi-label">Monthly 1σ / 2σ / 3σ</div><div class="kpi-value">—</div><div class="kpi-sub">no volatility for ${_esc(id || 'instrument')}</div></div>`);
    return;
  }
  const sym = _sym(id);
  setEl(
    'hw-exp-sigma-kpis',
    lv.map((l) => `<div class="kpi"><div class="kpi-label">Monthly −${l.k}σ</div>
      <div class="kpi-value neg">${l.downPct.toFixed(1)}%</div>
      <div class="kpi-sub">${l.down != null ? sym + _fmtNum(l.down) : '—'}</div></div>`).join('')
  );
}

function _renderChallengeSummary() {
  const hw = state.hedgeWorkflow;
  const id = hw.instrumentId;
  if (!id) { setEl('hw-exp-challenge-summary', `<div class="kpi-sub">No exposure yet.</div>`); return; }
  const parts = [];
  const volI = _volFor(id);
  const sI = monthlySigma(volI);
  if (sI != null) parts.push(`<strong>${_esc(id)}</strong>: a 1σ bad month is <strong class="neg">−${(sI * 100).toFixed(1)}%</strong> (2σ −${(sI * 200).toFixed(1)}%, 3σ −${(sI * 300).toFixed(1)}%), ann. vol ${volI.toFixed(1)}%`);
  const sP = monthlySigma(_portfolioVolPct());
  const tv = hw.totalValueEur;
  if (sP != null) {
    parts.push(
      tv != null
        ? `Portfolio (${_eur(tv)}): 1σ bad month <strong class="neg">−${_eur(tv * sP)}</strong> · 2σ −${_eur(tv * sP * 2)} · 3σ −${_eur(tv * sP * 3)}`
        : `Portfolio: 1σ bad month −${(sP * 100).toFixed(1)}%`
    );
  }
  const a = (hw.apiHedge?.holdings || []).find((h) => h.instrument_id === id);
  if (a && a.quarterly_var_pct != null) parts.push(`Quarterly VaR ${Number(a.quarterly_var_pct).toFixed(1)}%${a.quarterly_var_eur != null ? ' (' + _eur(a.quarterly_var_eur) + ')' : ''}`);
  setEl(
    'hw-exp-challenge-summary',
    parts.length
      ? `<div class="kpi-label">Your current challenge</div>${parts.map((t) => `<div class="kpi-sub">${t}</div>`).join('')}
         <div class="kpi-sub" style="opacity:.7">Monthly σ = annual volatility ÷ √12.</div>`
      : `<div class="kpi-sub">Your current challenge — volatility data unavailable.</div>`
  );
}

function _rollingDateRange() {
  const end = new Date();
  const start = new Date();
  start.setFullYear(start.getFullYear() - 1);
  return { start: start.toISOString().slice(0, 10), end: end.toISOString().slice(0, 10) };
}

// Same endpoint + inputs as the old Equity Hedge page (equity-hedge-scenarios, 1y range,
// n_shares via computeNShares, ann_vol_pct from positions). Only portfolio.daily is used;
// an instrument without an equity holding passes n_shares = 1 (price series is share-count
// independent).
async function _fetchHistory(id) {
  const hw = state.hedgeWorkflow;
  if (hw.priceHistory[id]) return hw.priceHistory[id];
  const h = (hw.portfolioHoldings || []).find((x) => x.instrument_id === id);
  const nShares = h ? computeNShares(h, hw.instruments[id], hw.totalValueEur) : 1;
  const { start, end } = _rollingDateRange();
  const volPos = (hw.positions || []).find((p) => p.und === id && p.ann_vol_pct != null);
  const body = { instrument: id, n_shares: nShares, start_date: start, end_date: end };
  if (volPos) body.ann_vol_pct = parseFloat(volPos.ann_vol_pct);
  try {
    const res = await api('/api/v1/portfolio/equity-hedge-scenarios', 'POST', body);
    const daily = res?.portfolio?.daily;
    if (Array.isArray(daily) && daily.length > 1) {
      hw.priceHistory[id] = { daily, currency: res.portfolio.currency || null, holding: !!h };
      return hw.priceHistory[id];
    }
  } catch (e) {
    console.warn('[hedge-workflow] price history failed', id, e);
  }
  return null;
}

function _drawCharts(id, hist) {
  const sym = _sym(id) || (_CCY_SYMBOL[hist.currency] || '');
  const last = hist.daily[hist.daily.length - 1].price;
  const lv = sigmaLevels(last, _volFor(id)) || [];
  const bands = lv.map((l) => ({
    label: `−${l.k}σ monthly (${l.downPct.toFixed(1)}%)`, value: l.down, color: BAND_COLORS['k' + l.k],
  }));
  const up = lv[0];
  if (up) bands.push({ label: `+1σ monthly (+${up.sigmaPct.toFixed(1)}%)`, value: up.up, color: '#1A6B3C', dash: [3, 3] });
  _candleChart = renderMonthlyCandles('hw-exp-candle-chart', hist.daily, {
    fmt: (v) => sym + Number(v).toLocaleString('en-US', { maximumFractionDigits: 2 }), bands, prev: _candleChart,
  });
  _changeChart = renderMonthlyChange('hw-exp-change-chart', hist.daily, {
    prev: _changeChart, titleId: 'hw-exp-change-title', title: `Monthly Price Change — ${id}`,
  });
  setEl('hw-exp-candle-title', `${_esc(id)} price vs monthly risk bands`);
  setEl('hw-exp-candle-msg', hist.holding ? '' : `No equity holding for ${_esc(id)} — showing the instrument price (option exposure only).`);
}

async function _renderChallengeCharts() {
  const hw = state.hedgeWorkflow;
  const id = hw.instrumentId;
  const token = ++_histToken;
  if (!id) return;
  const cached = hw.priceHistory[id];
  if (cached) { _drawCharts(id, cached); return; }
  setEl('hw-exp-candle-msg', `Loading ${_esc(id)} price history…`);
  const hist = await _fetchHistory(id);
  if (token !== _histToken || hw.instrumentId !== id) return; // user moved on
  if (!hist) {
    _candleChart = renderMonthlyCandles('hw-exp-candle-chart', [], { prev: _candleChart });
    _changeChart = renderMonthlyChange('hw-exp-change-chart', [], { prev: _changeChart });
    setEl('hw-exp-candle-msg', `Price history unavailable for ${_esc(id)}.`);
    return;
  }
  _drawCharts(id, hist);
}

function _renderChallenge() {
  _renderSigmaKpis();
  _renderChallengeSummary();
  return _renderChallengeCharts();
}

function _renderExposureFromState() {
  _renderHqsBanner();
  _renderInstrumentSelect();
  _renderGreeksKpis();
  _renderLiveBadge();
  _renderChallenge();
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

  const optionPositions = analytics?.positions || [];
  const greeksList = analytics?.greeks || [];

  state.hedgeWorkflow.portfolioHoldings = equityHoldings;
  state.hedgeWorkflow.instruments = instMap;
  state.hedgeWorkflow.totalValueEur = totalValueEur;
  state.hedgeWorkflow.greeks = greeksList;
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
