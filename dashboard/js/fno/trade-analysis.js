// ── FnO Trade Analysis (F42 Phase 1) ──────────────────────────────────────────
// Live Kite orders / trades / positions for NIFTY + BANKNIFTY options.
// Flow (ADR-001): browser → RITA Experience endpoint → RITA client → fno-margin-fetch.
// GET /api/v1/experience/fno/trade-analysis/live
// Kite exposes the current trading day only; history accrues via the middleware snapshot.

import { api } from './api.js';
import { setEl } from '../shared/utils.js';
import { fmtPnl, pnlClass } from './utils.js';
import { loadImportPanel } from './trade-import.js';
import { loadAnalyticsPanels } from './trade-analytics.js';

const _PATH = '/api/v1/experience/fno/trade-analysis/live';
const _MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

let _und = 'ALL';
let _month = '';
let _includeClosed = true;
let _monthsFilled = false;

export const _esc = v => String(v == null ? '' : v)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
export const _num = (v, d = 0) => v == null ? '—'
  : Number(v).toLocaleString('en-IN', { minimumFractionDigits: d, maximumFractionDigits: d });
export const _pnl = v => v == null ? '—' : fmtPnl(v);
const _time = v => v == null ? '—' : _esc(String(v).replace('T', ' ').slice(11, 19) || v);

function _reasonText(reason, message) {
  if (reason === 'token_expired') {
    return 'Kite session expired. Log in via the middleware (kite_login.py) and press Refresh.';
  }
  if (reason === 'middleware_unreachable') return 'fno-margin-fetch is not reachable.';
  return message || 'Live Kite data is unavailable.';
}

function _row(cells) {
  return '<tr>' + cells.map(c => `<td>${c}</td>`).join('') + '</tr>';
}

function _fill(id, rows, cols, emptyText) {
  setEl(id, rows.length ? rows.join('')
    : `<tr><td colspan="${cols}" style="color:var(--t3);text-align:center">${emptyText}</td></tr>`);
}

function _fillMonths(months) {
  if (_monthsFilled || !Array.isArray(months) || !months.length) return;
  const sel = document.getElementById('ta-month-select');
  if (!sel) return;
  sel.innerHTML = '<option value="">All expiries</option>'
    + months.map(m => `<option value="${_esc(m)}">${_esc(_MONTHS[m - 1] || m)}</option>`).join('');
  sel.value = _month;
  _monthsFilled = true;
}

function _renderKpis(k) {
  const v = k || {};
  setEl('ta-kpi-orders', k ? `${_num(v.orders_total)} <span style="font-size:11px;color:var(--t3)">`
    + `${_num(v.orders_complete)} done · ${_num(v.orders_rejected)} rej · ${_num(v.orders_cancelled)} canc · ${_num(v.orders_open)} open</span>` : '—');
  setEl('ta-kpi-trades', k ? _num(v.trades_count) : '—');
  setEl('ta-kpi-lots', k ? _num(v.lots_traded, 2) : '—');
  setEl('ta-kpi-open-pos', k ? _num(v.open_positions) : '—');
  setEl('ta-kpi-roundtrips', k ? _num(v.round_trips_today) : '—');
  [['ta-kpi-net-pnl', v.net_pnl], ['ta-kpi-realised', v.realised_pnl], ['ta-kpi-unrealised', v.unrealised_pnl]]
    .forEach(([id, val]) => {
      setEl(id, k ? _pnl(val) : '—');
      const el = document.getElementById(id);
      if (el) el.className = 'kpi-value' + (k && val != null ? ' ' + pnlClass(val) : '');
    });
}

let _liveAvailable = null;

function _render(data) {
  // Live Kite feed lives in a collapsible block: closed (with the reason in its title) when Kite is
  // not connected, opened automatically when data arrives, so the analysis below stays on screen.
  const banner = document.getElementById('ta-status-banner');
  if (banner) {
    banner.style.display = data.available && data.message ? '' : 'none';
    banner.textContent = data.available ? (data.message || '') : '';
  }
  const live = document.getElementById('ta-live-details');
  const state = document.getElementById('ta-live-state');
  if (state) {
    state.textContent = data.available ? '' : `— not connected: ${_reasonText(data.reason, data.message)}`;
    state.style.color = data.available ? '' : '#dc2626';
  }
  if (live && _liveAvailable !== !!data.available) live.open = !!data.available;
  _liveAvailable = !!data.available;
  setEl('ta-history-note', _esc(data.history_note || ''));
  setEl('ta-asof', data.as_of_date ? `As of ${_esc(data.as_of_date)} · Kite live, current day only` : '—');
  _fillMonths((data.filter || {}).expiry_months);
  _renderKpis(data.kpis);

  _fill('ta-expiry-body', (data.by_expiry || []).map(b => _row([
    _esc(b.label), _num(b.trades), _num(b.orders), _num(b.net_quantity), _num(b.open_legs),
    `<span class="${b.pnl == null ? '' : pnlClass(b.pnl)}">${_pnl(b.pnl)}</span>`,
  ])), 6, 'No activity today');

  _fill('ta-orders-body', (data.orders || []).map(o => _row([
    _time(o.order_timestamp), _esc(o.tradingsymbol), _esc(o.transaction_type || '—'), _esc(o.status || '—'),
    _num(o.quantity), _num(o.filled_quantity), _num(o.pending_quantity), _num(o.lots, 2),
    _num(o.average_price, 2), _esc(o.order_type || '—'), _esc(o.product || '—'),
    _esc(o.underlying || '—'), _esc(o.expiry || '—'), _num(o.strike), _esc(o.option_type || '—'), _num(o.lot_size),
  ])), 16, 'No orders today');

  _fill('ta-trades-body', (data.trades || []).map(t => _row([
    _time(t.fill_timestamp), _esc(t.tradingsymbol), _esc(t.transaction_type || '—'),
    _num(t.quantity), _num(t.lots, 2), _num(t.average_price, 2), _esc(t.trade_id || '—'),
    _esc(t.order_id || '—'), _esc(t.underlying || '—'), _esc(t.expiry || '—'),
    _num(t.strike), _esc(t.option_type || '—'), _num(t.lot_size),
  ])), 13, 'No trades today');

  _fill('ta-positions-body', (data.positions || []).map(p => _row([
    _esc(p.tradingsymbol), _esc(p.side || '—'), _num(p.net_quantity), _num(p.lots, 2),
    _num(p.average_price, 2), _num(p.last_price, 2),
    `<span class="${p.pnl == null ? '' : pnlClass(p.pnl)}">${_pnl(p.pnl)}</span>`,
    _pnl(p.m2m), _pnl(p.realised), _pnl(p.unrealised), _esc(p.product || '—'),
    _esc(p.underlying || '—'), _esc(p.expiry || '—'), _num(p.strike), _esc(p.option_type || '—'), _num(p.lot_size),
  ])), 16, 'No open positions');

  const s = data.snapshot || {};
  setEl('ta-snapshot-info', s.available
    ? `Snapshots: ${_num(s.days_captured)} day(s) captured · ${_esc(s.first_date || '—')} → ${_esc(s.last_date || '—')} · ${_num(s.total_trades)} trades stored`
    : 'Snapshot status unavailable (middleware not reachable).');

  const x = data.excluded || {};
  setEl('ta-excluded-note', `Excluded symbols — non-option: ${_num(x.non_option)} · other underlying: ${_num(x.other_underlying)}`
    + ` · out of window: ${_num(x.out_of_window)} · unresolved: ${_num(x.unresolved)}`);
}

function _renderFailure(text) {
  _render({ available: false, message: text, history_note: '', kpis: null });
}

export async function loadTradeAnalysis() {
  taInitTabs();  // idempotent; restores the remembered tab
  loadImportPanel();  // F42 P2 — independent of the live Kite feed; never throws
  loadAnalyticsPanels().catch(() => {});  // F42 P3 — six analytics panels, each fails on its own
  try {
    const qs = new URLSearchParams({ underlying: _und, include_closed: String(_includeClosed) });
    if (_month) qs.set('expiry_month', _month);
    const data = await api(`${_PATH}?${qs.toString()}`);
    if (!data) { _renderFailure('Trade Analysis could not be loaded.'); return; }
    _render(data);
  } catch (e) {
    _renderFailure('Trade Analysis could not be loaded.');
  }
}

// Current page filters (read by the P3 analytics module so it reuses the same selectors).
export function taGetFilters() {
  return { underlying: _und, month: _month };
}

export function taSetUnderlying(und) {
  _und = und || 'ALL';
  return loadTradeAnalysis();
}

export function taSetExpiryMonth(m) {
  _month = m ? String(m) : '';
  return loadTradeAnalysis();
}

export function taSetIncludeClosed(flag) {
  _includeClosed = !!flag;
  return loadTradeAnalysis();
}

export function taRefresh() {
  return loadTradeAnalysis();
}

// ── Page tabs: the page is long, so each group of cards is one tab (visibility only; data loads as before) ──
const _TA_TABS = ['behaviour', 'market', 'suggestions', 'import', 'live'];
const _TA_TAB_KEY = 'rita.fno.tradeAnalysis.tab';

export function taSwitchTab(tab) {
  const active = _TA_TABS.includes(tab) ? tab : _TA_TABS[0];
  document.querySelectorAll('#page-trade-analysis [data-ta-tab]').forEach(el => {
    el.style.display = el.dataset.taTab.split(' ').includes(active) ? '' : 'none';
  });
  document.querySelectorAll('#ta-tabs .ta-tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.taTabbtn === active);
  });
  try { localStorage.setItem(_TA_TAB_KEY, active); } catch (e) { /* storage unavailable: tab simply is not remembered */ }
  // Charts drawn while their tab was hidden need a resize once visible.
  window.dispatchEvent(new Event('resize'));
}

export function taInitTabs() {
  let saved = null;
  try { saved = localStorage.getItem(_TA_TAB_KEY); } catch (e) { /* ignore */ }
  taSwitchTab(saved);
}
