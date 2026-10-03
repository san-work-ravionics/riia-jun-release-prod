// ── Equity Hedge Scenarios ────────────────────────────────────────────────────
import { state } from './state.js';
import { apiBase } from './api.js';
import { renderGreeksCards, renderGreeksTable } from './greeks.js';
import { renderStressScenarios } from './stress.js';
import { computeNShares, coveredCallMargin } from './hedge-calc.js';
import { renderMonthlyCandles, renderMonthlyChange } from './hedge-charts.js';

const RITA_API_KEY = '';

let _portfolioChart = null;
let _monthlyChangeChart = null;

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

// Whole-number shares from portfolio builder, or fall back to floor(alloc / price).
// Calculation lives in hedge-calc.js; this wrapper only gathers the page state.
function _computeNShares(instrument) {
  const geoInsts = state.portfolioGeoInstruments || [];
  const inst     = geoInsts.find(i => i.id === instrument);
  const price    = state.marketData[instrument]?.close || inst?.close;
  return computeNShares(inst, { close: price }, state.portfolioMeta?.total_value_eur);
}

function _fmtRange(start, end) {
  const mo = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  const fmt = d => mo[+d.slice(5, 7) - 1] + ' ' + d.slice(0, 4);
  return (start && end) ? fmt(start) + ' – ' + fmt(end) : '—';
}

const _CCY_SYMBOL = { EUR: '€', INR: '₹', USD: '$' };

function _fmtCcy(v, currency) {
  const sym = _CCY_SYMBOL[currency] || '€';
  return sym + Number(v).toLocaleString('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function _fmtEur(v) {
  return _fmtCcy(v, 'EUR');
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

  const currency         = p.currency || 'EUR';
  const ccPremiumPerShare = mb.total_premium_eur / nShares;
  const ppPremiumPerShare = Math.abs(sb.total_premium_eur) / nShares;

  // Covered Call (Short CE) + Protective Put (Long PE) as positions
  state.positions = [
    ...state.positions,
    {
      und: instrument, full: mb.strike_label, exp: expLabel, type: 'CE', side: 'Short',
      strike: _parseStrike(mb.strike_label), qty: nShares,
      avg: ccPremiumPerShare, ltp: ccPremiumPerShare, chg: 0,
      pnl: mb.total_premium_eur, currency, _from_eq_hedge: true,
    },
    {
      und: instrument, full: sb.strike_label, exp: expLabel, type: 'PE', side: 'Long',
      strike: _parseStrike(sb.strike_label), qty: nShares,
      avg: ppPremiumPerShare, ltp: ppPremiumPerShare, chg: 0,
      pnl: -Math.abs(sb.total_premium_eur), currency, _from_eq_hedge: true,
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
  const { span: ccMarginSpan, exposure: ccMarginExp } = coveredCallMargin(mb);
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
    state.riskSelectedInstrument = instrument;
    renderGreeksCards();
    renderGreeksTable();
    renderStressScenarios();
    return;
  }
  _ehInstrument = instrument;
  _ehNShares    = _computeNShares(instrument);
  const { start: startDate, end: endDate } = _rollingDateRange();

  const loadEl = document.getElementById('eh-loading');
  const resEl  = document.getElementById('eh-results');
  if (loadEl) { loadEl.textContent = `Loading ${instrument}…`; loadEl.style.display = 'flex'; }
  if (resEl)  resEl.style.display = 'none';

  try {
    // Use same ann_vol_pct source as the stress/std-dev table (analytics endpoint)
    const volPos   = (state.positions || []).find(p => p.und === instrument && p.ann_vol_pct != null);
    const annVolPct = volPos ? parseFloat(volPos.ann_vol_pct) : null;

    const headers = { 'Content-Type': 'application/json', ...(RITA_API_KEY ? { 'X-API-Key': RITA_API_KEY } : {}) };
    const body    = { instrument, n_shares: _ehNShares, start_date: startDate, end_date: endDate };
    if (annVolPct != null) body.ann_vol_pct = annVolPct;
    const resp = await fetch(apiBase() + '/api/v1/portfolio/equity-hedge-scenarios', {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
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
    // Filter Greeks/Stress to the active instrument and render into eh-risk-panels
    state.riskSelectedInstrument = instrument;
    renderGreeksCards();
    renderGreeksTable();
    renderStressScenarios();
  } catch (e) {
    if (loadEl) { loadEl.textContent = 'Error: ' + e.message; loadEl.style.display = 'flex'; }
    if (resEl)  resEl.style.display = 'none';
  }
}

export function renderEquityHedge(data) {
  const p          = data.portfolio;
  const hs         = data.hedge_scenarios;
  const mb         = hs.mild_bearish;
  const sb         = hs.strong_bearish;
  const ccy        = p.currency || 'EUR';
  const fmt        = v => _fmtCcy(v, ccy);
  const isNseLive  = hs.data_source === 'nse';

  // KPIs
  const startValue   = p.start_price * p.n_shares;
  const hedgeRetPct  = startValue > 0 ? (mb.total_premium_eur / startValue) * 100 : 0;
  const netRetPct    = p.return_pct + hedgeRetPct;
  const retClass     = p.return_pct >= 0 ? 'pos' : 'neg';
  const hedgeClass   = hedgeRetPct >= 0 ? 'pos' : 'neg';
  const netClass     = netRetPct   >= 0 ? 'pos' : 'neg';
  const setKpi = (id, html) => { const el = document.getElementById(id); if (el) el.innerHTML = html; };
  const ccySym = _CCY_SYMBOL[ccy] || ccy;
  const chartTitle = document.getElementById('eh-portfolio-chart-title');
  if (chartTitle) chartTitle.textContent = `Portfolio Value (${ccySym})`;
  const startD = p.daily?.[0]?.date || '';
  const endD   = p.daily?.[p.daily.length - 1]?.date || '';
  setKpi('eh-kpi-date-range',   `<div class="kpi-value" style="font-size:12px">${_fmtRange(startD, endD)}</div><div class="kpi-sub">${p.daily?.length || 0} trading days</div>`);
  setKpi('eh-kpi-start-price',  `<div class="kpi-value">${fmt(p.start_price)}</div><div class="kpi-sub">${startD}</div>`);
  setKpi('eh-kpi-end-price',    `<div class="kpi-value">${fmt(p.end_price)}</div><div class="kpi-sub">${endD}</div>`);
  setKpi('eh-kpi-shares',       `<div class="kpi-value">${p.n_shares.toFixed(2)}</div><div class="kpi-sub">${fmt(p.end_price * p.n_shares)} position</div>`);
  const lotHtml = p.lot_size
    ? `<div class="kpi-value">${p.lot_size}</div><div class="kpi-sub">${p.n_contracts} contract${p.n_contracts !== 1 ? 's' : ''}</div>`
    : `<div class="kpi-value">—</div><div class="kpi-sub">no F&amp;O lot</div>`;
  setKpi('eh-kpi-lot', lotHtml);

  // Lot size banner inside Hedge Overview card
  const lotEl = document.getElementById('eh-overview-lot');
  if (lotEl) {
    if (p.lot_size) {
      lotEl.textContent = `Lot size: ${p.lot_size} shares/contract · ${p.n_contracts} contract${p.n_contracts !== 1 ? 's' : ''} (${p.n_shares} shares ÷ ${p.lot_size})`;
      lotEl.style.display = 'block';
    } else {
      lotEl.style.display = 'none';
    }
  }
  setKpi('eh-kpi-vol',          `<div class="kpi-value">${p.vol_30d_pct.toFixed(1)}%</div><div class="kpi-sub">annualised 30d</div>`);
  setKpi('eh-kpi-return',       `<div class="kpi-value ${retClass}">${p.return_pct >= 0 ? '+' : ''}${p.return_pct.toFixed(2)}%</div>`);
  setKpi('eh-kpi-hedge-return', `<div class="kpi-value ${hedgeClass}">+${hedgeRetPct.toFixed(2)}%</div><div class="kpi-sub">${fmt(mb.total_premium_eur)} premium</div>`);
  setKpi('eh-kpi-net-return',   `<div class="kpi-value ${netClass}">${netRetPct >= 0 ? '+' : ''}${netRetPct.toFixed(2)}%</div>`);

  // Data source badge (NSE Live or Black-Scholes)
  const srcBadge = isNseLive
    ? '<span class="phase-tag p04" style="font-size:9px;padding:2px 6px;">NSE Live</span>'
    : '<span class="phase-tag" style="font-size:9px;padding:2px 6px;background:var(--t3);color:#fff;">BSM Est.</span>';
  const setBadge = id => { const el = document.getElementById(id); if (el) el.innerHTML = srcBadge; };
  setBadge('eh-cc-source-badge');
  setBadge('eh-pp-source-badge');

  // Covered Call card
  const setEl = (id, txt) => { const el = document.getElementById(id); if (el) el.textContent = txt; };
  setEl('eh-cc-strike',    mb.strike_label);
  setEl('eh-cc-premium',   fmt(mb.total_premium_eur));
  setEl('eh-cc-max-value', fmt(mb.max_value_eur));
  setEl('eh-cc-breakeven', fmt(mb.breakeven_price));
  setEl('eh-cc-desc',      mb.description);

  // Protective Put card
  setEl('eh-pp-strike',    sb.strike_label);
  setEl('eh-pp-premium',   fmt(sb.total_premium_eur));
  setEl('eh-pp-floor',     fmt(sb.floor_value_eur));
  setEl('eh-pp-breakeven', fmt(sb.breakeven_price));
  setEl('eh-pp-desc',      sb.description);

  // Portfolio value (monthly candles) + monthly change (±1σ) — shared with the Hedge Workflow
  // Exposure step (hedge-charts.js; extracted verbatim, no behaviour change).
  _portfolioChart = renderMonthlyCandles('eh-portfolio-chart', p.daily, { fmt, prev: _portfolioChart });
  _monthlyChangeChart = renderMonthlyChange('eh-monthly-change-chart', p.daily, {
    prev: _monthlyChangeChart, titleId: 'eh-monthly-chart-title', title: `Monthly Price Change — ${_ehInstrument}`,
  });
}
