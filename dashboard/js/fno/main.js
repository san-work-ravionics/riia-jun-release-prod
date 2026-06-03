// ── FnO Dashboard — Entry Point ───────────────────────────────────────────────

// migrate legacy rita_token → auth_token (one-time, silent)
(function() {
  const legacy = sessionStorage.getItem('rita_token');
  if (legacy && !sessionStorage.getItem('auth_token')) {
    sessionStorage.setItem('auth_token', legacy);
    sessionStorage.removeItem('rita_token');
  }
})();

// ingest ?token= from OAuth callback
(function() {
  const p = new URLSearchParams(window.location.search);
  const t = p.get('token');
  if (t) {
    sessionStorage.setItem('auth_token', t);
    history.replaceState({}, '', window.location.pathname);
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
import { loadFnoMyPortfolio } from './my-portfolio.js';
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

import { loadEquityHedge } from './equity_hedge.js';
import { initI18n, setLanguage, applyTranslations } from '../shared/i18n.js';
import { loadPortfolioHedge, phSetCoverage, phSetDuration, phToggleHedge, phSetTotalEur, phPickStrategy, phSetScenarioTab } from './portfolio-hedge.js';

window.setLanguage = setLanguage;
window.loadEquityHedge = loadEquityHedge;

// My Portfolio section loader
_sectionLoaders['my-portfolio']      = loadFnoMyPortfolio;
window.loadFnoMyPortfolio = loadFnoMyPortfolio;

// Portfolio Hedge wizard
_sectionLoaders['portfolio-hedge'] = loadPortfolioHedge;
window.loadPortfolioHedge = loadPortfolioHedge;
window.phSetCoverage      = phSetCoverage;
window.phSetDuration      = phSetDuration;
window.phToggleHedge      = phToggleHedge;
window.phSetTotalEur      = phSetTotalEur;
window.phPickStrategy     = phPickStrategy;
window.phSetScenarioTab   = phSetScenarioTab;

// ── Boot ──────────────────────────────────────────────────────────────────────
initI18n(); applyTranslations();
window.addEventListener('load', async () => {
  await ensureDevToken();
  initNav();
  initApp();
  checkStatus();
  // Poll API status every 30s
  setInterval(checkStatus, 30000);
});
