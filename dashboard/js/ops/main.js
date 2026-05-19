// ── Ops Dashboard — Entry Point ───────────────────────────────────────────────
import { nav, sectionLoaders, loadSection } from './nav.js';
import { loadOverview } from './overview.js';
import { loadMonitoring } from './monitoring.js';
import { loadCICD } from './cicd.js';
import { loadDeploy } from './deploy.js';
import { loadObservability } from './observability.js';
import { loadChat } from './chat.js';
import { loadDailyOps, triggerSnapshot, loadInstruments, toggleInstrument, saveInstruments, searchInstrument, onboardInstrument } from './daily-ops.js';
import { refreshSidebar } from './sidebar.js';
import { loadTestResults } from './test-results.js';
import { loadUsers, saveUserRoles } from './users.js';
import { loadAgentBuilds, submitTokenEstimate, toggleEstimateWidget, closeChartModal } from './agent-builds.js';
import { loadGameCompliance, toggleGcDetail } from './game-compliance.js';
import { loadAlerts } from './alerts.js';
import { loadSourceAvailability } from './source-availability.js';
import { loadFunctionalKPIs } from './functional-kpis.js';
import { loadUtilities, runGoal, runMarket, runStrategy, runFullPipeline, doReset } from './utils.js';
import { loadApiMetrics, filterApiMetrics } from './api-metrics.js';
import { initI18n, setLanguage, applyTranslations } from '../shared/i18n.js';

// ── Populate section loader registry ─────────────────────────────────────────
sectionLoaders['overview']             = loadOverview;
sectionLoaders['monitoring']           = loadMonitoring;
sectionLoaders['cicd']                 = loadCICD;
sectionLoaders['test']                 = loadTestResults;
sectionLoaders['deploy']               = loadDeploy;
sectionLoaders['observability']        = loadObservability;
sectionLoaders['chat']                 = loadChat;
sectionLoaders['dailyops']             = () => { loadDailyOps(); loadInstruments(); };
sectionLoaders['users']                = loadUsers;
sectionLoaders['agent-builds']         = loadAgentBuilds;
sectionLoaders['game-compliance']      = loadGameCompliance;
sectionLoaders['alerts']               = loadAlerts;
sectionLoaders['source-availability']  = loadSourceAvailability;
sectionLoaders['functional-kpis']      = loadFunctionalKPIs;
sectionLoaders['api-metrics']          = loadApiMetrics;

// ── Window bindings for inline onclick= attributes ────────────────────────────
window.nav                    = nav;
window.refreshTestResults     = loadTestResults;
window.triggerSnapshot        = triggerSnapshot;
window.loadChat               = loadChat;
window.loadDailyOps           = loadDailyOps;
window.toggleInstrument       = toggleInstrument;
window.saveInstruments        = saveInstruments;
window.searchInstrument       = searchInstrument;
window.onboardInstrument      = onboardInstrument;
window.loadUsers              = loadUsers;
window.saveUserRoles          = saveUserRoles;
window.loadAgentBuilds        = loadAgentBuilds;
window.submitTokenEstimate    = submitTokenEstimate;
window.toggleEstimateWidget   = toggleEstimateWidget;
window.closeChartModal        = closeChartModal;
window.loadGameCompliance     = loadGameCompliance;
window.toggleGcDetail         = toggleGcDetail;
window.loadAlerts             = loadAlerts;
window.loadSourceAvailability = loadSourceAvailability;
window.loadFunctionalKPIs     = loadFunctionalKPIs;
window.runGoal                = runGoal;
window.runMarket              = runMarket;
window.runStrategy            = runStrategy;
window.runFullPipeline        = runFullPipeline;
window.doReset                = doReset;
window.loadApiMetrics         = loadApiMetrics;
window.filterApiMetrics       = filterApiMetrics;
window.setLanguage            = setLanguage;

// ── Boot ──────────────────────────────────────────────────────────────────────
initI18n(); applyTranslations();
document.addEventListener('DOMContentLoaded', () => {
  loadOverview();
  loadAlerts();
  loadSourceAvailability();
  loadFunctionalKPIs();
  setInterval(refreshSidebar, 30000);
});
