import { createShow } from './nav.js';
import { loadUnderstand, runUnderstand, vizSelectInstrument, openVizModal, closeVizModal, runPortfolioOverview } from './understand.js';
import { loadDashboard } from './dashboard.js';
import { runBuild, runReuse, resetSession, checkStatus, loadInstruments, loadActiveInstrument } from './pipeline.js';
import { loadPerformance, switchPerfTab } from './performance.js';
import { loadRisk } from './risk.js';
import { loadTrades } from './trades.js';
import { loadExplain } from './explain.js';
import { loadScenariosPage, runPortfolioScenario } from './scenarios.js';
import { loadTraining, switchTrainTab } from './training.js';
import { loadChangelog, saveChangelog } from './changelog.js';
import { loadObservability } from './observability.js';
import { loadMCP } from './mcp.js';
import { loadExport, pingAPI, dlJSON } from './export.js';
import { loadExperimentResults, downloadExperimentResults } from './experiment-results.js';
import { loadTradeDiagnostics } from './trade-diagnostics.js';
import { loadModelTrainProgress } from './model-train-progress.js';
import { loadModelObservability } from './model-observability.js';
import { loadModelMcp } from './model-mcp.js';
import { loadModelAudit } from './model-audit.js';
import { closeChartModal } from './utils.js';
import { initI18n, setLanguage, applyTranslations } from '../shared/i18n.js';

// ── Section loader registry ──────────────────────────────────────────────────
const _sectionLoaders = {
  'understand':           loadUnderstand,
  'dashboard':            loadDashboard,
  'pipeline':             () => {}, // pipeline nav click does not auto-load; checkStatus polls on interval
  'performance':          loadPerformance,
  'risk':                 loadRisk,
  'trades':               loadTrades,
  'explain':              loadExplain,
  'scenarios':            loadScenariosPage,
  'training':             loadTraining,
  'changelog':            loadChangelog,
  'observability':        loadObservability,
  'mcp':                  loadMCP,
  'export':               loadExport,
  'experiment-results':   loadExperimentResults,
  'trade-diagnostics':    loadTradeDiagnostics,
  'model-train-progress': loadModelTrainProgress,
  'model-observability':  loadModelObservability,
  'model-mcp':            loadModelMcp,
  'model-audit':          loadModelAudit,
};

// ── Section switching ─────────────────────────────────────────────────────────
const show = createShow(_sectionLoaders);

// ── Window bindings (module scope — before DOMContentLoaded) ─────────────────
// Must be at module scope so onclick="" attributes work immediately on nav click.
window.show                   = show;
window.runUnderstand          = runUnderstand;
window.vizSelectInstrument    = vizSelectInstrument;
window.openVizModal           = openVizModal;
window.closeVizModal          = closeVizModal;
window.closeChartModal        = closeChartModal;
window.runPortfolioOverview   = runPortfolioOverview;
window.runBuild               = runBuild;
window.runReuse               = runReuse;
window.resetSession           = resetSession;
window.saveChangelog          = saveChangelog;
window.pingAPI                = pingAPI;
window.dlJSON                 = dlJSON;
window.switchPerfTab          = switchPerfTab;
window.switchTrainTab         = switchTrainTab;
window.runPortfolioScenario   = runPortfolioScenario;
window.downloadExperimentResults = downloadExperimentResults;
window.setLanguage               = setLanguage;
window.loadMCP                   = loadMCP;

// ── Keyboard escape handlers (replicate inline listeners from ds.html) ────────
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeChartModal(); });
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeVizModal(); });

// ── Init (DOMContentLoaded) ───────────────────────────────────────────────────
initI18n(); applyTranslations();
// Replicates the inline init() function from ds.html verbatim.
document.addEventListener('DOMContentLoaded', async () => {
  // Default simulation end date to today so charts always show current data
  const today = new Date().toISOString().slice(0, 10);
  ['b-end', 'r-end'].forEach(id => {
    const el = document.getElementById(id);
    if (el && !el.value) el.value = today;
  });

  await loadInstruments();
  await checkStatus();
  setInterval(checkStatus, 30000);
  await loadActiveInstrument();
  loadUnderstand();  // default landing section
});
