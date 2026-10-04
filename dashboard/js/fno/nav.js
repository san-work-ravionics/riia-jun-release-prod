// ── Navigation + underlying/expiry selectors ──────────────────────────────────
import { state } from './state.js';

// Section loaders registry — modules register themselves in main.js
export const _sectionLoaders = {};
import { renderGreeksCards, updateRiskSections } from './greeks.js';
import { renderStressScenarios } from './stress.js';
import { renderPayoffChart } from './payoff.js';
import { renderScenarios } from './rr.js';
import { initManoeuvre, renderMonthTiles } from './manoeuvre.js';

// ── Hedge Workflow redirect aliases (F39 Phase 2) ───────────────────────────
// Old nav keys stay registered (not deleted) but now deep-link into the
// unified hedge-workflow shell instead of their own standalone pages, per the
// core design's Migration Plan ("old nav/section keys stay registered ... but
// point to a thin alias loader that calls show('hedge-workflow') and
// deep-links to the matching step via loadHedgeWorkflow(stepOverride)"). Mapped
// step per closest semantic match (all four steps are built as of Phase 3):
//   hedge           -> exposure        (Hedge Radar: current hedge state)
//   hedge-advisor   -> recommendation  (Advisor: recommend a strategy)
//   equity-hedge    -> recommendation  (equity strategy pick/sizing)
//   portfolio-hedge -> exposure        (was the single-page workflow entry)
// Dormant reachability: no nav item or URL/hash routing targets these keys any more (the
// sidebar items were removed); kept as zero-cost defence for programmatic/legacy callers.
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
        // Single call: the loader enters aliasStep itself (stepOverride wins over the
        // saved last_step). A separate hwGoToStep() afterwards raced the async load.
        if (_sectionLoaders['hedge-workflow']) { _sectionLoaders['hedge-workflow'](aliasStep); }
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
  updateRiskSections();
  renderGreeksCards();
  renderStressScenarios();
  renderPayoffChart();
  renderScenarios();
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
  updateRiskSections();
  renderGreeksCards();
  renderStressScenarios();
  renderPayoffChart();
  renderScenarios();
  // Manoeuvre has its own month selector — only refresh the tiles summary
  renderMonthTiles();
}
