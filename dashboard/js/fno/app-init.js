// ── FnO App Initialisation ────────────────────────────────────────────────────

import { apiBase, RITA_API_KEY } from './api.js';
import { state } from './state.js';
import { buildExpiryPills } from './nav.js';
import { renderDashboard } from './dashboard.js';
import { renderGreeksCards, renderGreeksTable, updateRiskSections } from './greeks.js';
import { renderStressScenarios } from './stress.js';
import { renderPayoffChart } from './payoff.js';
import { saveToday, syncPriceHistory, renderScenarios } from './rr.js';
import { renderPortfolioHedgeRadar } from './hedge.js';
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
  renderGreeksTable();
  renderStressScenarios();
  highlightRiskChart();
});

// window.RITA_API_BASE can be set by the host page to point at a non-origin
// API server (e.g. staging). Defaults to '' = same origin.

export async function initApp(mode = 'mock') {
  state.analyticsMode = mode;

  const url = apiBase() + '/api/v1/experience/fno/portfolio-analytics?mode=' + mode;
  const headers = RITA_API_KEY ? { 'X-API-Key': RITA_API_KEY } : {};

  const token = sessionStorage.getItem('auth_token');
  if (token) headers['Authorization'] = `Bearer ${token}`;

  // Fire portfolio + geography fetches in parallel with the main analytics call
  const _token = sessionStorage.getItem('auth_token');
  const _portHeaders = { ...(RITA_API_KEY ? { 'X-API-Key': RITA_API_KEY } : {}), ...(_token ? { Authorization: `Bearer ${_token}` } : {}) };
  const _portPromise = fetch(apiBase() + '/api/v1/experience/user-portfolio', { headers: _portHeaders })
    .then(r => r.ok ? r.json() : null).catch(() => null);
  const _geoPromise = fetch(apiBase() + '/api/v1/experience/rita/geography-overview')
    .then(r => r.ok ? r.json() : null).catch(() => null);

  let rawResp = null;
  try {
    rawResp = await fetch(url, { headers });
  } catch (e) {
    console.error('Portfolio analytics fetch failed:', e);
    document.getElementById('sidebar-as-of').textContent = 'API error — check server';
    _renderAll();
    return;
  }

  if (!rawResp.ok) {
    const errEl = document.getElementById('analytics-mode-error');
    if (rawResp.status === 401) {
      window.location.href = '/';
      return;
    } else if (rawResp.status === 404) {
      if (errEl) { errEl.textContent = 'No portfolio configured — set one in Portfolio Builder'; errEl.style.display = ''; }
    } else {
      console.error('Portfolio analytics API error:', rawResp.status);
      document.getElementById('sidebar-as-of').textContent = 'API error — check server';
    }
    _renderAll();
    return;
  }

  let data;
  try {
    data = await rawResp.json();
  } catch (e) {
    console.error('Portfolio analytics JSON parse error:', e);
    document.getElementById('sidebar-as-of').textContent = 'API error — check server';
    _renderAll();
    return;
  }

  // Map all 13 response fields to state
  state.portfolioMeta    = data.portfolio_meta    || {};
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
  renderDashboard();
  updateRiskSections();
  renderGreeksCards();
  renderGreeksTable();
  renderStressScenarios();
  renderScenarios();
  renderPayoffChart();
  renderPortfolioHedgeRadar();
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
        cash_eur:       h.cash_eur ?? null,   // leftover cash from portfolio builder
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
