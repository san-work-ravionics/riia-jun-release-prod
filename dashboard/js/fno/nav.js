// ── Navigation + underlying/expiry selectors ──────────────────────────────────
import { state } from './state.js';
import { renderDashboard } from './dashboard.js';
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
import { renderScenarios } from './rr.js';
import { renderHedgeRadar, loadHedgeHistory } from './hedge.js';
import { initManoeuvre, renderMonthTiles } from './manoeuvre.js';

export function initNav() {
  document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', () => {
      document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
      item.classList.add('active');
      document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
      document.getElementById('page-' + item.dataset.page).classList.add('active');
      if (item.dataset.page === 'history') loadHedgeHistory();
    });
  });
}

export function setUnderlying(und) {
  state.currentUnd = und;
  // Update sidebar market items active state
  document.querySelectorAll('.mkt-price-item[data-und]').forEach(el => {
    el.classList.toggle('active', el.dataset.und === und);
  });
  buildExpiryPills();
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
  renderPayoffChart();
  renderScenarios();
  renderHedgeRadar();
  initManoeuvre();
}

export function buildExpiryPills() {
  const expiries = [...new Set(state.positions.map(p => p.exp))].sort();
  const container = document.getElementById('exp-pills-container');
  container.innerHTML =
    `<button class="exp-pill${state.currentExpiry === 'ALL' ? ' active' : ''}" onclick="setExpiry('ALL',this)">All</button>` +
    expiries.map(e =>
      `<button class="exp-pill${state.currentExpiry === e ? ' active' : ''}" onclick="setExpiry('${e}',this)">${e}</button>`
    ).join('');
}

export function setExpiry(exp, btn) {
  state.currentExpiry = exp;
  document.querySelectorAll('.exp-pill').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
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
  renderPayoffChart();
  renderScenarios();
  renderHedgeRadar();
  // Manoeuvre has its own month selector — only refresh the tiles summary
  renderMonthTiles();
}
