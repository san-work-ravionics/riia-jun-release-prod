// ── RITA Dashboard — main.js (entry point) ─────────────────
// ── Token ingestion from ?token= URL param ─────────────────
const _urlParams = new URLSearchParams(window.location.search);
const _urlToken = _urlParams.get('token');
if (_urlToken) {
  sessionStorage.setItem('auth_token', _urlToken);
  history.replaceState({}, document.title, window.location.pathname);
}

import { api } from './api.js';
import { show, warmupChat, _sectionLoaders, getCurrentSection } from './nav.js';
import { loadOverviewCommentary } from './commentary.js';
import { loadHealth, loadPerfSummary, loadDrift, loadProgress } from './health.js';
import { switchMsTab, loadMarketSignals, loadGoalHint } from './market-signals.js';
import { loadPerformance } from './performance.js';
import { loadExplain } from './explainability.js';
import { loadRisk } from './risk.js';
import { loadExport, runGoal, runMarket, runStrategy, runFullPipeline, doReset } from './export.js';
import { loadTrades, downloadTradeJournal } from './trades.js';
import { loadScenarios, runScenarioBacktest, setScenarioPeriod } from './scenarios.js';
import { loadAgentPanel, agentPanelStep, resetAgentPanel, approveAgentProposal, rejectAgentProposal } from './agent-panel.js';
import { loadAiCompliance, switchAcTab } from './ai-compliance.js';
import { loadTechnicalAnalysis } from './technical-analysis.js';
import { loadLearnings, toggleLearnCard, switchAgentTab } from './learnings.js';
import { loadStrategyComparison, scSelectInstrument, scSelectYear } from './strategy-comparison.js';
import { useChip, sendChatMsg, clearChat, updateChips, showAlerts, refreshChatChips } from './chat.js';
import { openChartModal, closeChartModal } from './chart-modal.js';
import { initI18n, setLanguage, applyTranslations } from '../shared/i18n.js';
import { ensureDevToken } from '../shared/dev-auth.js';
import { loadMyPortfolio, savePortfolio } from './my-portfolio.js';
import { loadAgentPerformance, setAgentPerfPeriod, loadAgentPerfTimeline, loadRLScorecards } from './agent-performance.js';
import { loadPortfolioBuilder, pbToggleInstrument, pbSelectAllRegion, pbClearAllRegion, pbSortTable, pbApplyGoalPreset, pbToggleDraftItem, pbBuildFromDraft, pbClearBasket, pbBuildPortfolio, pbSetAlloc } from './portfolio-builder.js?v=4';

// ── Populate section loaders map ───────────────────────────
_sectionLoaders.market            = async () => { refreshChatChips(); clearChat(); runMarket(); const data = await warmupChat(); if (data) { updateChips(data.chips); showAlerts(data.alerts); } };
_sectionLoaders['market-signals'] = loadMarketSignals;
_sectionLoaders.goal              = loadGoalHint;
_sectionLoaders.scenarios         = loadScenarios;
_sectionLoaders['agent-panel']    = loadAgentPanel;
_sectionLoaders['ai-compliance']  = loadAiCompliance;
_sectionLoaders.performance       = loadPerformance;
_sectionLoaders.explain           = loadExplain;
_sectionLoaders.risk              = loadRisk;
_sectionLoaders.trades            = loadTrades;
_sectionLoaders.export            = loadExport;
_sectionLoaders['technical-analysis'] = loadTechnicalAnalysis;
_sectionLoaders.learnings             = loadLearnings;
_sectionLoaders['strategy-compare']    = loadStrategyComparison;
_sectionLoaders['my-portfolio']        = loadMyPortfolio;
_sectionLoaders['portfolio-builder']   = loadPortfolioBuilder;
_sectionLoaders['agent-performance']   = loadAgentPerformance;

// ── Expose to window for inline HTML onclick attributes ────
window.show                = show;
window.selectGeoInstrument = selectGeoInstrument;
window.switchMsTab         = switchMsTab;
window.runGoal            = runGoal;
window.runMarket          = runMarket;
window.runStrategy        = runStrategy;
window.runFullPipeline    = runFullPipeline;
window.doReset            = doReset;
window.downloadTradeJournal = downloadTradeJournal;
window.setScenarioPeriod  = setScenarioPeriod;
window.runScenarioBacktest = runScenarioBacktest;
window.agentPanelStep        = agentPanelStep;
window.resetAgentPanel       = resetAgentPanel;
window.approveAgentProposal  = approveAgentProposal;
window.rejectAgentProposal   = rejectAgentProposal;
window.loadAiCompliance   = loadAiCompliance;
window.switchAcTab        = switchAcTab;
window.useChip            = useChip;
window.sendChatMsg        = sendChatMsg;
window.clearChat          = clearChat;
window.openChartModal     = openChartModal;
window.closeChartModal    = closeChartModal;
// Reload buttons for individual sections
window.loadMarketSignals  = loadMarketSignals;
window.loadGoalHint       = loadGoalHint;
window.loadOverviewCommentary = loadOverviewCommentary;
window.loadPerformance    = loadPerformance;
window.loadExplain        = loadExplain;
window.loadRisk           = loadRisk;
window.loadTrades         = loadTrades;
window.loadTechnicalAnalysis = loadTechnicalAnalysis;
window.loadLearnings      = loadLearnings;
window.toggleLearnCard          = toggleLearnCard;
window.switchAgentTab           = switchAgentTab;
window.loadStrategyComparison   = loadStrategyComparison;
window.scSelectInstrument       = scSelectInstrument;
window.scSelectYear             = scSelectYear;
window.setLanguage        = setLanguage;
window.loadMyPortfolio    = loadMyPortfolio;
window.savePortfolio      = savePortfolio;
window.loadPortfolioBuilder = loadPortfolioBuilder;
window.loadAgentPerformance = loadAgentPerformance;
window.setAgentPerfPeriod = setAgentPerfPeriod;
window.loadAgentPerfTimeline = loadAgentPerfTimeline;
window.loadRLScorecards = loadRLScorecards;
window.pbToggleInstrument   = pbToggleInstrument;
window.pbSelectAllRegion    = pbSelectAllRegion;
window.pbClearAllRegion     = pbClearAllRegion;
window.pbSortTable          = pbSortTable;
window.pbApplyGoalPreset    = pbApplyGoalPreset;
window.pbToggleDraftItem    = pbToggleDraftItem;
window.pbBuildFromDraft     = pbBuildFromDraft;
window.pbClearBasket        = pbClearBasket;
window.pbBuildPortfolio     = pbBuildPortfolio;
window.pbSetAlloc           = pbSetAlloc;

// ── Refresh all home KPIs & active section ─────────────────
async function refresh() {
  await Promise.all([loadHealth(), loadPerfSummary(), loadDrift(), loadProgress()]);
  const current = getCurrentSection();
  if (_sectionLoaders[current]) _sectionLoaders[current]();
}

// Expose refresh so export.js can call it via window._ritaRefresh
window._ritaRefresh = refresh;

async function selectGeoInstrument(id) {
  localStorage.setItem('ritaInstrument', id);
  document.querySelectorAll('.geo-kpi').forEach(el =>
    el.classList.toggle('geo-kpi-active', el.dataset.id === id)
  );
  try { await api('/api/v1/instrument/select', 'POST', { instrument_id: id }).catch(e => console.error('[RITA] instrument select failed', e)); } catch (_) {}
  const section = getCurrentSection();
  if (section === 'market') {
    clearChat();
    const data = await warmupChat(true);
    if (data) { updateChips(data.chips); showAlerts(data.alerts); }
  }
  await loadActiveInstrument();
  const instrumentSections = new Set(['trades', 'performance', 'scenarios', 'risk', 'market-signals', 'diagnostics', 'explain', 'technical-analysis', 'learnings', 'strategy-compare']);
  await Promise.all([
    loadHealth(), loadPerfSummary(), loadDrift(), loadProgress(), loadMarketSignals(),
    ...(instrumentSections.has(section) && _sectionLoaders[section] ? [_sectionLoaders[section]()] : []),
  ]);
}

// ── Active instrument pill ─────────────────────────────────
async function loadActiveInstrument() {
  try {
    const inst = await api('/api/v1/instrument/active');
    if (!inst || !inst.id) return;
    const pill = document.getElementById('inst-pill');
    document.getElementById('inst-pill-flag').textContent = inst.flag || '';
    document.getElementById('inst-pill-name').textContent = inst.name || inst.id;
    document.getElementById('inst-pill-exch').textContent = inst.exchange ? `· ${inst.exchange}` : '';
    pill.style.display = 'flex';
    document.title = `RITA — ${inst.name || inst.id}`;
  } catch { /* silently skip if API not ready */ }
}

// ── Init ───────────────────────────────────────────────────
initI18n(); applyTranslations();
window.addEventListener('load', async () => {
  await ensureDevToken();
  refresh(); loadActiveInstrument(); loadMarketSignals();
});
