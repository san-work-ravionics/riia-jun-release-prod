// ── FnO Dashboard — Entry Point ───────────────────────────────────────────────

// ingest ?token= from OAuth callback; migrate legacy localStorage key on first load
(function() {
  const p = new URLSearchParams(window.location.search);
  const t = p.get('token');
  if (t) {
    sessionStorage.setItem('auth_token', t);
    history.replaceState({}, '', window.location.pathname);
  } else {
    const legacy = localStorage.getItem('rita_token');
    if (legacy && !sessionStorage.getItem('auth_token')) {
      sessionStorage.setItem('auth_token', legacy);
      localStorage.removeItem('rita_token');
    }
  }
})();

import { initApp, checkStatus, fetchPositions } from './app-init.js';
import { randomUUID } from '../shared/utils.js';
import { ensureDevToken } from '../shared/dev-auth.js';

const SESSION_TRACE_ID = randomUUID();

async function apiFetch(url, opts = {}) {
    try {
        const res = await fetch(url, {
            ...opts,
            headers: { ...opts.headers, 'X-Request-ID': SESSION_TRACE_ID }
        });
        if (!res.ok) console.error('[RITA] fetch error', url, res.status, SESSION_TRACE_ID);
        return res.ok ? res.json() : null;
    } catch (e) {
        console.error('[RITA] fetch failed', url, e, SESSION_TRACE_ID);
        return null;
    }
}
import { state } from './state.js';
import { initNav, setUnderlying, setExpiry, _sectionLoaders } from './nav.js';
import { loadFnoMyPortfolio, fnoSelectInstrument } from './my-portfolio.js';
import { filterPos } from './positions.js';
import {
  manSelectTile,
  manSwitchTab,
  manDragStart,
  manDragEnd,
  manDropToGroup,
  manDropToPool,
  manRemove,
  manSaveName,
  manToggleView,
  manSaveCsv,
  manSaveSnapshot,
} from './manoeuvre.js';

// ── Window bindings for inline onclick= attributes ────────────────────────────
// Navigation / filter
window.toggleAnalyticsMode = function(mode) {
  state.analyticsMode = mode;
  const errEl = document.getElementById('analytics-mode-error');
  if (errEl) { errEl.textContent = ''; errEl.style.display = 'none'; }
  initApp(state.analyticsMode);
};
window.setUnderlying    = setUnderlying;
window.setExpiry        = setExpiry;
window.filterPos        = filterPos;
window.togglePaperMode  = function(isPaper) {
  state.paperMode = isPaper;
  const lbl = document.getElementById('paper-mode-label');
  if (lbl) lbl.textContent = isPaper ? 'Paper' : 'Live';
  fetchPositions();
};
// Manoeuvre
window.manSelectTile    = manSelectTile;
window.manSwitchTab     = manSwitchTab;
window.manDragStart     = manDragStart;
window.manDragEnd       = manDragEnd;
window.manDropToGroup   = manDropToGroup;
window.manDropToPool    = manDropToPool;
window.manRemove        = manRemove;
window.manSaveName      = manSaveName;
window.manToggleView    = manToggleView;
window.manSaveCsv       = manSaveCsv;
window.manSaveSnapshot  = manSaveSnapshot;

import { init as loadEquityScenarios } from '../scenarios/equity-scenarios.js';
import { initI18n, setLanguage, applyTranslations } from '../shared/i18n.js';
import { loadPortfolioHedge, phSetCoverage, phSetDuration, phToggleHedge, phPickStrategy, phSetScenarioTab } from './portfolio-hedge.js';
import { haSkipToVerdict } from './hedge-reasoning.js';
import { loadStudy } from './study.js';
import { loadExperiment, fetchExpData, switchExpTab } from './experiment.js';
import { loadHedgeWorkflow, hwGoToStep, hwSelectInstrument, hwRefreshStep } from './hedge-workflow.js';
import { hwToggleHedged, hwSelectStrategy, hwRerunAdvisor } from './hedge-workflow-recommendation.js';
import { hwSetCoverage, hwSetScenarioTab } from './hedge-workflow-whatif.js';
import { hwSave } from './hedge-workflow-save.js';

window.setLanguage        = setLanguage;
_sectionLoaders['equity-scenarios'] = loadEquityScenarios;
window.fnoSelectInstrument = fnoSelectInstrument;

// Overview Portfolio Hedge block (ph-* DOM inside #page-overview): loadPortfolioHedge() is
// called on every boot (see window 'load' handler below); ph* handlers are used by inline
// onclick/oninput in fno.html. NOT a separate page.
window.loadPortfolioHedge = loadPortfolioHedge;
window.phSetCoverage      = phSetCoverage;
window.phSetDuration      = phSetDuration;
window.phToggleHedge      = phToggleHedge;
window.phPickStrategy     = phPickStrategy;
window.phSetScenarioTab   = phSetScenarioTab;

// Hedge Advisor reasoning screen now lives in the Recommendation step (Skip button handler).
window.haSkipToVerdict    = haSkipToVerdict;

// ── Unified Hedge Workflow (F39 Phase 2/3) ───────────────────────────────────
_sectionLoaders['hedge-workflow'] = loadHedgeWorkflow;
window.loadHedgeWorkflow   = loadHedgeWorkflow;
window.hwGoToStep          = hwGoToStep;
window.hwSelectInstrument  = hwSelectInstrument;
window.hwRefreshStep       = hwRefreshStep;
// Phase 3 step modules
window.hwToggleHedged      = hwToggleHedged;
window.hwSelectStrategy    = hwSelectStrategy;
window.hwRerunAdvisor      = hwRerunAdvisor;
window.hwSetCoverage       = hwSetCoverage;
window.hwSetScenarioTab    = hwSetScenarioTab;
window.hwSave              = hwSave;

// Redirect aliases — old nav keys stay registered in _sectionLoaders but now
// deep-link into the unified workflow (Migration Plan; see nav.js comment for
// the exact old-key -> step mapping). hedge/equity-hedge previously had no
// _sectionLoaders entry (nav.js special-cased them directly) — now registered
// here too so any direct `_sectionLoaders['hedge']()`-style call also redirects.
function _hwAlias(step) {
  // loadHedgeWorkflow(step) enters the step itself once the saved plan has resolved;
  // no separate hwGoToStep() call (it raced the async load and was overridden by last_step).
  return function () {
    return loadHedgeWorkflow(step);
  };
}
_sectionLoaders['hedge'] = _hwAlias('exposure');
_sectionLoaders['hedge-advisor'] = _hwAlias('recommendation');
_sectionLoaders['equity-hedge'] = _hwAlias('recommendation');
_sectionLoaders['portfolio-hedge'] = _hwAlias('exposure');

// Study — Rolling Futures Backtest
_sectionLoaders['study'] = loadStudy;

// Experiment — Nifty Options Strangle Backtest
_sectionLoaders['experiment'] = loadExperiment;
window.loadExperiment = loadExperiment;
window.fetchExpData = fetchExpData;
window.switchExpTab = switchExpTab;

// My Portfolio CTA — navigates to the Hedge Workflow (Exposure step) from Overview.
// Was "navItem = ...[data-section=...]" (stale selector — nav markup uses
// data-page, not data-section, so this lookup was already always null before
// this change); now points at the real hedge-workflow nav item/section.
window.fnoMpGoHedge = function () {
  document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.section').forEach(el => el.classList.remove('active'));
  const navItem = document.querySelector('.nav-item[data-page="hedge-workflow"]');
  if (navItem) navItem.classList.add('active');
  const section = document.getElementById('page-hedge-workflow');
  if (section) section.classList.add('active');
  if (typeof _sectionLoaders['hedge-workflow'] === 'function') {
    _sectionLoaders['hedge-workflow']('exposure');
  }
};

// ── Boot ──────────────────────────────────────────────────────────────────────
initI18n(); applyTranslations();
window.addEventListener('load', async () => {
  await ensureDevToken();
  initNav();
  initApp('real');
  checkStatus();
  loadPortfolioHedge();
  // Poll API status every 30s
  setInterval(checkStatus, 30000);
});
