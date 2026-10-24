// ── Invest Game App — main.js (entry point) ─────────────────────────────────
import { show, registerLoader, toggleSidebar } from './nav.js';
import { loadConcepts, switchAgentTab } from './concepts.js';
import { loadCrispDm, switchCrispTab } from './crisp-dm.js';
import { loadAgentPerformance, setAgentPerfPeriod, loadAgentPerfTimeline } from './agent-performance.js';
import { loadAgentBuilds, submitTokenEstimate, toggleEstimateWidget, closeChartModal } from './agent-builds.js';
import { loadAgentPanel, agentPanelStep, resetAgentPanel, approveAgentProposal, rejectAgentProposal } from './agent-panel.js';
import { loadWhatINeed, hasPendingSave } from './what-i-need.js?v=59';
import { ensureDevToken } from '../shared/dev-auth.js';

// ── Register section loaders ─────────────────────────────────────────────────
registerLoader('investgame', () => {}); // intro page — no data to load
registerLoader('what-i-need', loadWhatINeed);
registerLoader('journey', () => {
  const frame = document.getElementById('journey-frame');
  if (frame && !frame.src) frame.src = frame.dataset.src;
});
registerLoader('concepts', loadConcepts);
registerLoader('crisp-dm', loadCrispDm);
registerLoader('agent-performance', loadAgentPerformance);
registerLoader('agent-builds', loadAgentBuilds);
registerLoader('agent-panel', loadAgentPanel);

// ── Expose to window for onclick attributes ──────────────────────────────────
window.show = show;
window.toggleSidebar = toggleSidebar;
window.switchAgentTab = switchAgentTab;
window.switchCrispTab = switchCrispTab;
window.loadConcepts = loadConcepts;
window.loadCrispDm = loadCrispDm;
window.loadAgentPerformance = loadAgentPerformance;
window.setAgentPerfPeriod = setAgentPerfPeriod;
window.loadAgentPerfTimeline = loadAgentPerfTimeline;
window.loadAgentBuilds = loadAgentBuilds;
window.submitTokenEstimate = submitTokenEstimate;
window.toggleEstimateWidget = toggleEstimateWidget;
window.closeChartModal = closeChartModal;
window.loadAgentPanel = loadAgentPanel;
window.agentPanelStep = agentPanelStep;
window.resetAgentPanel = resetAgentPanel;
window.approveAgentProposal = approveAgentProposal;
window.rejectAgentProposal = rejectAgentProposal;

// ── Init ─────────────────────────────────────────────────────────────────────
window.addEventListener('load', async () => {
  await ensureDevToken();
  // Show the intro section by default; back from sign-in to save → What I Need
  const start = hasPendingSave() ? 'what-i-need' : 'investgame';
  const defaultNav = document.querySelector(`[data-s="${start}"]`);
  if (defaultNav) show(start, defaultNav);
});
