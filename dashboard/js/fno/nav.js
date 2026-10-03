// ── Navigation + underlying/expiry selectors ──────────────────────────────────
import { state } from './state.js';

// Section loaders registry — modules register themselves in main.js
export const _sectionLoaders = {};
import { renderDashboard } from './dashboard.js';
import { renderGreeksCards, renderGreeksTable, updateRiskSections } from './greeks.js';
import { renderStressScenarios } from './stress.js';
import { renderPayoffChart } from './payoff.js';
import { renderScenarios } from './rr.js';
import { renderHedgeRadar } from './hedge.js';
import { initManoeuvre, renderMonthTiles } from './manoeuvre.js';
import { loadEquityHedge } from './equity_hedge.js';

// ── Hedge Workflow redirect aliases (F39 Phase 2) ───────────────────────────
// Old nav keys stay registered (not deleted) but now deep-link into the
// unified hedge-workflow shell instead of their own standalone pages, per the
// core design's Migration Plan ("old nav/section keys stay registered ... but
// point to a thin alias loader that calls show('hedge-workflow') and
// deep-links to the matching step via hwGoToStep()"). Mapped Phase 2 step per
// closest semantic match (Recommendation/What-if/Save are empty stubs until
// Phase 3 ships their content — see task-brief-20261003-1114 Engineer log):
//   hedge           -> exposure        (Hedge Radar: current hedge state)
//   hedge-advisor   -> recommendation  (Advisor: recommend a strategy)
//   equity-hedge    -> recommendation  (equity strategy pick/sizing)
//   portfolio-hedge -> exposure        (was the single-page workflow entry)
const HEDGE_WORKFLOW_ALIASES = {
  hedge: 'exposure',
  'hedge-advisor': 'recommendation',
  'equity-hedge': 'recommendation',
  'portfolio-hedge': 'exposure',
};

export function initNav() {
  document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', () => {
      const page = item.dataset.page;
      document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
      item.classList.add('active');
      document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));

      const aliasStep = HEDGE_WORKFLOW_ALIASES[page];
      if (aliasStep) {
        const hwSection = document.getElementById('page-hedge-workflow');
        if (hwSection) hwSection.classList.add('active');
        if (_sectionLoaders['hedge-workflow']) { _sectionLoaders['hedge-workflow'](); }
        if (typeof window.hwGoToStep === 'function') { window.hwGoToStep(aliasStep); }
        return;
      }

      document.getElementById('page-' + page).classList.add('active');
      if (_sectionLoaders[page]) { _sectionLoaders[page](); }
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
  updateRiskSections();
  renderGreeksCards();
  renderGreeksTable();
  renderStressScenarios();
  renderPayoffChart();
  renderScenarios();
  renderHedgeRadar();
  initManoeuvre();
  // If equity hedge page is visible, reload data for the new instrument
  const ehPage = document.getElementById('page-equity-hedge');
  if (ehPage?.classList.contains('active')) {
    loadEquityHedge(true);
  }
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
