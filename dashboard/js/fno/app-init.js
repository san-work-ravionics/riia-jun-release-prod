// ── FnO App Initialisation — extracted from fno/api.js god module ─────────────
// FC-IMP verified exports:
//   apiBase       — fno/api.js re-exports from shared/api.js ✓
//   state         — fno/state.js export const state ✓
//   buildExpiryPills — fno/nav.js export function buildExpiryPills ✓
//   renderDashboard, renderDailyProgress — fno/dashboard.js ✓
//   renderPositionsKpis, renderPositionsTable — fno/positions.js ✓
//   renderMarginKpis, updateMarginSections, renderMarginTables, renderClosedPositions — fno/margin.js ✓
//   renderGreeksCards, renderGreeksTable, updateRiskSections — fno/greeks.js ✓
//   renderStressScenarios — fno/stress.js ✓
//   renderPayoffChart — fno/payoff.js ✓
//   saveToday, syncPriceHistory, renderScenarios — fno/rr.js ✓
//   renderHedgeRadar — fno/hedge.js ✓
//   initManoeuvre — fno/manoeuvre.js ✓

import { apiBase } from './api.js';
import { state } from './state.js';
import { buildExpiryPills } from './nav.js';
import { loadEquityHedge } from './equity_hedge.js';
import {
  renderDashboard,
  renderDailyProgress,
} from './dashboard.js';
import { renderPositionsKpis, renderPositionsTable } from './positions.js';
import {
  renderMarginKpis,
  updateMarginSections,
  renderMarginTables,
  renderClosedPositions,
} from './margin.js';
import { renderGreeksCards, renderGreeksTable, updateRiskSections } from './greeks.js';
import { renderStressScenarios } from './stress.js';
import { renderPayoffChart } from './payoff.js';
import { saveToday, syncPriceHistory, renderScenarios } from './rr.js';
import { renderHedgeRadar } from './hedge.js';
import { initManoeuvre } from './manoeuvre.js';

export async function fetchPositions() {
  const mode = state.paperMode ? 'paper' : 'live';
  try {
    const resp = await fetch(apiBase() + `/api/v1/portfolio/positions?mode=${mode}`);
    if (!resp.ok) throw new Error(`API ${resp.status}`);
    state.positions = await resp.json();
  } catch (e) {
    console.error('fetchPositions error:', e);
    state.positions = [];
  }
  buildExpiryPills();
  renderPositionsKpis();
  renderPositionsTable();
}

// window.RITA_API_BASE can be set by the host page to point at a non-origin
// API server (e.g. staging). Defaults to '' = same origin.

export async function initApp() {
  try {
    const resp = await fetch(apiBase() + '/api/v1/portfolio/summary');
    if (!resp.ok) throw new Error(`API ${resp.status}`);
    const d = await resp.json();

    state.marketData      = d.market || {};
    state.positions       = d.positions || [];
    buildExpiryPills();
    state.greeksData      = d.greeks || [];
    state.closedPositions = d.closed_positions || [];
    state.realizedPnl     = d.realized_pnl || 0;
    state.portDelta       = d.net_delta || {};
    state.netGreeks       = d.net_greeks || {};
    state.scenarioLevels  = d.scenario_levels || {};
    state.marginData      = d.margin || {};
    state.stressData      = d.stress || [];
    state.payoffData      = d.payoff || {};
    state.hedgeQuality    = d.hedge_quality || {};

    // Update sidebar
    const asOf = d.last_date || d.as_of || '';
    document.getElementById('sidebar-as-of').textContent = asOf ? `As of ${asOf}` : '';

  } catch (e) {
    console.error('Portfolio API error:', e);
    document.getElementById('sidebar-as-of').textContent = 'API error — check server';
  }

  // Fetch positions (paper or live depending on state.paperMode)
  await fetchPositions();

  // Render all sections
  saveToday();
  syncPriceHistory().then(() => { renderScenarios(); renderDailyProgress(); });
  renderDashboard();
  renderPositionsKpis();
  renderPositionsTable();
  renderClosedPositions();
  renderMarginKpis();
  updateMarginSections();
  renderMarginTables();
  updateRiskSections();
  renderGreeksCards();
  renderGreeksTable();
  renderStressScenarios();
  renderScenarios();
  renderPayoffChart();
  renderHedgeRadar();
  initManoeuvre();

  // Re-render all pages when ASML equity hedge data is injected into state
  document.addEventListener('rita:asml-state-updated', () => {
    buildExpiryPills();
    renderDashboard();
    renderPositionsKpis();
    renderPositionsTable();
    renderClosedPositions();
    renderMarginKpis();
    updateMarginSections();
    renderMarginTables();
  });

  // Auto-load equity hedge in background so ASML data flows to all pages
  loadEquityHedge(false).catch(() => {});
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
