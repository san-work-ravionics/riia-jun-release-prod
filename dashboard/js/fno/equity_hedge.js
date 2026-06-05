// ── Equity Hedge Scenarios ────────────────────────────────────────────────────
import { state } from './state.js';
import { apiBase } from './api.js';

const RITA_API_KEY = '';

let _portfolioChart = null;
let _payoffChart = null;

// Instrument + shares used for the last fetch — read by injectAsmlToState + renderEquityHedge
let _ehInstrument = 'ASML';
let _ehNShares    = 10;

const _MONTHS = ['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'];

function _activeInstrument() {
  const und = state.currentUnd;
  if (und && und !== 'ALL') return und;
  const eu = (state.portfolioGeoInstruments || []).find(i => i.region === 'EU');
  return eu ? eu.id : 'ASML';
}

function _rollingDateRange() {
  const end   = new Date();
  const start = new Date();
  start.setFullYear(start.getFullYear() - 1);
  return { start: start.toISOString().slice(0, 10), end: end.toISOString().slice(0, 10) };
}

function _fmtEur(v) {
  return '€' + Number(v).toLocaleString('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function _parseStrike(label) {
  const m = label.match(/[\d.]+/g);
  return m ? parseFloat(m[m.length - 1]) : 0;
}

// ── Inject ASML equity hedge positions/market/margin data into shared state ──
export function injectAsmlToState() {
  const data = state.equityHedgeData;
  if (!data) return;

  const p  = data.portfolio;
  const hs = data.hedge_scenarios;
  const mb = hs.mild_bearish;
  const sb = hs.strong_bearish;

  const instrument = _ehInstrument;
  const nShares    = _ehNShares;
  const endDate    = _rollingDateRange().end;
  const expLabel   = _MONTHS[new Date(endDate + 'T00:00:00').getMonth()] || 'EXP';

  // Remove stale entries from a prior inject
  state.positions = (state.positions || []).filter(pos => !pos._from_eq_hedge);
  state.marginData.by_position = (state.marginData.by_position || []).filter(m => !m._from_eq_hedge);

  const ccPremiumPerShare = mb.total_premium_eur / nShares;
  const ppPremiumPerShare = Math.abs(sb.total_premium_eur) / nShares;

  // Covered Call (Short CE) + Protective Put (Long PE) as positions
  state.positions = [
    ...state.positions,
    {
      und: instrument, full: mb.strike_label, exp: expLabel, type: 'CE', side: 'Short',
      strike: _parseStrike(mb.strike_label), qty: nShares,
      avg: ccPremiumPerShare, ltp: ccPremiumPerShare, chg: 0,
      pnl: mb.total_premium_eur, currency: 'EUR', _from_eq_hedge: true,
    },
    {
      und: instrument, full: sb.strike_label, exp: expLabel, type: 'PE', side: 'Long',
      strike: _parseStrike(sb.strike_label), qty: nShares,
      avg: ppPremiumPerShare, ltp: ppPremiumPerShare, chg: 0,
      pnl: -Math.abs(sb.total_premium_eur), currency: 'EUR', _from_eq_hedge: true,
    },
  ];

  // ASML market data derived from equity hedge portfolio
  const dailyPrices = (p.daily || []).map(d => d.value / nShares);
  const lastDay = p.daily?.[p.daily.length - 1];
  state.marketData[instrument] = {
    close: p.end_price, open: p.start_price,
    high:  dailyPrices.length ? Math.max(...dailyPrices) : p.end_price,
    low:   dailyPrices.length ? Math.min(...dailyPrices) : p.start_price,
    date:  lastDay?.date || endDate,
    chgFromOpen: p.return_pct, chgFromPrev: null, prevClose: p.start_price,
    shares: `${nShares} shares`, turnover: null,
    vol_30d: p.vol_30d_pct, currency: 'EUR', _from_eq_hedge: true,
  };

  // Covered call requires margin; long put is just premium paid
  const ccMarginSpan = mb.max_value_eur * 0.12;
  const ccMarginExp  = mb.max_value_eur * 0.08;
  state.marginData.by_position = [
    ...state.marginData.by_position,
    { und: instrument, full: mb.strike_label, exp: expLabel, type: 'CE', side: 'Short', qty: nShares,
      span: ccMarginSpan, exposure: ccMarginExp, total: ccMarginSpan + ccMarginExp, _from_eq_hedge: true },
    { und: instrument, full: sb.strike_label, exp: expLabel, type: 'PE', side: 'Long',  qty: nShares,
      span: 0, exposure: 0, total: ppPremiumPerShare * nShares, _from_eq_hedge: true },
  ];

  const asmlByPos = state.marginData.by_position.filter(m => m.und === instrument);
  state.marginData.summary = state.marginData.summary || {};
  state.marginData.summary[instrument] = {
    span:     asmlByPos.reduce((s, m) => s + m.span, 0),
    exposure: asmlByPos.reduce((s, m) => s + m.exposure, 0),
    total:    asmlByPos.reduce((s, m) => s + m.total, 0),
  };

  document.dispatchEvent(new CustomEvent('rita:asml-state-updated'));
}

export async function loadEquityHedge(forceRefresh = false) {
  const instrument = _activeInstrument();
  if (state.equityHedgeData && !forceRefresh && _ehInstrument === instrument) {
    renderEquityHedge(state.equityHedgeData);
    return;
  }
  _ehInstrument = instrument;
  _ehNShares    = 10;
  const { start: startDate, end: endDate } = _rollingDateRange();

  const loadEl = document.getElementById('eh-loading');
  const resEl  = document.getElementById('eh-results');
  if (loadEl) { loadEl.textContent = `Loading ${instrument}…`; loadEl.style.display = 'flex'; }
  if (resEl)  resEl.style.display = 'none';

  try {
    const headers = { 'Content-Type': 'application/json', ...(RITA_API_KEY ? { 'X-API-Key': RITA_API_KEY } : {}) };
    const resp = await fetch(apiBase() + '/api/v1/portfolio/equity-hedge-scenarios', {
      method: 'POST',
      headers,
      body: JSON.stringify({ instrument, n_shares: _ehNShares, start_date: startDate, end_date: endDate }),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new Error(err.detail || `HTTP ${resp.status}`);
    }
    const data = await resp.json();
    state.equityHedgeData = data;
    if (loadEl) loadEl.style.display = 'none';
    if (resEl)  resEl.style.display = 'block';
    renderEquityHedge(data);
    injectAsmlToState();
  } catch (e) {
    if (loadEl) { loadEl.textContent = 'Error: ' + e.message; loadEl.style.display = 'flex'; }
    if (resEl)  resEl.style.display = 'none';
  }
}

export function renderEquityHedge(data) {
  const p   = data.portfolio;
  const hs  = data.hedge_scenarios;
  const mb  = hs.mild_bearish;
  const sb  = hs.strong_bearish;
  const pc  = hs.payoff_curves;

  // KPIs
  const startValue   = p.start_price * p.n_shares;
  const hedgeRetPct  = startValue > 0 ? (mb.total_premium_eur / startValue) * 100 : 0;
  const netRetPct    = p.return_pct + hedgeRetPct;
  const retClass     = p.return_pct >= 0 ? 'pos' : 'neg';
  const hedgeClass   = hedgeRetPct >= 0 ? 'pos' : 'neg';
  const netClass     = netRetPct   >= 0 ? 'pos' : 'neg';
  const setKpi = (id, html) => { const el = document.getElementById(id); if (el) el.innerHTML = html; };
  setKpi('eh-kpi-start-price',  `<div class="kpi-value">${_fmtEur(p.start_price)}</div>`);
  setKpi('eh-kpi-end-price',    `<div class="kpi-value">${_fmtEur(p.end_price)}</div>`);
  setKpi('eh-kpi-vol',          `<div class="kpi-value">${p.vol_30d_pct.toFixed(1)}%</div>`);
  setKpi('eh-kpi-return',       `<div class="kpi-value ${retClass}">${p.return_pct >= 0 ? '+' : ''}${p.return_pct.toFixed(2)}%</div>`);
  setKpi('eh-kpi-hedge-return', `<div class="kpi-value ${hedgeClass}">+${hedgeRetPct.toFixed(2)}%</div><div class="kpi-sub">${_fmtEur(mb.total_premium_eur)} premium</div>`);
  setKpi('eh-kpi-net-return',   `<div class="kpi-value ${netClass}">${netRetPct >= 0 ? '+' : ''}${netRetPct.toFixed(2)}%</div>`);

  // Covered Call card
  const setEl = (id, txt) => { const el = document.getElementById(id); if (el) el.textContent = txt; };
  setEl('eh-cc-strike',    mb.strike_label);
  setEl('eh-cc-premium',   _fmtEur(mb.total_premium_eur));
  setEl('eh-cc-max-value', _fmtEur(mb.max_value_eur));
  setEl('eh-cc-breakeven', _fmtEur(mb.breakeven_price));
  setEl('eh-cc-desc',      mb.description);

  // Protective Put card
  setEl('eh-pp-strike',    sb.strike_label);
  setEl('eh-pp-premium',   _fmtEur(sb.total_premium_eur));
  setEl('eh-pp-floor',     _fmtEur(sb.floor_value_eur));
  setEl('eh-pp-breakeven', _fmtEur(sb.breakeven_price));
  setEl('eh-pp-desc',      sb.description);

  // Portfolio value chart
  if (_portfolioChart) { _portfolioChart.destroy(); _portfolioChart = null; }
  const portCtx = document.getElementById('eh-portfolio-chart');
  if (portCtx) {
    requestAnimationFrame(() => {
      _portfolioChart = new Chart(portCtx, {
        type: 'line',
        data: {
          labels: p.daily.map(d => d.date),
          datasets: [{
            label: `${_ehInstrument} × ${_ehNShares} shares`,
            data: p.daily.map(d => d.value),
            borderColor: 'var(--p04)', backgroundColor: 'rgba(107,47,160,0.08)',
            borderWidth: 2, pointRadius: 2, tension: 0.3, fill: true,
          }],
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: {
            x: { grid: { display: false }, ticks: { font: { family: 'IBM Plex Mono', size: 10 }, maxTicksLimit: 8 } },
            y: { grid: { color: 'rgba(0,0,0,.05)' }, ticks: { font: { family: 'IBM Plex Mono', size: 10 }, callback: v => _fmtEur(v) } },
          },
        },
      });
    });
  }

  // Payoff comparison chart
  if (_payoffChart) { _payoffChart.destroy(); _payoffChart = null; }
  const payCtx = document.getElementById('eh-payoff-chart');
  if (payCtx) {
    requestAnimationFrame(() => {
      const instrument = _ehInstrument;
      const xLabels = pc.price_range.map(v => _fmtEur(v));
      _payoffChart = new Chart(payCtx, {
        type: 'line',
        data: {
          labels: xLabels,
          datasets: [
            { label: 'Unhedged',       data: pc.unhedged,       borderColor: 'var(--p02)', backgroundColor: 'transparent', borderWidth: 2, pointRadius: 0, tension: 0.2 },
            { label: 'Covered Call',   data: pc.covered_call,   borderColor: 'var(--p01)', backgroundColor: 'transparent', borderWidth: 2, pointRadius: 0, tension: 0.2 },
            { label: 'Protective Put', data: pc.protective_put, borderColor: 'var(--neg)', backgroundColor: 'transparent', borderWidth: 2, pointRadius: 0, tension: 0.2 },
            { label: 'Break-even',     data: Array(xLabels.length).fill(0), borderColor: 'rgba(0,0,0,0.2)', borderWidth: 1, borderDash: [4,3], pointRadius: 0, fill: false },
          ],
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: {
            legend: { position: 'top', labels: { font: { family: 'IBM Plex Mono', size: 11 }, boxWidth: 10 } },
            tooltip: { callbacks: { label: ctx => `${ctx.dataset.label}: ${_fmtEur(ctx.raw)}` } },
          },
          scales: {
            x: { grid: { display: false }, title: { display: true, text: `${instrument} price at expiry`, font: { family: 'IBM Plex Mono', size: 10 } }, ticks: { font: { family: 'IBM Plex Mono', size: 9 }, maxTicksLimit: 10 } },
            y: { grid: { color: 'rgba(0,0,0,.05)' }, ticks: { font: { family: 'IBM Plex Mono', size: 10 }, callback: v => _fmtEur(v) } },
          },
        },
      });
    });
  }
}
