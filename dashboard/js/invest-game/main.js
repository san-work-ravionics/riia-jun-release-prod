import { selectDays, runDay, getResult, selectVolatileDays, runDayVolatile } from './api.js';

const TRANSACTION_RATE = 0.001;
const TAX_RATE = 0.30;

const gameState = {
  gameId: null,
  instrument: 'ASML',
  currency: 'EUR',
  startingCapital: 5000,
  warmupDays: [],
  gameDays: [],
  currentDayIndex: 0,
  started: false,
  volatileMode: false,
  buysLeft: 4,
  sellsLeft: 4,
  aiBuysLeft: 4,
  aiSellsLeft: 4,
  user: { position: 'flat', cash: 5000, shares: 0, entryPrice: 0, portfolio: 0, cumCosts: 0, cumTax: 0, netValue: 5000, prevNetValue: 5000 },
  ai:   { position: 'flat', cash: 5000, shares: 0, entryPrice: 0, portfolio: 0, cumCosts: 0, cumTax: 0, netValue: 5000, prevNetValue: 5000 }
};

function sym() {
  return gameState.currency === 'USD' ? '$' : '€';
}

function fmtSigned(value) {
  if (value > 0)  return '+' + sym() + value.toFixed(2);
  if (value < 0)  return '−' + sym() + Math.abs(value).toFixed(2);
  return sym() + '0.00';
}

function calculateDay(actor, action, closePrice) {
  const tranche = gameState.startingCapital / 4;

  if (action === 'BUY' && actor.cash > 0) {
    const invest   = Math.min(tranche, actor.cash);
    const txCost   = invest * TRANSACTION_RATE;
    actor.cumCosts += txCost;
    const newShares = (invest - txCost) / closePrice;
    actor.entryPrice = actor.shares > 0
      ? (actor.shares * actor.entryPrice + newShares * closePrice) / (actor.shares + newShares)
      : closePrice;
    actor.shares += newShares;
    actor.cash   -= invest;
    actor.position = 'long';

  } else if (action === 'SELL' && actor.shares > 0) {
    const sharesToSell = Math.min(tranche / closePrice, actor.shares);
    const proceeds     = sharesToSell * closePrice;
    const txCost       = proceeds * TRANSACTION_RATE;
    actor.cumCosts += txCost;
    const grossProfit  = sharesToSell * (closePrice - actor.entryPrice);
    const tax          = grossProfit > 0 ? grossProfit * TAX_RATE : 0;
    actor.cumTax  += tax;
    actor.cash    += proceeds - txCost - tax;
    actor.shares  -= sharesToSell;
    if (actor.shares < 1e-9) { actor.shares = 0; actor.entryPrice = 0; actor.position = 'flat'; }

  } else if (action === 'SELL_ALL' && actor.shares > 0) {
    const proceeds    = actor.shares * closePrice;
    const txCost      = proceeds * TRANSACTION_RATE;
    actor.cumCosts   += txCost;
    const grossProfit = actor.shares * (closePrice - actor.entryPrice);
    const tax         = grossProfit > 0 ? grossProfit * TAX_RATE : 0;
    actor.cumTax     += tax;
    actor.cash       += proceeds - txCost - tax;
    actor.shares      = 0; actor.entryPrice = 0; actor.position = 'flat';
  }

  actor.portfolio = actor.shares * closePrice;
  actor.netValue  = actor.cash + actor.portfolio - actor.cumCosts - actor.cumTax;
}

// ── P&L cards ──
function renderPnLCards() {
  const s = sym();
  const cap = gameState.startingCapital;
  const setCard = (prefix, actor) => {
    document.getElementById(`${prefix}-cash`).textContent      = s + actor.cash.toFixed(2);
    document.getElementById(`${prefix}-portfolio`).textContent = s + actor.portfolio.toFixed(2);
    document.getElementById(`${prefix}-costs`).textContent     = '−' + s + actor.cumCosts.toFixed(2);
    document.getElementById(`${prefix}-tax`).textContent       = '−' + s + actor.cumTax.toFixed(2);
    const netEl = document.getElementById(`${prefix}-net`);
    netEl.textContent = s + actor.netValue.toFixed(2);
    netEl.className   = 'pnl-value' + (actor.netValue > cap ? ' pos' : actor.netValue < cap ? ' neg' : '');
  };
  setCard('user', gameState.user);
  setCard('ai',   gameState.ai);
}

function renderBudgetDisplay() {
  const el  = document.getElementById('budget-display');
  const row = document.getElementById('budget-row');
  if (!el) return;
  if (row) row.style.display = '';
  const budgetHtml = (b, s) =>
    `<span style="color:var(--ok);font-weight:600">Buys: ${b}</span>` +
    `<span style="color:var(--t4);margin:0 4px">/</span>` +
    `<span style="color:var(--danger);font-weight:600">Sells: ${s}</span>`;
  el.innerHTML = budgetHtml(gameState.buysLeft, gameState.sellsLeft);
  const aiEl = document.getElementById('ai-budget-display');
  if (aiEl) aiEl.innerHTML = budgetHtml(gameState.aiBuysLeft, gameState.aiSellsLeft);
}

function showDayBar(n) {
  const canBuy  = gameState.buysLeft  > 0 && gameState.user.cash > 0;
  const canSell = gameState.sellsLeft > 0 && gameState.user.shares > 0;
  const buyBtn  = document.getElementById('dbar-buy');
  const sellBtn = document.getElementById('dbar-sell');
  const holdBtn = document.getElementById('dbar-hold');
  buyBtn.disabled  = !canBuy;
  sellBtn.disabled = !canSell;
  holdBtn.disabled = false;
  buyBtn.onclick  = () => handleUserAction(n, 'BUY');
  sellBtn.onclick = () => handleUserAction(n, 'SELL');
  holdBtn.onclick = () => handleUserAction(n, 'HOLD');
}

function setEndDateMax() {
  const d = new Date();
  d.setMonth(d.getMonth() - 3);
  const el = document.getElementById('end-date');
  el.max = d.toISOString().split('T')[0];
  el.value = el.max;
}

function validateDates() {
  const start = document.getElementById('start-date').value;
  const end   = document.getElementById('end-date').value;
  document.getElementById('btn-select-days').disabled = !(start && end && end > start);
}

function lockControls() {
  ['pill-asml', 'pill-nvidia', 'start-date', 'end-date'].forEach(id => {
    document.getElementById(id).disabled = true;
  });
  document.getElementById('btn-select-days').style.display   = 'none';
  document.getElementById('btn-volatile-days').style.display = 'none';
  document.getElementById('btn-new-game').style.display      = '';
}

function renderWarmupRows() {
  const s = sym();
  [1, 2].forEach((n, i) => {
    const d = gameState.warmupDays[i];
    document.getElementById(`dbar-date-${n}`).textContent  = d.date;
    document.getElementById(`dbar-price-${n}`).textContent = s + d.close.toFixed(2);
  });
  document.getElementById('day-action-bar').style.display = '';
}

function populateActiveRowData(n) {
  const d = gameState.gameDays[n - 3];
  const prevClose = n === 3
    ? gameState.warmupDays[gameState.warmupDays.length - 1].close
    : gameState.gameDays[n - 4].close;
  const pct   = (d.close - prevClose) / prevClose * 100;
  const isUp  = pct >= 0;
  const arrow = isUp ? '▲' : '▼';
  const color = isUp ? 'var(--pos)' : 'var(--neg)';
  const sign  = isUp ? '+' : '';
  document.getElementById(`row${n}-price`).innerHTML =
    `${sym()}${d.close.toFixed(2)} <span style="font-size:0.8em;color:${color};white-space:nowrap">${arrow} ${sign}${pct.toFixed(2)}%</span>`;
}

function unlockRow(n) {
  populateActiveRowData(n);

  if (n === 10) {
    showDayBar(n);
    ['dbar-buy', 'dbar-sell', 'dbar-hold'].forEach(id => {
      document.getElementById(id).disabled = true;
    });
    setTimeout(() => {
      const action = gameState.user.position === 'long' ? 'SELL' : 'HOLD';
      handleUserAction(10, action);
    }, 700);
    return;
  }

  showDayBar(n);
}

function showAllGreyed() {
  for (let n = 3; n <= 10; n++) {
    document.querySelectorAll(`[data-day="${n}"]`).forEach(el => {
      el.style.display = '';
      el.classList.add('greyed-out');
    });
  }
}


function revealDay(n) {
  document.querySelectorAll(`[data-day="${n}"]`).forEach(el => { el.classList.remove('greyed-out'); });
  // Highlight active column header
  document.querySelectorAll('.day-col.active-col').forEach(el => el.classList.remove('active-col'));
  document.getElementById(`game-row-${n}`).classList.add('active-col');
  unlockRow(n);
  document.getElementById(`game-row-${n}`).scrollIntoView({ behavior: 'smooth', inline: 'nearest', block: 'nearest' });
}

async function handleUserAction(n, action) {
  ['dbar-buy', 'dbar-sell', 'dbar-hold'].forEach(id => {
    document.getElementById(id).disabled = true;
  });

  const actionCell = document.getElementById(`action-label-${n}`);
  if (actionCell) {
    actionCell.innerHTML = `<span class="action-label ${action.toLowerCase()}">${action}</span>`;
  }

  document.getElementById(`game-row-${n}`).classList.remove('active-col');

  const dayIndex   = n - 3;
  const closePrice = gameState.gameDays[dayIndex].close;

  const wasBuying  = action === 'BUY'  && gameState.user.cash > 0;
  const wasSelling = action === 'SELL' && gameState.user.shares > 0;

  gameState.user.prevNetValue = gameState.user.netValue;
  gameState.ai.prevNetValue   = gameState.ai.netValue;

  calculateDay(gameState.user, action, closePrice);

  if (wasBuying)  gameState.buysLeft--;
  if (wasSelling) gameState.sellsLeft--;

  let result;
  try {
    result = gameState.volatileMode
      ? runDayVolatile(gameState.instrument, dayIndex)
      : await runDay(gameState.gameId, dayIndex, action);
  } catch (e) {
    console.error('runDay error', e);
    showDayBar(n);
    return;
  }

  const aiEffective  = (result.ai_action === 'SELL' && gameState.ai.shares <= 0) ? 'HOLD'
                     : (result.ai_action === 'BUY'  && gameState.ai.cash   <= 0) ? 'HOLD'
                     : result.ai_action;
  const aiWasBuying  = aiEffective === 'BUY';
  const aiWasSelling = aiEffective === 'SELL';
  calculateDay(gameState.ai, aiEffective, closePrice);
  if (aiWasBuying)  gameState.aiBuysLeft--;
  if (aiWasSelling) gameState.aiSellsLeft--;
  gameState.currentDayIndex = dayIndex + 1;

  const aiCell  = document.getElementById(`ai-cell-${n}`);
  const aiClass = aiEffective === 'BUY' ? 'ai-buy' : aiEffective === 'SELL' ? 'ai-sell' : 'ai-hold';
  aiCell.textContent = aiEffective;
  aiCell.className   = `day-data ai-cell ${aiClass}`;

  renderPnLCards();
  renderBudgetDisplay();

  const pct = ((dayIndex + 1) / 8) * 100;
  document.getElementById('progress-fill').style.width       = `${pct}%`;
  document.getElementById('progress-label-text').textContent = `Day ${dayIndex + 1} of 8`;

  renderComplianceRow(n, result);

  if (n < 10) {
    revealDay(n + 1);
  } else {
    await endGame();
  }
}

function renderComplianceRow(n, result) {
  const isFlag = result.compliance_status === 'flagged';
  document.getElementById(`comp-status-${n}`).innerHTML    = `<span class="status-badge ${isFlag ? 'flag' : 'ok'}">${isFlag ? 'FLAGGED' : 'PASS'}</span>`;
  document.getElementById(`comp-rule-${n}`).textContent    = result.compliance_rule;
  document.getElementById(`comp-insight-${n}`).textContent = result.ai_insight;
}

async function endGame() {
  try { await getResult(gameState.gameId); } catch (e) { console.error('getResult error', e); }
}

function resetGame() {
  const cap = 5000;
  const freshActor = () => ({ position: 'flat', cash: cap, shares: 0, entryPrice: 0, portfolio: 0, cumCosts: 0, cumTax: 0, netValue: cap, prevNetValue: cap });
  Object.assign(gameState, {
    gameId: null, instrument: 'ASML', currency: 'EUR', startingCapital: cap,
    warmupDays: [], gameDays: [], currentDayIndex: 0, started: false, volatileMode: false,
    buysLeft: 4, sellsLeft: 4, aiBuysLeft: 4, aiSellsLeft: 4,
    user: freshActor(), ai: freshActor()
  });

  // Controls
  ['pill-asml', 'pill-nvidia', 'start-date', 'end-date'].forEach(id => {
    document.getElementById(id).disabled = false;
  });
  document.getElementById('pill-asml').classList.add('active');
  document.getElementById('pill-nvidia').classList.remove('active');
  document.getElementById('btn-select-days').style.display   = '';
  document.getElementById('btn-new-game').style.display      = 'none';
  document.getElementById('btn-volatile-days').style.display = '';
  document.getElementById('selection-label').style.display = 'none';
  document.getElementById('selected-instrument').textContent = '—';
  document.getElementById('selected-range-text').textContent = '—';
  document.getElementById('selected-days-count').textContent = '—';

  // P&L
  const s = '€';
  ['user', 'ai'].forEach(p => {
    document.getElementById(`${p}-cash`).textContent      = s + '5,000.00';
    document.getElementById(`${p}-portfolio`).textContent = s + '0.00';
    document.getElementById(`${p}-costs`).textContent     = '−' + s + '0.00';
    document.getElementById(`${p}-tax`).textContent       = '−' + s + '0.00';
    const net = document.getElementById(`${p}-net`);
    net.textContent = s + '5,000.00'; net.className = 'pnl-value';
  });
  const autoBadge = document.getElementById('day10-auto-badge');
  if (autoBadge) autoBadge.remove();
  const budgetEl  = document.getElementById('budget-display');
  if (budgetEl) budgetEl.innerHTML = '';
  const budgetRow = document.getElementById('budget-row');
  if (budgetRow) budgetRow.style.display = 'none';

  document.getElementById('winner-banner').style.display     = 'none';
  document.getElementById('winner-badge').textContent        = '—';
  document.getElementById('winner-badge').className          = '';
  document.getElementById('progress-fill').style.width       = '0%';
  document.getElementById('progress-label-text').textContent = 'Day 0 of 8';
  document.getElementById('row-performance').style.display   = 'none';

  // Day action bar
  document.getElementById('day-action-bar').style.display = 'none';
  ['dbar-date-1', 'dbar-price-1', 'dbar-date-2', 'dbar-price-2'].forEach(id => {
    document.getElementById(id).textContent = '—';
  });
  ['dbar-buy', 'dbar-sell', 'dbar-hold'].forEach(id => {
    const el = document.getElementById(id);
    el.disabled = true;
    el.onclick  = null;
  });

  // Active columns
  for (let n = 3; n <= 10; n++) {
    document.querySelectorAll(`[data-day="${n}"]`).forEach(el => { el.classList.add('greyed-out'); });
    document.getElementById(`game-row-${n}`).classList.remove('active-col');
    const actionCell = document.getElementById(`action-label-${n}`);
    if (actionCell) actionCell.textContent = '—';
    document.getElementById(`row${n}-price`).textContent  = '—';
    document.getElementById(`ai-cell-${n}`).textContent   = '—';
    document.getElementById(`ai-cell-${n}`).className     = 'day-data ai-cell';
    document.getElementById(`comp-status-${n}`).innerHTML  = '—';
    document.getElementById(`comp-rule-${n}`).textContent  = '—';
    document.getElementById(`comp-insight-${n}`).textContent = '—';
  }

  validateDates();
}

function initControls() {
  setEndDateMax();
  validateDates();

  document.getElementById('pill-asml').addEventListener('click', () => {
    gameState.instrument = 'ASML'; gameState.currency = 'EUR';
    document.getElementById('pill-asml').classList.add('active');
    document.getElementById('pill-nvidia').classList.remove('active');
    validateDates();
  });
  document.getElementById('pill-nvidia').addEventListener('click', () => {
    gameState.instrument = 'NVIDIA'; gameState.currency = 'USD';
    document.getElementById('pill-nvidia').classList.add('active');
    document.getElementById('pill-asml').classList.remove('active');
    validateDates();
  });

  document.getElementById('start-date').addEventListener('change', validateDates);
  document.getElementById('end-date').addEventListener('change',   validateDates);

  document.getElementById('btn-select-days').addEventListener('click', async () => {
    document.getElementById('btn-select-days').disabled = true;
    const start = document.getElementById('start-date').value;
    const end   = document.getElementById('end-date').value;
    let data;
    try {
      data = await selectDays(gameState.instrument, start, end);
    } catch (e) {
      console.error('selectDays error', e);
      document.getElementById('btn-select-days').disabled = false;
      return;
    }

    gameState.gameId          = data.game_id;
    gameState.currency        = data.currency;
    gameState.startingCapital = data.starting_capital ?? 5000;
    gameState.warmupDays      = data.warmup_days;
    gameState.gameDays        = data.game_days;
    gameState.user.cash       = gameState.startingCapital;
    gameState.user.netValue   = gameState.startingCapital;
    gameState.user.prevNetValue = gameState.startingCapital;
    gameState.ai.cash         = gameState.startingCapital;
    gameState.ai.netValue     = gameState.startingCapital;
    gameState.ai.prevNetValue = gameState.startingCapital;
    gameState.started         = true;

    lockControls();

    document.getElementById('selected-instrument').textContent = data.instrument;
    document.getElementById('selected-range-text').textContent =
      data.game_days[0].date + ' — ' + data.game_days[data.game_days.length - 1].date;
    document.getElementById('selected-days-count').textContent = '8 trading days';
    document.getElementById('selection-label').style.display   = '';
    document.getElementById('row-performance').style.display   = '';
    document.getElementById('progress-fill').style.width       = '0%';
    document.getElementById('progress-label-text').textContent = 'Day 0 of 8';

    renderPnLCards();
    renderBudgetDisplay();
    renderWarmupRows();
    document.querySelectorAll('.warmup').forEach(el => el.classList.remove('greyed-out'));
    revealDay(3);
  });

  document.getElementById('btn-new-game').addEventListener('click', resetGame);

  document.getElementById('btn-volatile-days').addEventListener('click', () => {
    const isNvidia = gameState.instrument === 'NVIDIA';
    if (gameState.started) {
      resetGame();
      if (isNvidia) {
        gameState.instrument = 'NVIDIA';
        gameState.currency   = 'USD';
        document.getElementById('pill-nvidia').classList.add('active');
        document.getElementById('pill-asml').classList.remove('active');
      }
    }

    const data = selectVolatileDays(gameState.instrument);

    gameState.gameId          = data.game_id;
    gameState.currency        = data.currency;
    gameState.startingCapital = data.starting_capital;
    gameState.warmupDays      = data.warmup_days;
    gameState.gameDays        = data.game_days;
    gameState.user.cash       = gameState.startingCapital;
    gameState.user.netValue   = gameState.startingCapital;
    gameState.user.prevNetValue = gameState.startingCapital;
    gameState.ai.cash         = gameState.startingCapital;
    gameState.ai.netValue     = gameState.startingCapital;
    gameState.ai.prevNetValue = gameState.startingCapital;
    gameState.started         = true;
    gameState.volatileMode    = true;

    lockControls();
    document.getElementById('selected-instrument').textContent = data.instrument;
    document.getElementById('selected-range-text').textContent =
      data.game_days[0].date + ' — ' + data.game_days[data.game_days.length - 1].date;
    document.getElementById('selected-days-count').textContent = '8 volatile days';
    document.getElementById('selection-label').style.display   = '';
    document.getElementById('row-performance').style.display   = '';
    document.getElementById('progress-fill').style.width       = '0%';
    document.getElementById('progress-label-text').textContent = 'Day 0 of 8';

    renderPnLCards();
    renderBudgetDisplay();
    renderWarmupRows();
    document.querySelectorAll('.warmup').forEach(el => el.classList.remove('greyed-out'));
    revealDay(3);
  });

  showAllGreyed();
}

document.addEventListener('DOMContentLoaded', initControls);
