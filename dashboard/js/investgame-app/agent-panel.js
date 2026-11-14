import { t } from '../shared/i18n.js';
import { api } from './api.js';
import { mkChart, C } from './charts.js';
import { randomUUID } from '../shared/utils.js';

// ── Module state ──────────────────────────────────────────────────────────────
let apState = {
  dayIndex: 0,
  threadId: randomUUID(),
  loaded: false,
  selectedDays: 10,
  pendingAction: null,          // 'BUY' | 'SELL' | null — set while HITL panel is open
  buyHistory: [],               // confirmed buys: [{date, price, shares}]
  sellHistory: [],              // confirmed sells: [{date, price, shares}]
  pendingFinalResult: null,
};

// Cancellation token — incremented each time a new typewriter starts.
let _twToken = 0;

const STARTING_CAPITAL = 10_000;

// ── Public API ────────────────────────────────────────────────────────────────

export function loadAgentPanel() {
  if (apState.loaded) return;
  apState.loaded = true;
  _initApChart();
  _showApNarrator('ABOUT THIS DEMO', _introText(), 8);
}

export function setApDays(n) {
  if (apState.selectedDays === n) return;
  apState.selectedDays = n;
  _updateDayTabs(n);
  resetAgentPanel();
}

export async function agentPanelStep() {
  const btn = document.getElementById('ap-run-btn');
  const status = document.getElementById('agent-panel-status');
  const totalDays = apState.selectedDays;

  if (apState.dayIndex >= totalDays) return;

  btn.disabled = true;
  btn.textContent = t('agent.processing');
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

    // Sync histories from backend
    apState.buyHistory  = result.buy_history  || [];
    apState.sellHistory = result.sell_history || [];

    if (result.collaboration_insight) {
      _showApNarrator('AGENTIC AI COLLABORATION', result.collaboration_insight, 10);
    }

    apState.dayIndex++;

    const isFinalDay = apState.dayIndex >= totalDays;
    // Both BUY and SELL require HITL now
    const isHitl = result.pending === true &&
      (result.proposal?.action === 'BUY' || result.proposal?.action === 'SELL');

    if (isFinalDay) {
      btn.textContent = t('agent.sim_complete');
      if (isHitl) {
        apState.pendingAction = result.proposal.action;
        apState.pendingFinalResult = result;
        _showHitl(result);
        if (status) { status.className = 'badge warn'; status.textContent = t('agent.awaiting_decision'); }
      } else {
        btn.disabled = true;
        _showFinalSummary();
        if (status) { status.className = 'badge ok'; status.textContent = 'Done'; }
      }
    } else if (isHitl) {
      apState.pendingAction = result.proposal.action;
      _showHitl(result);
      if (status) { status.className = 'badge warn'; status.textContent = t('agent.awaiting_decision'); }
    } else {
      btn.disabled = false;
      btn.textContent = `${t('agent.run_day_btn')} ${apState.dayIndex + 1}`;
      if (status) { status.className = 'badge neu'; status.textContent = `${t('agent.day_label')} ${apState.dayIndex} / ${totalDays}`; }
    }
  } catch (err) {
    console.error('Agent Panel error:', err);
    btn.disabled = false;
    btn.textContent = t('agent.run_day_btn');
    if (status) { status.className = 'badge err'; status.textContent = 'Error'; }
  }
}

export async function approveAgentProposal() {
  _hideHitl();
  const btn = document.getElementById('ap-run-btn');
  const status = document.getElementById('agent-panel-status');
  const totalDays = apState.selectedDays;
  const pendingAction = apState.pendingAction;
  apState.pendingAction = null;

  try {
    const result = await api('/api/v1/agent-panel/confirm-day', 'POST', {
      thread_id: apState.threadId,
    });
    // Add the correct triangle and update cash line
    if (result.action === 'BUY') {
      _addBuyMarker(result.price);
      apState.buyHistory = result.buy_history || [];
    } else {
      _addSellMarker(result.price);
      apState.sellHistory = result.sell_history || [];
    }
    _updateCashOnChart(result.cash);
    const s = result.shares_traded;
    _appendHitlAuditNote(`Approved. ${result.action} executed: ${s} share${s !== 1 ? 's' : ''} at €${result.price.toFixed(2)}.`);
  } catch (err) {
    console.error('Agent Panel confirm error:', err);
    _appendHitlAuditNote('Approval failed — position not changed.');
  }

  if (apState.pendingFinalResult) {
    apState.pendingFinalResult = null;
    btn.disabled = true;
    _showFinalSummary();
    if (status) { status.className = 'badge ok'; status.textContent = 'Done'; }
  } else {
    if (btn) { btn.disabled = false; btn.textContent = `${t('agent.run_day_btn')} ${apState.dayIndex + 1}`; }
    if (status) { status.className = 'badge neu'; status.textContent = `${t('agent.day_label')} ${apState.dayIndex} / ${totalDays}`; }
  }
}

export async function rejectAgentProposal() {
  _hideHitl();
  const btn = document.getElementById('ap-run-btn');
  const status = document.getElementById('agent-panel-status');
  const totalDays = apState.selectedDays;
  const pendingAction = apState.pendingAction;
  apState.pendingAction = null;

  try {
    await api('/api/v1/agent-panel/reject-day', 'POST', {
      thread_id: apState.threadId,
    });
  } catch (err) {
    console.error('Agent Panel reject error:', err);
  }
  _appendHitlAuditNote(`Human rejected the ${pendingAction || 'trade'} proposal. No position change.`);

  if (apState.pendingFinalResult) {
    apState.pendingFinalResult = null;
    btn.disabled = true;
    _showFinalSummary();
    if (status) { status.className = 'badge ok'; status.textContent = 'Done'; }
  } else {
    if (btn) { btn.disabled = false; btn.textContent = `${t('agent.run_day_btn')} ${apState.dayIndex + 1}`; }
    if (status) { status.className = 'badge neu'; status.textContent = `${t('agent.day_label')} ${apState.dayIndex} / ${totalDays}`; }
  }
}

export function resetAgentPanel() {
  _twToken++;
  _hideHitl();
  localStorage.removeItem('riia_agent_history');

  const days = apState.selectedDays || 10;
  apState = {
    dayIndex: 0,
    threadId: randomUUID(),
    loaded: true,
    selectedDays: days,
    pendingAction: null,
    buyHistory: [],
    sellHistory: [],
    pendingFinalResult: null,
  };

  const status = document.getElementById('agent-panel-status');
  if (status) { status.className = 'badge neu'; status.textContent = t('agent.ready'); }

  const btn = document.getElementById('ap-run-btn');
  if (btn) { btn.disabled = false; btn.textContent = t('agent.run_day_btn'); }

  _setEl('ap-run-date', '—');
  _setEl('ap-regime', '—');
  _setEl('ap-policy', '—');
  _setEl('ap-probability', '—');
  _setEl('ap-proposal', '—');
  const comp = document.getElementById('ap-compliance');
  if (comp) { comp.textContent = 'PENDING'; comp.style.color = ''; }

  const tbody = document.getElementById('ap-audit-body');
  if (tbody) tbody.innerHTML = '';

  _updateDayTabs(days);
  _showApNarrator('ABOUT THIS DEMO', _introText(), 8);
  _initApChart();
}

// ── HITL helpers ──────────────────────────────────────────────────────────────

function _showHitl(result) {
  const panel = document.getElementById('ap-hitl-panel');
  const summary = document.getElementById('ap-hitl-summary');
  if (!panel) return;
  if (summary) {
    const action = result.proposal?.action || 'TRADE';
    const shares = result.proposal?.shares || 0;
    const price  = result.price_data.close;
    if (action === 'BUY') {
      const cost = (shares * price).toFixed(2);
      summary.textContent =
        `PROPOSAL: BUY ${shares} share${shares !== 1 ? 's' : ''} at €${price.toFixed(2)} ` +
        `(total cost €${cost}). ` +
        `Regime: ${result.regime}. Strategy: ${result.policy}. ` +
        `Probability: ${(result.probability * 100).toFixed(0)}%. ` +
        `Cash available: €${result.cash.toFixed(2)}.`;
    } else {
      const proceeds = (shares * price).toFixed(2);
      summary.textContent =
        `PROPOSAL: SELL ${shares} share${shares !== 1 ? 's' : ''} at €${price.toFixed(2)} ` +
        `(proceeds €${proceeds}). ` +
        `Regime: ${result.regime}. Strategy: ${result.policy}. ` +
        `Probability: ${(result.probability * 100).toFixed(0)}%. ` +
        `Holdings: ${result.holdings} shares.`;
    }
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
  if (firstRow.cells[4]) {
    const span = document.createElement('div');
    span.style.cssText = 'font-size:10px;color:var(--t3);margin-top:4px;font-style:italic';
    span.textContent = `↳ ${note}`;
    firstRow.cells[4].appendChild(span);
  }
}

// ── Days tab helper ───────────────────────────────────────────────────────────

function _updateDayTabs(active) {
  [5, 10, 15].forEach(d => {
    const btn = document.getElementById(`ap-days-${d}`);
    if (!btn) return;
    btn.className = d === active ? 'btn btn-build btn-sm' : 'btn btn-ghost btn-sm';
  });
}

// ── Chart helpers ─────────────────────────────────────────────────────────────

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
          pointRadius: 3,
          yAxisID: 'y',
        },
        {
          label: `Capital €${STARTING_CAPITAL.toLocaleString()}`,
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
          pointRadius: 0,
          yAxisID: 'y1',
        },
        {
          label: '▲ BUY',
          data: [],
          type: 'line',
          showLine: false,
          pointStyle: 'triangle',
          rotation: 0,
          pointRadius: 4,
          pointHoverRadius: 5,
          backgroundColor: 'rgba(26,107,60,0.9)',
          borderColor: '#1A6B3C',
          borderWidth: 2,
          yAxisID: 'y',
          spanGaps: false,
        },
        {
          label: '▼ SELL',
          data: [],
          type: 'line',
          showLine: false,
          pointStyle: 'triangle',
          rotation: 180,
          pointRadius: 4,
          pointHoverRadius: 5,
          backgroundColor: 'rgba(155,28,28,0.9)',
          borderColor: '#9B1C1C',
          borderWidth: 2,
          yAxisID: 'y',
          spanGaps: false,
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
          max: STARTING_CAPITAL * 2,
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
  d.datasets[1].data.push(STARTING_CAPITAL);
  d.datasets[2].data.push(result.cash);
  // Both BUY and SELL markers are null until confirmed via HITL
  d.datasets[3].data.push(null);
  d.datasets[4].data.push(null);
  chart.update('none');
}

function _addBuyMarker(price) {
  const chart = Chart.getChart('ap-chart');
  if (!chart) return;
  const d3 = chart.data.datasets[3].data;
  if (d3.length > 0) d3[d3.length - 1] = price;
  chart.update('none');
}

function _addSellMarker(price) {
  const chart = Chart.getChart('ap-chart');
  if (!chart) return;
  const d4 = chart.data.datasets[4].data;
  if (d4.length > 0) d4[d4.length - 1] = price;
  chart.update('none');
}

function _updateCashOnChart(newCash) {
  const chart = Chart.getChart('ap-chart');
  if (!chart) return;
  const d2 = chart.data.datasets[2].data;
  if (d2.length > 0) d2[d2.length - 1] = newCash;
  chart.update('none');
}

// ── Widget / audit helpers ────────────────────────────────────────────────────

function _updateApWidgets(result) {
  _setEl('ap-run-date', result.date || '—');
  _setEl('ap-regime', result.regime || '—');
  _setEl('ap-policy', result.policy || '—');
  _setEl('ap-probability', result.probability != null ? `${(result.probability * 100).toFixed(0)}%` : '—');

  const action = result.proposal?.action || '—';
  const shares = result.proposal?.shares;
  const proposalText = (action === 'BUY' || action === 'SELL') && shares
    ? `${action} ${shares} sh`
    : action;
  _setEl('ap-proposal', proposalText);

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
    if (myToken !== _twToken) return;
    if (i >= text.length) return;
    // Jump through HTML tags instantly so only visible text characters are timed
    if (text[i] === '<') {
      const end = text.indexOf('>', i);
      i = end !== -1 ? end + 1 : text.length;
      textEl.innerHTML = text.substring(0, i);
      type();
    } else {
      textEl.innerHTML = text.substring(0, ++i);
      setTimeout(type, speed);
    }
  }
  type();
}

function _introText() {
  const n = apState.selectedDays;
  return (
    `RITA AI simulates a 6-agent investment system making decisions on ASML stock across ` +
    `${n} trading days in April 2026. Starting capital: €10,000. The Portfolio Manager buys or sells ` +
    `in whole shares — 20% of available cash per buy, 20% of holdings per sell. ` +
    `Both BUY and SELL proposals pause for your Human-in-the-Loop approval before execution. ` +
    `Use the 5 / 10 / 15 day selector to change the run length, then click ▶ Run Day to begin.`
  );
}

function _showFinalSummary() {
  const bh = apState.buyHistory  || [];
  const sh = apState.sellHistory || [];

  const totalBuyShares  = bh.reduce((s, b) => s + b.shares, 0);
  const totalSellShares = sh.reduce((s, b) => s + b.shares, 0);
  const avgBuyPrice  = totalBuyShares  > 0 ? bh.reduce((s, b) => s + b.price * b.shares, 0) / totalBuyShares  : null;
  const avgSellPrice = totalSellShares > 0 ? sh.reduce((s, b) => s + b.price * b.shares, 0) / totalSellShares : null;

  const chart = Chart.getChart('ap-chart');
  const lastPrice = chart?.data.datasets[0].data.at(-1) ?? 0;
  const lastCash  = chart?.data.datasets[2].data.at(-1) ?? 0;
  const netHoldings  = totalBuyShares - totalSellShares;
  const sharesValue  = netHoldings * lastPrice;
  const portfolioValue = lastCash + sharesValue;
  const profit = portfolioValue - STARTING_CAPITAL;
  const roi    = (profit / STARTING_CAPITAL) * 100;
  const isProfit = profit >= 0;
  const sign   = isProfit ? '+' : '−';
  const returnColor = isProfit ? 'var(--build)' : 'var(--danger)';

  const pl = (n, word) => `${n} ${word}${n !== 1 ? 's' : ''}`;

  const netSpan = `<span style="color:${returnColor}">${sign}€${Math.abs(profit).toFixed(2)} (${sign}${roi.toFixed(2)}%)</span>`;

  const sharesDetail = netHoldings > 0
    ? `shares €${sharesValue.toFixed(2)} (holding ${pl(netHoldings, 'share')})`
    : 'shares €0.00 (no position)';

  const buysLine  = avgBuyPrice  !== null
    ? `${pl(bh.length, 'trade')}, ${pl(totalBuyShares, 'share')}, avg entry €${avgBuyPrice.toFixed(2)}.`
    : 'None.';
  const sellsLine = avgSellPrice !== null
    ? `${pl(sh.length, 'trade')}, ${pl(totalSellShares, 'share')}, avg exit €${avgSellPrice.toFixed(2)}.`
    : 'None.';

  const text = [
    `RITA AI completed the ${apState.selectedDays}-day ASML simulation.`,
    `Cash €${lastCash.toFixed(2)} and ${sharesDetail} = Final Portfolio €${portfolioValue.toFixed(2)} — net ${netSpan}.`,
    `Buys: ${buysLine}`,
    `Sells: ${sellsLine}`,
  ].join(' ');

  _showApNarrator('SIMULATION COMPLETE — FINAL REPORT', text, 10);
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
