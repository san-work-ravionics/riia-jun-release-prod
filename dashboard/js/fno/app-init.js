// ── FnO App Initialisation ────────────────────────────────────────────────────

import { api, apiFetch, apiBase } from './api.js';
import { holdingCash, portfolioCurrency, setPortfolioCurrency } from '../shared/portfolio-currency.js';
import { state } from './state.js';
import { buildExpiryPills } from './nav.js';
import { renderGreeksCards, updateRiskSections } from './greeks.js';
import { renderStressScenarios } from './stress.js';
import { renderPayoffChart } from './payoff.js';
import { saveToday, syncPriceHistory, renderScenarios } from './rr.js';
import { initManoeuvre } from './manoeuvre.js';
import { fetchAndRenderRiskCharts, highlightRiskChart } from './risk_chart.js';

// ── scenario_levels shape normalisation ──────────────────────────────────────
// API may return {INST: {target, sl}} or {INST: {bull:{target,sl}, bear:{target,sl}}}.
// Normalise everything to the bull/bear shape so consumers (rr.js) are consistent.
function _normScenarioLevels(raw) {
  const out = {};
  for (const [key, val] of Object.entries(raw || {})) {
    if (val && val.bull !== undefined) {
      out[key] = val; // already normalised
    } else if (val && val.target !== undefined && val.sl !== undefined) {
      out[key] = {
        bull: { target: val.target, sl: val.sl },
        bear: { target: val.sl,    sl: val.target },
      };
    } else {
      out[key] = val;
    }
  }
  return out;
}

// Re-render risk sections when the stddev table row click changes the instrument filter
document.addEventListener('risk-filter-change', () => {
  renderGreeksCards();
  renderStressScenarios();
  highlightRiskChart();
});

// window.RITA_API_BASE can be set by the host page to point at a non-origin
// API server (e.g. staging). Defaults to '' = same origin.

export async function initApp(mode = 'mock') {
  state.analyticsMode = mode;

  // Fire portfolio + geography fetches in parallel with the main analytics call.
  // F44 P2: authenticated reads go through api() (401 → ensureDevToken(true) → retry once on
  // localhost; production → Google sign-in) — no raw fetch.
  const _portPromise = api('/api/v1/experience/user-portfolio').catch(() => null);
  const _geoPromise = apiFetch('/api/v1/experience/rita/geography-overview');

  let data;
  try {
    data = await api('/api/v1/experience/fno/portfolio-analytics?mode=' + mode);
  } catch (e) {
    const msg = String(e?.message || '');
    if (/^No (active )?portfolio/i.test(msg)) {   // 404 detail from the analytics route
      const errEl = document.getElementById('analytics-mode-error');
      if (errEl) { errEl.textContent = 'No portfolio configured — set one in Portfolio Builder'; errEl.style.display = ''; }
    } else {
      console.error('Portfolio analytics API error:', e);
      document.getElementById('sidebar-as-of').textContent = 'API error — check server';
    }
    _renderAll();
    return;
  }
  if (!data) { _renderAll(); return; }   // production 401: api() is redirecting to sign-in

  // Map all 13 response fields to state
  state.portfolioMeta    = data.portfolio_meta    || {};
  setPortfolioCurrency(portfolioCurrency(state.portfolioMeta));   // F44 P2
  state.marketData       = data.market            || {};
  state.positions        = data.positions         || [];
  state.greeksData       = data.greeks            || [];
  state.netGreeks        = data.net_greeks        || {};
  state.portDelta        = data.net_delta         || {};
  state.scenarioLevels   = _normScenarioLevels(data.scenario_levels || {});
  state.payoffData       = data.payoff            || {};
  state.stressData       = data.stress            || [];
  state.hedgeQuality     = data.hedge_quality     || {};
  state.closedPositions  = data.closed_positions  || [];
  state.realizedPnl      = data.realized_pnl      || 0;
  state.marginData       = data.margin            || {};

  // Update sidebar as-of timestamp
  const asOf = data.portfolio_meta?.updated_at || '—';
  const asOfEl = document.getElementById('sidebar-as-of');
  if (asOfEl) asOfEl.textContent = asOf !== '—' ? `Updated ${asOf}` : '';

  // Resolve the parallel portfolio + geography fetches, build geo instrument list
  const [portData, geoData] = await Promise.all([_portPromise, _geoPromise]);
  _buildPortfolioGeoInstruments(portData, geoData);

  buildExpiryPills();
  _renderAll();
  fetchAndRenderRiskCharts();
  saveToday();
  syncPriceHistory().then(() => { renderScenarios(); });
}

function _renderAll() {
  updateRiskSections();
  renderGreeksCards();
  renderStressScenarios();
  renderScenarios();
  renderPayoffChart();
  initManoeuvre();
}

function _buildPortfolioGeoInstruments(portData, geoData) {
  // Build a name+region+close lookup from geography-overview
  const geoInstMap = {};
  if (geoData?.regions) {
    for (const reg of geoData.regions) {
      for (const inst of (reg.instruments ?? [])) {
        geoInstMap[inst.id] = { name: inst.name, region: reg.region, close: inst.close };
      }
    }
  }
  if (portData?.holdings?.length) {
    state.portfolioGeoInstruments = portData.holdings.map(h => {
      const geo = geoInstMap[h.instrument_id] || {};
      return {
        id:             h.instrument_id,
        name:           geo.name || h.instrument_id,
        region:         geo.region || 'Other',
        allocation_pct: h.allocation_pct,
        shares:         h.shares   ?? null,   // integer share count from portfolio builder
        cash:           holdingCash(h),       // leftover cash (portfolio currency; cash ?? cash_eur)
        close:          geo.close  ?? null,   // current market price
      };
    });
  } else {
    state.portfolioGeoInstruments = [];
  }
}

// Backward-compat shim — main.js imports fetchPositions for the Paper/Live toggle.
// Delegates to initApp so the single-fetch architecture is preserved.
export async function fetchPositions() {
  return initApp(state.analyticsMode);
}

export async function checkStatus() {
  try {
    const r = await fetch(apiBase() + '/health');
    const d = await r.json();
    document.getElementById('sdot').className = d.status === 'ok' ? 'status-dot ok' : 'status-dot';
    document.getElementById('stxt').textContent = d.status === 'ok' ? 'API online' : 'API error';
  } catch {
    document.getElementById('sdot').className = 'status-dot';
    document.getElementById('stxt').textContent = 'API offline';
  }
}
