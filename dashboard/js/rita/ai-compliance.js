// ── AI Compliance Panel ───────────────────────────────────────────────────────
// Reads simulation history written by agent-panel.js (localStorage key:
// 'riia_agent_history') and renders three sub-tabs: Governance, Guardrails,
// and Trace Inspector.
import { t } from '../shared/i18n.js';

let _acHistory = [];

// ── Public ────────────────────────────────────────────────────────────────────

export function loadAiCompliance() {
  _acHistory = JSON.parse(localStorage.getItem('riia_agent_history') || '[]');
  _renderGovernance();
  _switchAcTab('ac-tab-governance', 'ac-view-governance');
}

export function switchAcTab(tabId, viewId) {
  _switchAcTab(tabId, viewId);
}

// ── Tab switching ─────────────────────────────────────────────────────────────

function _switchAcTab(tabId, viewId) {
  document.querySelectorAll('.ac-tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.ac-view').forEach(v => { v.style.display = 'none'; });
  const tab = document.getElementById(tabId);
  const view = document.getElementById(viewId);
  if (tab) tab.classList.add('active');
  if (view) view.style.display = 'block';
}

// ── Governance tab ────────────────────────────────────────────────────────────

function _renderGovernance() {
  const history = _acHistory;

  // KPIs
  if (history.length > 0) {
    const vetoes = history.filter(h => (h.compliance_status || '').includes('FLAGGED')).length;
    const passRate = ((history.length - vetoes) / history.length * 100).toFixed(1);
    _setEl('ac-pass-rate', `${passRate}%`);
    _setEl('ac-veto-count', vetoes);
    _setEl('ac-days-run', history.length);
  } else {
    _setEl('ac-pass-rate', '--%');
    _setEl('ac-veto-count', '0');
    _setEl('ac-days-run', '0');
  }

  // Timeline
  const container = document.getElementById('ac-timeline');
  if (!container) return;
  container.innerHTML = '';

  if (history.length === 0) {
    container.innerHTML = `<div style="color:var(--t3);font-size:12px;padding:12px">${t('compliance.no_data_prompt')}</div>`;
    return;
  }

  history.forEach((step, idx) => {
    const isVeto = (step.compliance_status || '').includes('FLAGGED');
    const node = document.createElement('div');
    node.className = 'ac-node' + (isVeto ? ' ac-node-veto' : ' ac-node-pass');
    node.textContent = idx + 1;
    node.title = `Day ${idx + 1}: ${step.date} — ${step.compliance_status}`;
    node.onclick = () => _showTrace(step, node);
    container.appendChild(node);
  });
}

function _showTrace(step, nodeEl) {
  document.querySelectorAll('.ac-node').forEach(n => n.classList.remove('selected'));
  if (nodeEl) nodeEl.classList.add('selected');

  _setEl('ac-day-label', `Day — ${step.date}`);

  const badge = document.getElementById('ac-violation-badge');
  if (badge) {
    const isVeto = (step.compliance_status || '').includes('FLAGGED');
    badge.style.display = isVeto ? 'inline-block' : 'none';
    badge.textContent = step.compliance_status;
  }

  const traceEl = document.getElementById('ac-trace-logs');
  if (!traceEl) return;
  traceEl.innerHTML = '';

  (step.logs || []).forEach(line => {
    const colonIdx = line.indexOf(':');
    const agent = colonIdx > -1 ? line.slice(0, colonIdx).trim() : line;
    const msg   = colonIdx > -1 ? line.slice(colonIdx + 1).trim() : '';

    const div = document.createElement('div');
    div.className = 'ac-trace-step';
    div.innerHTML = `<div class="ac-step-agent">${agent}</div><div class="ac-step-msg">${msg}</div>`;
    traceEl.appendChild(div);
  });
}

// ── Utility ───────────────────────────────────────────────────────────────────

function _setEl(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}
