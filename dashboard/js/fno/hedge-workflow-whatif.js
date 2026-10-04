// ── Hedge Workflow — What-if step (F39 Phase 3) ──────────────────────────────
// Payoff chart + scenario table + stress table (portfolio-hedge), equity-leg payoff
// and ONE margin-impact number (equity-hedge-scenarios + kite-live). All payoff and
// aggregate maths come from hedge-calc.js — the same code as the old Portfolio Hedge
// page — so numbers match for identical inputs.
//
// Refresh strategy: on step entry (no polling). A coverage-slider change re-renders
// instantly from cached rows, then after 300ms re-fetches portfolio-hedge and discards
// the result if the coverage changed meanwhile. Stale responses are dropped via a
// per-step token.
//
// Margin: kite.margin.required is used only when kite-live is available, non-null and
// INR; otherwise the BSM "Estimated" figure (estimateEquityHedgeMargin). One number is
// shown, never both, never summed across currencies.

import { api, apiFetch } from './api.js';
import { setEl, badge } from '../shared/utils.js';
import { mkChart } from '../shared/charts.js';
import { state } from './state.js';
import {
  buildRows, aggregates, hedgedPL, PAYOFF_MOVES, SCENARIO_MOVES,
  computeNShares, estimateEquityHedgeMargin, estRisk,
} from './hedge-calc.js';
import { hwMarkDirty, authHeaders, TAB_LABELS, STRATEGY_LABELS } from './hedge-workflow-save.js';

const _COVERAGE_REFETCH_MS = 300;
const _CCY_SYMBOL = { EUR: '€', INR: '₹', USD: '$' };

let _wiToken = 0;
let _covTimer = null;

function _hw() { return state.hedgeWorkflow; }

function _esc(v) {
  return String(v ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function _fmtCcy(v, currency) {
  if (v == null || Number.isNaN(Number(v))) return '—';
  const sym = _CCY_SYMBOL[currency] || '€';
  return sym + Number(v).toLocaleString('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function _fmtPct(v, d = 1) {
  return v == null || Number.isNaN(Number(v)) ? '—' : `${Number(v) > 0 ? '+' : ''}${Number(v).toFixed(d)}%`;
}

function _rollingDateRange() {
  const end = new Date();
  const start = new Date();
  start.setFullYear(start.getFullYear() - 1);
  return { start: start.toISOString().slice(0, 10), end: end.toISOString().slice(0, 10) };
}

function _holding(id) {
  return (_hw().portfolioHoldings || []).find((h) => h.instrument_id === id) || null;
}

function _nSharesFor(id) {
  const h = _holding(id);
  return h ? computeNShares(h, _hw().instruments[id], _hw().totalValueEur) : null;
}

// Chosen strategy; falls back to the Recommendation-step default rule when the user
// restored straight into What-if (selections is not persisted).
function _strategy(id) {
  const hw = _hw();
  if (hw.selections[id]) return hw.selections[id];
  const a = (hw.apiHedge?.holdings || []).find((h) => h.instrument_id === id);
  const inst = hw.instruments[id] || {};
  const risk = a?.risk_score ?? inst.risk_score ?? estRisk(inst.daily_return_pct);
  return risk >= 3 ? 'put_buy' : 'call_sell';
}

function _eqKey(id) { return `${id}|${_nSharesFor(id)}`; }

function _rows() {
  const hw = _hw();
  return buildRows(hw.portfolioHoldings, hw.instruments, hw.apiHedge, new Set(hw.hedgedIds), hw.coverage);
}

// ── Fetchers ─────────────────────────────────────────────────────────────────
async function _fetchPortfolioHedge(coverage) {
  const hw = _hw();
  let url = `/api/v1/experience/fno/portfolio-hedge?coverage=${coverage}`;
  if (hw.totalValueEur != null) url += `&total_value_eur=${hw.totalValueEur}`;
  return apiFetch(url, { headers: authHeaders() });
}

async function _fetchEquityScenarios(id) {
  const hw = _hw();
  const nShares = _nSharesFor(id);
  if (nShares == null) return null; // option-only instrument: no invented shares
  const { start, end } = _rollingDateRange();
  const volPos = (hw.positions || []).find((p) => p.und === id && p.ann_vol_pct != null);
  const body = { instrument: id, n_shares: nShares, start_date: start, end_date: end };
  if (volPos) body.ann_vol_pct = parseFloat(volPos.ann_vol_pct);
  try {
    return await api('/api/v1/portfolio/equity-hedge-scenarios', 'POST', body);
  } catch (e) {
    console.warn('[hedge-workflow] equity-hedge-scenarios failed', e);
    return null;
  }
}

function _parseStrike(label) {
  const m = String(label || '').match(/[\d.]+/g);
  return m ? parseFloat(m[m.length - 1]) : null;
}

async function _fetchKite(id, eq) {
  const hw = _hw();
  let url = `/api/v1/experience/fno/kite-live?instrument_id=${encodeURIComponent(id)}`;
  const strategy = _strategy(id);
  const hs = eq?.hedge_scenarios;
  const leg = strategy === 'call_sell' ? hs?.mild_bearish : hs?.strong_bearish;
  const strike = _parseStrike(leg?.strike_label);
  if (strike != null) {
    url += `&strike=${strike}`;
    url += `&option_type=${strategy === 'call_sell' ? 'CE' : 'PE'}`;
    url += `&transaction_type=${strategy === 'call_sell' ? 'SELL' : 'BUY'}`;
  }
  const n = _nSharesFor(id);
  if (n != null) url += `&quantity=${n}`;
  const data = await apiFetch(url, { headers: authHeaders() });
  // No-flash: a failed call leaves the previous liveData untouched.
  if (data) {
    hw.liveData = {
      available: data.available,
      source: data.source,
      lotSize: data.lot_size,
      quote: data.quote,
      margin: data.margin,
      fetchedAt: data.fetched_at,
      instrumentId: id,
    };
  }
}

// ── Margin impact (ONE number) ───────────────────────────────────────────────
function _computeMargin() {
  const hw = _hw();
  const id = hw.instrumentId;
  const eq = id ? hw.eqScenarios[_eqKey(id)] : null;
  const strategy = id ? _strategy(id) : null;
  if (!id || !eq || !strategy) {
    hw.marginImpact = null;
    return;
  }
  const currency = eq.portfolio?.currency || 'EUR';
  const live = hw.liveData;
  if (
    live?.available && live.instrumentId === id && live.margin?.required != null && currency === 'INR'
  ) {
    hw.marginImpact = { amount: live.margin.required, currency, source: 'kite', instrumentId: id, strategy };
    return;
  }
  const amount = estimateEquityHedgeMargin(eq, strategy);
  hw.marginImpact = amount == null
    ? null
    : { amount, currency, source: 'estimated', instrumentId: id, strategy };
}

// ── Rendering ────────────────────────────────────────────────────────────────
function _renderControls() {
  const hw = _hw();
  const input = document.getElementById('hw-wi-coverage-input');
  if (input) input.value = hw.coverage;
  setEl('hw-wi-coverage-label', `${hw.coverage}%`);
  setEl(
    'hw-wi-scenario-tabs',
    Object.entries(TAB_LABELS)
      .map(([k, v]) => {
        const on = k === hw.scenarioTab;
        return `<button onclick="hwSetScenarioTab('${k}')" style="padding:4px 12px;margin-right:6px;border-radius:6px;font-family:var(--fm);font-size:11px;cursor:pointer;background:${on ? '#BE185D' : 'transparent'};color:${on ? '#fff' : '#64748b'};border:1px solid ${on ? '#BE185D' : 'rgba(0,0,0,.12)'}">${v}</button>`;
      })
      .join('')
  );
}

function _renderAggregatesAndTables() {
  const hw = _hw();
  const rows = _rows();
  if (!rows.length) {
    hw.payoff = null;
    setEl('hw-wi-aggregates', `<div class="kpi-sub">Select instruments in the Recommendation step.</div>`);
    setEl('hw-wi-scenario-table', `<div class="kpi-sub">Select instruments</div>`);
    setEl('hw-wi-cost-display', '—');
    setEl('hw-wi-stress-table', `<div class="kpi-sub">Select instruments</div>`);
    mkChart('hw-wi-payoff-chart', { type: 'line', data: { labels: [], datasets: [] } });
    return;
  }
  const agg = aggregates(rows, hw.apiHedge);
  const { totalCost, avgStrike } = agg;
  const hedged = PAYOFF_MOVES.map((m) => parseFloat(hedgedPL(m, hw.scenarioTab, avgStrike, totalCost).toFixed(2)));
  hw.payoff = { moves: PAYOFF_MOVES, hedged, unhedged: PAYOFF_MOVES, aggregates: agg };

  setEl(
    'hw-wi-aggregates',
    `<div class="kpi"><div class="kpi-label">Max drawdown (hedged)</div><div class="kpi-value">${agg.maxDdHedged.toFixed(0)}%</div><div class="kpi-sub">vs ${agg.maxDdUnhedged.toFixed(0)}% unhedged</div></div>
     <div class="kpi"><div class="kpi-label">Monthly cost</div><div class="kpi-value">${totalCost.toFixed(2)}%</div><div class="kpi-sub">premium drag</div></div>`
  );

  const scen = SCENARIO_MOVES.map((m) => {
    const h = hedgedPL(m, hw.scenarioTab, avgStrike, totalCost);
    return `<tr><td>${m === 0 ? 'Flat' : (m > 0 ? '+' : '') + m + '%'}</td><td style="text-align:right">${_fmtPct(m, 0)}</td><td style="text-align:right">${_fmtPct(h, 0)}</td></tr>`;
  }).join('');
  setEl(
    'hw-wi-scenario-table',
    `<table style="width:100%;font-family:var(--fm);font-size:12px;border-collapse:collapse;">
       <thead><tr style="text-align:left;opacity:.7;"><th>Market move</th><th style="text-align:right">Unhedged</th><th style="text-align:right">Hedged (${TAB_LABELS[hw.scenarioTab] || ''})</th></tr></thead>
       <tbody>${scen}</tbody></table>`
  );
  setEl('hw-wi-cost-display', `${totalCost.toFixed(2)}%/mo`);

  // Stress: portfolio-hedge VaR / breach fields for the hedged holdings.
  const apiMap = {};
  for (const h of hw.apiHedge?.holdings || []) apiMap[h.instrument_id] = h;
  const stress = rows
    .map((r) => {
      const a = apiMap[r.id];
      if (!a) return `<tr><td>${_esc(r.id)}</td><td colspan="5">—</td></tr>`;
      const eur = (v) => (v == null ? '—' : '€' + Number(v).toLocaleString('en-US', { maximumFractionDigits: 0 }));
      const pct = (v) => (v == null ? '—' : Number(v).toFixed(1) + '%');
      return `<tr><td>${_esc(r.id)}</td><td>${eur(a.var_95_eur)}</td><td>${pct(a.quarterly_var_pct)}</td><td>${eur(a.quarterly_var_eur)}</td><td>${pct(a.hist_breach_prob_pct)}</td><td>${pct(a.ann_vol_pct)}</td></tr>`;
    })
    .join('');
  setEl(
    'hw-wi-stress-table',
    `<table style="width:100%;font-family:var(--fm);font-size:12px;border-collapse:collapse;">
       <thead><tr style="text-align:left;opacity:.7;"><th>Instrument</th><th>1σ VaR</th><th>Qtr VaR %</th><th>Qtr VaR</th><th>Breach prob.</th><th>Ann. vol</th></tr></thead>
       <tbody>${stress}</tbody></table>`
  );

  mkChart('hw-wi-payoff-chart', {
    type: 'line',
    data: {
      labels: PAYOFF_MOVES.map((m) => m + '%'),
      datasets: [
        { label: 'hedged', data: hedged, borderColor: '#BE185D', borderWidth: 2.5, pointRadius: 0, tension: 0.1, fill: false },
        { label: 'unhedged', data: PAYOFF_MOVES, borderColor: 'rgba(100,116,139,.5)', borderWidth: 1.5, borderDash: [5, 4], pointRadius: 0, fill: false },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: true, position: 'top' },
        tooltip: { mode: 'index', intersect: false, callbacks: { label: (ctx) => `${ctx.dataset.label}: ${ctx.parsed.y.toFixed(1)}%` } },
      },
      scales: {
        x: { title: { display: true, text: 'market move →' }, ticks: { maxTicksLimit: 10 } },
        y: { title: { display: true, text: 'P&L %' }, ticks: { callback: (v) => v + '%' } },
      },
    },
  });
}

function _renderEquityLeg() {
  const hw = _hw();
  const id = hw.instrumentId;
  if (!id) {
    setEl('hw-wi-equity-leg', `<div class="kpi-sub">—</div>`);
    return;
  }
  if (!_holding(id)) {
    setEl('hw-wi-equity-leg', `<div class="kpi-sub">No equity holding for ${_esc(id)} — equity-leg scenarios n/a.</div>`);
    mkChart('hw-wi-equity-payoff-chart', { type: 'line', data: { labels: [], datasets: [] } });
    return;
  }
  const eq = hw.eqScenarios[_eqKey(id)];
  if (!eq) {
    setEl('hw-wi-equity-leg', `<div class="kpi-sub">Equity-leg scenarios — (unavailable)</div>`);
    return;
  }
  const p = eq.portfolio;
  const hs = eq.hedge_scenarios;
  const ccy = p.currency || 'EUR';
  const strategy = _strategy(id);
  const mb = hs.mild_bearish;
  const sb = hs.strong_bearish;
  const lot = hw.liveData?.instrumentId === id && hw.liveData.lotSize != null ? hw.liveData.lotSize : p.lot_size;
  const lotTxt = lot
    ? `${lot} shares/contract${p.n_contracts != null ? ` · ${p.n_contracts} contract${p.n_contracts !== 1 ? 's' : ''}` : ''}`
    : 'no F&amp;O lot';
  const legHtml =
    strategy === 'call_sell'
      ? `<div class="kpi-sub">Covered call: strike ${_esc(mb.strike_label)} · premium ${_fmtCcy(mb.total_premium_eur, ccy)} · max value ${_fmtCcy(mb.max_value_eur, ccy)} · breakeven ${_fmtCcy(mb.breakeven_price, ccy)}</div>`
      : `<div class="kpi-sub">Protective put: strike ${_esc(sb.strike_label)} · premium ${_fmtCcy(sb.total_premium_eur, ccy)} · floor ${_fmtCcy(sb.floor_value_eur, ccy)} · breakeven ${_fmtCcy(sb.breakeven_price, ccy)}</div>`;
  setEl(
    'hw-wi-equity-leg',
    `<div class="kpi-label">${_esc(id)} equity leg — ${STRATEGY_LABELS[strategy]} (${_esc(hs.data_source)})</div>
     <div class="kpi-sub">${p.n_shares} shares · lot: ${lotTxt} · 1y return ${_fmtPct(p.return_pct, 2)} · 30d vol ${p.vol_30d_pct != null ? Number(p.vol_30d_pct).toFixed(1) : '—'}%</div>
     ${legHtml}`
  );
  const pc = hs.payoff_curves;
  if (pc?.price_range) {
    mkChart('hw-wi-equity-payoff-chart', {
      type: 'line',
      data: {
        labels: pc.price_range.map((v) => v.toFixed(0)),
        datasets: [
          { label: 'unhedged', data: pc.unhedged, borderColor: 'rgba(100,116,139,.6)', borderWidth: 1.5, borderDash: [5, 4], pointRadius: 0, fill: false },
          { label: 'covered call', data: pc.covered_call, borderColor: '#0056B8', borderWidth: strategy === 'call_sell' ? 2.5 : 1, pointRadius: 0, fill: false },
          { label: 'protective put', data: pc.protective_put, borderColor: '#BE185D', borderWidth: strategy === 'put_buy' ? 2.5 : 1, pointRadius: 0, fill: false },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: true, position: 'top' } },
        scales: { x: { title: { display: true, text: `price at expiry (${ccy})` }, ticks: { maxTicksLimit: 10 } }, y: { title: { display: true, text: `P&L (${ccy})` } } },
      },
    });
  }
}

function _renderMargin() {
  const m = _hw().marginImpact;
  if (!m) {
    setEl('hw-wi-margin-impact', `<div class="kpi-label">Margin impact</div><div class="kpi-value">—</div>`);
    setEl('hw-wi-live-badge', badge('Estimated'));
    return;
  }
  setEl(
    'hw-wi-margin-impact',
    `<div class="kpi-label">Margin impact (${_esc(m.instrumentId)}, ${STRATEGY_LABELS[m.strategy] || ''})</div>
     <div class="kpi-value">${_fmtCcy(m.amount, m.currency)}</div>`
  );
  setEl('hw-wi-live-badge', badge(m.source === 'kite' ? 'Live' : 'Estimated'));
}

function _renderAll() {
  _renderControls();
  _renderAggregatesAndTables();
  _renderEquityLeg();
  _computeMargin();
  _renderMargin();
}

function _setEmpty(isEmpty) {
  const empty = document.getElementById('hw-wi-empty');
  const content = document.getElementById('hw-wi-content');
  if (empty) empty.style.display = isEmpty ? '' : 'none';
  if (content) content.style.display = isEmpty ? 'none' : '';
  const next = document.getElementById('hw-wi-next-btn');
  if (next) next.disabled = isEmpty;
}

// ── Step entry ───────────────────────────────────────────────────────────────
export async function loadWhatIfStep() {
  const hw = _hw();
  const holdings = hw.portfolioHoldings || [];
  _setEmpty(!holdings.length);
  if (!holdings.length) {
    setEl(
      'hw-wi-empty',
      `<div class="kpi-sub">No holdings yet — build a portfolio first.</div>
       <button onclick="document.querySelector('.nav-item[data-page=\\'equity-scenarios\\']')?.click()"
         style="margin-top:8px;padding:6px 16px;border:none;border-radius:6px;background:var(--p03);color:#fff;font-family:var(--fm);font-size:12px;font-weight:600;cursor:pointer">
         Go to Portfolio Builder
       </button>`
    );
    return;
  }
  const token = ++_wiToken;
  const id = hw.instrumentId;
  setEl('hw-wi-status', 'Loading…');
  _renderAll(); // cached values first (no flash)

  const [hedgeRes, eqRes] = await Promise.allSettled([
    _fetchPortfolioHedge(hw.coverage),
    id ? _fetchEquityScenarios(id) : Promise.resolve(null),
  ]);
  if (token !== _wiToken || hw.instrumentId !== id) return;
  if (hedgeRes.status === 'fulfilled' && hedgeRes.value) hw.apiHedge = hedgeRes.value;
  if (eqRes.status === 'fulfilled' && eqRes.value && id) hw.eqScenarios[_eqKey(id)] = eqRes.value;
  const failed = [];
  if (!(hedgeRes.status === 'fulfilled' && hedgeRes.value)) failed.push('portfolio-hedge');
  if (id && _holding(id) && !(eqRes.status === 'fulfilled' && eqRes.value)) failed.push('equity-leg');
  setEl('hw-wi-status', failed.length ? `Partial data — ${failed.join(', ')} unavailable (estimates shown).` : '');
  _renderAll();

  // kite-live needs the chosen hedge's strike, so it follows the equity response.
  if (id) {
    try {
      await _fetchKite(id, hw.eqScenarios[_eqKey(id)]);
    } catch (e) {
      console.warn('[hedge-workflow] kite-live failed', e);
    }
    if (token !== _wiToken || hw.instrumentId !== id) return;
    _computeMargin();
    _renderMargin();
    _renderEquityLeg();
  }
}

// ── window.hwSetCoverage(val) ────────────────────────────────────────────────
export function hwSetCoverage(val) {
  const hw = _hw();
  const cov = Math.max(0, Math.min(100, parseInt(val, 10)));
  if (Number.isNaN(cov)) return;
  hw.coverage = cov;
  hwMarkDirty();
  _renderControls();
  _renderAggregatesAndTables();
  clearTimeout(_covTimer);
  _covTimer = setTimeout(async () => {
    if (cov !== hw.coverage) return;
    const fresh = await _fetchPortfolioHedge(cov);
    if (fresh && cov === hw.coverage) {
      hw.apiHedge = fresh;
      _renderAggregatesAndTables();
    }
  }, _COVERAGE_REFETCH_MS);
}

// ── window.hwSetScenarioTab(tab) ─────────────────────────────────────────────
export function hwSetScenarioTab(tab) {
  if (!TAB_LABELS[tab]) return;
  _hw().scenarioTab = tab;
  hwMarkDirty();
  _renderControls();
  _renderAggregatesAndTables();
}
