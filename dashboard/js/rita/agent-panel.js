import { api } from './api.js';
import { mkChart, C } from './charts.js';

// ── Module state ──────────────────────────────────────────────────────────────
let apState = {
  dayIndex: 0,
  threadId: crypto.randomUUID(),
  loaded: false,
};

// Cancellation token — incremented each time a new typewriter starts,
// so any in-flight typewriter stops when it checks its captured token.
let _twToken = 0;

const TOTAL_DAYS = 16;

// ── Public API ────────────────────────────────────────────────────────────────

export function loadAgentPanel() {
  if (apState.loaded) return;
  apState.loaded = true;
  _initApChart();
  _showApNarrator(
    'ABOUT THIS DEMO',
    'RITA AI simulates a 6-agent investment system making decisions on ASML stock across ' +
    '16 trading days in April 2026. A Context Agent reads the market regime, a Strategy Agent ' +
    'adapts the stop-loss and target policy, a Probability Agent filters for statistical edge, ' +
    'and a Portfolio Manager sizes positions using the Kelly Criterion — all governed by a hard ' +
    'Compliance Gate that can veto any trade. A Narrator Agent synthesises the collaboration into ' +
    'a two-sentence insight. Click ▶ Run Day to step through each session.',
    8
  );
}

export async function agentPanelStep() {
  const btn = document.getElementById('ap-run-btn');
  const status = document.getElementById('agent-panel-status');

  if (apState.dayIndex >= TOTAL_DAYS) return;

  btn.disabled = true;
  btn.textContent = '⏳ Processing…';
  if (status) { status.className = 'badge run'; status.textContent = 'Running'; }

  try {
    const result = await api('/api/v1/agent-panel/run-day', 'POST', {
      day_index: apState.dayIndex,
      thread_id: apState.threadId,
    });

    _updateApChart(result);
    _updateApWidgets(result);
    _appendAuditRow(result);
    _saveToHistory(result);

    if (result.collaboration_insight) {
      _showApNarrator('AGENTIC AI COLLABORATION', result.collaboration_insight, 10);
    }

    apState.dayIndex++;

    if (apState.dayIndex >= TOTAL_DAYS) {
      _showFinalSummary(result);
      btn.textContent = '✓ Simulation Complete';
      if (status) { status.className = 'badge ok'; status.textContent = 'Done'; }
    } else if (result.proposal && result.proposal.action === 'BUY') {
      // Pause for human approval before the next day runs
      _showHitl(result);
      if (status) { status.className = 'badge warn'; status.textContent = 'Awaiting Decision'; }
    } else {
      btn.disabled = false;
      btn.textContent = `▶ Run Day ${apState.dayIndex + 1}`;
      if (status) { status.className = 'badge neu'; status.textContent = `Day ${apState.dayIndex} / ${TOTAL_DAYS}`; }
    }
  } catch (err) {
    console.error('Agent Panel error:', err);
    btn.disabled = false;
    btn.textContent = '▶ Run Day';
    if (status) { status.className = 'badge err'; status.textContent = 'Error'; }
  }
}

export function approveAgentProposal() {
  _hideHitl();
  _appendHitlAuditNote('Human approved the BUY proposal. Execution confirmed.');
  const btn = document.getElementById('ap-run-btn');
  const status = document.getElementById('agent-panel-status');
  if (btn) { btn.disabled = false; btn.textContent = `▶ Run Day ${apState.dayIndex + 1}`; }
  if (status) { status.className = 'badge neu'; status.textContent = `Day ${apState.dayIndex} / ${TOTAL_DAYS}`; }
}

export function rejectAgentProposal() {
  _hideHitl();
  _appendHitlAuditNote('Human rejected the BUY proposal. Position not taken.');
  const btn = document.getElementById('ap-run-btn');
  const status = document.getElementById('agent-panel-status');
  if (btn) { btn.disabled = false; btn.textContent = `▶ Run Day ${apState.dayIndex + 1}`; }
  if (status) { status.className = 'badge neu'; status.textContent = `Day ${apState.dayIndex} / ${TOTAL_DAYS}`; }
}

export function resetAgentPanel() {
  _twToken++; // cancel any in-flight typewriter
  _hideHitl();
  localStorage.removeItem('riia_agent_history');
  apState = { dayIndex: 0, threadId: crypto.randomUUID(), loaded: true };

  const status = document.getElementById('agent-panel-status');
  if (status) { status.className = 'badge neu'; status.textContent = 'Ready'; }

  const btn = document.getElementById('ap-run-btn');
  if (btn) { btn.disabled = false; btn.textContent = '▶ Run Day'; }

  _setEl('ap-regime', '—');
  _setEl('ap-policy', '—');
  _setEl('ap-probability', '—');
  _setEl('ap-proposal', '—');
  const comp = document.getElementById('ap-compliance');
  if (comp) { comp.textContent = 'PENDING'; comp.style.color = ''; }

  const tbody = document.getElementById('ap-audit-body');
  if (tbody) tbody.innerHTML = '';

  _showApNarrator('ABOUT THIS DEMO',
    'RITA AI simulates a 6-agent investment system making decisions on ASML stock across ' +
    '16 trading days in April 2026. Click ▶ Run Day to begin a fresh simulation.', 8);

  _initApChart();
}

// ── HITL helpers ──────────────────────────────────────────────────────────────

function _showHitl(result) {
  const panel = document.getElementById('ap-hitl-panel');
  const summary = document.getElementById('ap-hitl-summary');
  if (!panel) return;
  if (summary) {
    summary.textContent =
      `PROPOSAL: ${result.proposal.action} — ${result.proposal.size} of available cash ` +
      `at €${result.price_data.close.toFixed(2)}. ` +
      `Regime: ${result.regime}. Strategy: ${result.policy}. ` +
      `Probability: ${(result.probability * 100).toFixed(0)}%.`;
  }
  panel.style.display = 'block';
}

function _hideHitl() {
  const panel = document.getElementById('ap-hitl-panel');
  if (panel) panel.style.display = 'none';
}

function _appendHitlAuditNote(note) {
  const tbody = document.getElementById('ap-audit-body');
  if (!tbody || !tbody.firstChild) return;
  const firstRow = tbody.firstChild;
  // Append HITL decision as a small note under the Portfolio Manager cell (col 4)
  if (firstRow.cells[4]) {
    const span = document.createElement('div');
    span.style.cssText = 'font-size:10px;color:var(--t3);margin-top:4px;font-style:italic';
    span.textContent = `↳ ${note}`;
    firstRow.cells[4].appendChild(span);
  }
}

// ── Internal helpers ──────────────────────────────────────────────────────────

function _initApChart() {
  mkChart('ap-chart', {
    type: 'line',
    data: {
      labels: [],
      datasets: [
        {
          label: 'ASML Close (€)',
          data: [],
          borderColor: C.run,
          backgroundColor: 'rgba(0,86,184,0.05)',
          fill: true,
          tension: 0.4,
          pointRadius: 5,
          yAxisID: 'y',
        },
        {
          label: 'Initial Capital €5,000',
          data: [],
          borderColor: C.t3,
          borderWidth: 1,
          borderDash: [5, 5],
          fill: false,
          pointRadius: 0,
          yAxisID: 'y1',
        },
        {
          label: 'Available Cash (€)',
          data: [],
          borderColor: C.build,
          borderWidth: 2,
          fill: false,
          tension: 0.4,
          yAxisID: 'y1',
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        y: {
          position: 'right',
          beginAtZero: false,
          grid: { color: 'rgba(0,0,0,0.05)' },
          ticks: { color: C.run, font: { family: 'IBM Plex Mono' } },
          title: { display: true, text: 'ASML Price (€)' },
        },
        y1: {
          position: 'left',
          beginAtZero: false,
          min: 0,
          max: 10000,
          grid: { display: false },
          ticks: { color: C.t3, font: { family: 'IBM Plex Mono' } },
          title: { display: true, text: 'Capital (€)' },
        },
        x: { grid: { display: false }, ticks: { color: C.t3 } },
      },
      plugins: { legend: { display: true, position: 'top' } },
    },
  });
}

function _updateApChart(result) {
  const chart = Chart.getChart('ap-chart');
  if (!chart) return;
  const d = chart.data;
  d.labels.push(result.date);
  d.datasets[0].data.push(result.price_data.close);
  d.datasets[1].data.push(5000);
  d.datasets[2].data.push(result.cash);
  chart.update('none');
}

function _updateApWidgets(result) {
  _setEl('ap-regime', result.regime || '—');
  _setEl('ap-policy', result.policy || '—');
  _setEl('ap-probability', result.probability != null ? `${(result.probability * 100).toFixed(0)}%` : '—');
  _setEl('ap-proposal', result.proposal ? `${result.proposal.action} ${result.proposal.size}` : '—');

  const comp = document.getElementById('ap-compliance');
  if (comp) {
    comp.textContent = result.compliance_status || '—';
    comp.style.color = (result.compliance_status || '').startsWith('FLAGGED')
      ? 'var(--danger)' : 'var(--build)';
  }
}

function _appendAuditRow(result) {
  const tbody = document.getElementById('ap-audit-body');
  if (!tbody) return;

  const logs = result.logs || [];
  const get = (prefix) => {
    const entry = logs.find(l => l.startsWith(prefix));
    return entry ? entry.replace(prefix, '').trim() : '—';
  };

  const tr = document.createElement('tr');
  const cells = [
    result.date,
    get('Context Agent:'),
    get('Strategy Agent:'),
    get('Probability Agent:'),
    get('Portfolio Manager:'),
    result.compliance_status || '—',
  ].map(text => {
    const td = document.createElement('td');
    td.textContent = text;
    return td;
  });
  cells.forEach(td => tr.appendChild(td));
  tbody.prepend(tr);
}

function _showApNarrator(title, text, speed = 10) {
  const titleEl = document.getElementById('ap-narrator-title');
  const textEl = document.getElementById('ap-narrator-text');
  if (titleEl) titleEl.textContent = title;
  if (!textEl) return;
  textEl.innerHTML = '';
  const myToken = ++_twToken;
  let i = 0;
  function type() {
    if (myToken !== _twToken) return; // cancelled by a newer call
    if (i < text.length) {
      textEl.innerHTML += text.charAt(i);
      i++;
      setTimeout(type, speed);
    }
  }
  type();
}

function _showFinalSummary(result) {
  const profit = result.portfolio_value - 5000;
  const roi = (profit / 5000) * 100;
  const sign = profit >= 0 ? '+' : '';
  const outcome = profit >= 0
    ? 'Bull Trending regimes drove high-conviction entries while the Compliance Gate kept the system disciplined on volatile days.'
    : 'Conservative probability filters and volatile sessions limited exposure — agents prioritised capital preservation over forced entries.';

  _showApNarrator(
    'SIMULATION COMPLETE — FINAL REPORT',
    `RITA AI completed its 16-day ASML simulation. Starting capital of €5,000 closed at ` +
    `€${result.portfolio_value.toFixed(2)}, a net ${profit >= 0 ? 'gain' : 'loss'} of ` +
    `€${Math.abs(profit).toFixed(2)} (${sign}${roi.toFixed(2)}%) with ${result.holdings.toFixed(2)} shares held. ` +
    outcome,
    10
  );
}

function _setEl(id, html) {
  const el = document.getElementById(id);
  if (el) el.textContent = html;
}

function _saveToHistory(result) {
  const history = JSON.parse(localStorage.getItem('riia_agent_history') || '[]');
  history.push(result);
  localStorage.setItem('riia_agent_history', JSON.stringify(history));
}
