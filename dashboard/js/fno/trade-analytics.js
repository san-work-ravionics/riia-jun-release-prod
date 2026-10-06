// ── FnO Trade Analysis — analytics panels (F42 Phase 3) ──────────────────────────
// Fills the five panels on the Trade Analysis page (overtrading, build-up, market-turn, margin
// trap, suggestions) plus the reconciliation strip.  Six read-only Experience GETs run IN PARALLEL
// (Promise.allSettled); every panel renders independently and fails to "—" on its own.
//   GET /api/v1/experience/fno/trade-analysis/analytics/{foundation,overtrading,buildup,
//       market-turn,margin-trap,suggestions}
// F42 P6: Behaviour + Suggestions rework (headlines, single-row widgets, month-grouped weekly chart, chain ladder,
// cash-vs-exposure chart, two consolidated tables, collapsible suggestion cards).  _cache joins the payloads.
// F42 P4: a seventh GET, .../spot-vs-pnl, feeds ONE collapsed card and is fetched lazily on first
// open (never by the six-panel loader).
// PERSONAL DATA: the payloads are the caller's own rows.  Every server string goes through _esc;
// numbers go through _num / _pnl / _pct.  Descriptive wording only: no causal claims, no advice.

import { api } from './api.js';
import { setEl } from '../shared/utils.js';
import { mkChart, destroyChart } from '../shared/charts.js';
import { _esc, _num, _pnl, taGetFilters } from './trade-analysis.js';

const _BASE = '/api/v1/experience/fno/trade-analysis/analytics/';
const _DISCLAIMER = 'Observations from your own imported history, not investment advice or a forecast.';
const _REASONS = {
  no_data: 'Import your Console files on the Import tab, or load sample data there.',
  no_trades_in_scope: 'No option fills match the selected underlying, expiry and date filters.',
  no_ledger: 'No usable ledger cash history; cash metrics are omitted.',
  spot_unavailable: 'No spot price history for this underlying; the turn analysis is omitted.',
  no_pnl_sheet: 'No P&L sheet imported.',
  no_timestamps: 'Needs execution timestamps, which are missing in too many fills.',
  insufficient_sample: 'Too few days in this sample for this statistic.',
  no_open_positions: 'No open positions to mark.',
  sheet_stale: 'The P&L sheet snapshot is older than the latest spot day.',
  no_trades_for_underlying: 'No option fills for this underlying in the selected scope.',
};
const _PANELS = ['overtrading', 'buildup', 'marketturn', 'margintrap', 'suggestions'];
const _INFO_IDS = [..._PANELS, 'spotpnl'];   // panels with a Definition toggle (spotpnl is the lazy P4 card)
const _VERDICTS = {
  with_market: 'mostly positioned with the market', against_market: 'mostly positioned against the market',
  no_clear_lean: 'no clear lean', insufficient_sample: 'too few days to say',
};
const _ENDPOINTS = {
  foundation: 'foundation', overtrading: 'overtrading', buildup: 'buildup',
  marketturn: 'market-turn', margintrap: 'margin-trap', suggestions: 'suggestions',
};


let _from = '';
let _estimate = null;   // null = server default; set once the user toggles the checkbox
let _seq = 0;
// F42 P4 lazy Spot vs P&L card state
let _spotLoaded = false;   // a successful load happened for _spotKey
let _spotStale = false;    // filters changed (or a refresh was asked for) since the last load
let _spotSeq = 0;          // response-ordering guard
let _spotKey = '';         // the _query() used for the last load
let _spotOpen = false;     // the details card is open
// F42 P6 cross-payload state.  _cache is reset at the START of every loadAnalyticsPanels run and filled
// only after the _seq guard, so no renderer ever reads a payload from a previous run.
const _cache = { overtrading: null, buildup: null, margintrap: null, suggestions: null };
let _chainSel = 0;          // chain picker position (index into the story chains)
const _sgOpen = new Set();  // Suggestions cards the user opened (rule ids); cleared when the filter scope changes
let _sgScope = null;        // the _query() the Set belongs to
let _fullOpen = false;      // legacy "Full data tables" card is open
let _detailBAll = false;    // Table B shows every row instead of the top 10

// ── tiny html helpers (all inputs escaped or numeric) ─────────────────────────────

const _pct = v => v == null ? '—' : `${_num(v, 2)}%`;
const _cls = v => v == null ? '' : (Number(v) >= 0 ? 'pos' : 'neg');
const _dash = v => (v == null || v === '') ? '—' : _esc(v);
// attribute-safe escape (the shared _esc leaves quotes alone)
const _ea = v => _esc(v).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
const _badge = kind => `<span style="font-family:var(--fm);font-size:9px;padding:1px 6px;border-radius:8px;`
  + `margin-left:6px;background:${kind === 'estimated' ? 'rgba(146,72,10,.12)' : 'rgba(26,107,60,.12)'};`
  + `color:${kind === 'estimated' ? '#92480A' : '#1A6B3C'}">${_esc(kind)}</span>`;

// Compact formatters for the single-row widgets: a widget VALUE is at most 8 characters (the full
// precision value goes in the widget's title attribute).  Indian grouping: K, L (lakh), Cr (crore).
const _sgn = n => n < 0 ? '-' : '';
const _f1 = n => n.toFixed(1);
const _html = h => h;   // marks a string already built from escaped/numeric parts (kept out of the template-safety scan)
function _scaled(a) {
  if (a >= 1e10) return '999Cr+';   // beyond 1,000 Cr: the full value is in the widget title
  if (a < 1e3) return `${Math.round(a)}`;
  if (a < 1e5) return `${(a / 1e3).toFixed(1)}K`;
  if (a < 1e7) return `${(a / 1e5).toFixed(1)}L`;
  return a < 1e9 ? `${_f1(a / 1e7)}Cr` : `${Math.round(a / 1e7)}Cr`;
}
export function _numShort(v) {
  if (v == null || Number.isNaN(Number(v))) return '—';
  const n = Number(v), a = Math.abs(n);
  return a < 1e5 ? `${_sgn(n)}${Math.round(a).toLocaleString('en-IN')}` : `${_sgn(n)}${_scaled(a)}`;
}
export function _pnlShort(v) {
  if (v == null || Number.isNaN(Number(v))) return '—';
  const n = Number(v);
  return `₹${_sgn(n)}${_scaled(Math.abs(n))}`;
}
export function _pctShort(v) {
  if (v == null || Number.isNaN(Number(v))) return '—';
  const n = Number(v);
  return Math.abs(n) >= 10000 ? `${n < 0 ? '<-' : '>'}9999%` : `${_f1(n)}%`;
}
export function _ratioShort(v) {
  if (v == null || Number.isNaN(Number(v))) return '—';
  const n = Number(v);
  return Math.abs(n) >= 100 ? `${n < 0 ? '<-' : '>'}99x` : `${_f1(n)}x`;
}

// Widget.  o.compact -> single-row sizing; o.tag -> tiny "est." corner tag (title says "estimated");
// o.title -> full-precision / one-sentence hover text.
const _kpi = (label, valueHtml, cls = '', sub = '', o = {}) => `<div class="kpi${o.compact ? ' kpi-compact' : ''}"`
  + `${o.title ? ` title="${_ea(o.title)}"` : ''}>${o.tag ? '<span class="kpi-est" title="estimated">est.</span>' : ''}`
  + `<div class="kpi-label">${_esc(label)}</div>`
  + `<div class="kpi-value ${cls}">${valueHtml}</div>${sub ? `<div class="kpi-sub">${sub}</div>` : ''}</div>`;
const _ck = (label, valueHtml, cls, sub, o = {}) => _kpi(label, valueHtml, cls, sub, { ...o, compact: true });
// cols: 'c8' | 'c5' | 'c4' = compact single-row widgets inside a container-query host; omitted = legacy grid.
const _kpis = (items, cols) => cols
  ? `<div class="ta-cq"><div class="kpi-row ta-row1 ${cols}">${items.join('')}</div></div>`
  : `<div class="kpi-row c4">${items.join('')}</div>`;
const _th = c => `<th style="padding:6px 8px;text-align:left;font-weight:700;white-space:nowrap">${_esc(c)}</th>`;
const _td = c => `<td style="padding:4px 8px;white-space:nowrap">${c}</td>`;
const _tbl = (title, cols, rows, empty = 'No data') => `<div style="margin:10px 0 4px;font-weight:700;font-size:12px">${_esc(title)}</div>`
  + `<div class="tbl-wrap" style="max-height:200px"><table style="width:100%;border-collapse:collapse;font-size:12px"><thead><tr>`
  + `${cols.map(_th).join('')}</tr></thead><tbody>`
  + (rows.length ? rows.map(r => `<tr>${r.map(_td).join('')}</tr>`).join('')
    : `<tr><td colspan="${cols.length}" style="color:var(--t3);text-align:center">${_esc(empty)}</td></tr>`)
  + '</tbody></table></div>';
const _pnlCell = v => `<span class="${_cls(v)}">${_pnl(v)}</span>`;
const _list = items => `<ul style="margin:4px 0 4px 18px;padding:0">${(items || []).map(i => `<li>${_esc(i)}</li>`).join('')}</ul>`;
const _note = text => `<div class="kpi-sub" style="margin:6px 0">${_esc(text)}</div>`;
const _unavail = (d) => `<div class="kpi-sub">${_esc(d.message || _REASONS[d.reason] || 'Not available.')}</div>`;
const _unavailText = d => _esc(d.message || _REASONS[d.reason] || 'Not available.');
const _join = a => a.filter(Boolean).join(' ');

function _quality(d) {
  const q = d.quality || {};
  return _note(`Fills in scope ${_num(q.fills_in_scope)} · timestamp coverage ${_pct(q.timestamp_coverage_pct)}`
    + ` · spot days missing ${_num(q.spot_days_missing)} · spot last ${_dash(q.spot_last_date)}`
    + ` · expiry-estimated lots ${_num(q.expiry_estimated_lots)} · expiry unknown lots ${_num(q.expiry_unknown_lots)}`);
}

function _infoBlock(label, b) {
  const x = (b && b.info) || b || {};
  if (!x.definition && !(x.assumptions || []).length) return '';
  return `<div style="margin:6px 0"><b>${_esc(label)}</b> ${_esc(x.definition || '')}${_list(x.assumptions)}</div>`;
}

function _defs(d, blocks) {
  const t = d.tags || {};
  return `<div class="kpi-sub" style="margin:6px 0 10px;padding:8px 10px;border:1px dashed var(--border);border-radius:6px">`
    + `<div>${_esc(d.definition || '')}</div>${_list(d.assumptions)}`
    + `<div>Measured: ${_esc((t.measured || []).join(', ') || '—')}</div>`
    + `<div>Estimated: ${_esc((t.estimated || []).join(', ') || '—')}</div>`
    + `${blocks.map(([l, b]) => _infoBlock(l, b)).join('')}</div>`;
}

function _setPanel(key, bodyHtml, defHtml) {
  setEl(`ta-an-${key}-body`, bodyHtml);
  setEl(`ta-an-${key}-def`, defHtml || '');
}
// headline = bold one-sentence summary; html must already be escaped (builders use _esc/_num/_pnl only)
function _setHead(key, headlineHtml) {
  setEl(`ta-an-${key}-headline`, headlineHtml || '');
}
// unavailable / failed panel: the reason takes the headline's place
function _setUnavail(key, d) {
  _setHead(key, _unavailText(d));
  _setPanel(key, '');
}

const _PANEL_CHARTS = {
  overtrading: ['ta-cv-weekly', 'ta-cv-holding'], buildup: ['ta-cv-buildup'], margintrap: ['ta-cv-cash'],
  marketturn: ['ta-cv-turn'],
};
const _PANEL_EXTRA = {
  overtrading: ['ta-an-overtrading-note', 'ta-an-holding-empty'], buildup: ['ta-bu-chain-sel', 'ta-an-buildup-chain-note'],
  suggestions: ['ta-an-sg-summary', 'ta-an-sg-obs', 'ta-an-sg-counts', 'ta-an-sg-grid'],
};

function _fail(key) {
  (_PANEL_CHARTS[key] || []).forEach(id => _chart(id, null));
  (_PANEL_EXTRA[key] || []).forEach(id => setEl(id, ''));
  setEl(`ta-an-${key}-headline`, '');
  setEl(`ta-an-${key}-body`, '<div class="kpi-sub">— could not be loaded</div>');
  setEl(`ta-an-${key}-def`, '');
}

function _chart(id, cfg) {
  if (typeof Chart === 'undefined') return;
  destroyChart(id);
  if (cfg) mkChart(id, cfg);
}

const _axis = { grid: { color: 'rgba(0,0,0,.035)' }, ticks: { font: { family: 'IBM Plex Mono, monospace', size: 10 } } };
const _opts = (extra = {}) => ({ responsive: true, maintainAspectRatio: false, scales: { x: _axis, y: _axis }, ...extra });


// ── panels ──────────────────────────────────────────────────────────────────────────

// ── F42 P6: weekly axis helpers (pure; exported for the node tests) ────────────────────

const _MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const _DAY_MS = 86400000;
const _ymd = ts => { const t = new Date(ts); return { y: t.getUTCFullYear(), m: t.getUTCMonth() + 1, d: t.getUTCDate() }; };

// 'YYYY-Www' (ISO year-week) -> {y, m, d} of that week's MONDAY (m is 1..12).  Date.UTC only: no timezone.
export function taIsoWeekMonday(key) {
  const m = /^(\d{4})-W(\d{2})$/.exec(String(key));
  if (!m) return null;
  const y = Number(m[1]), w = Number(m[2]);
  const wd = new Date(Date.UTC(y, 0, 4)).getUTCDay() || 7;   // ISO weekday of Jan 4 (1 = Monday)
  return _ymd(Date.UTC(y, 0, 4 - (wd - 1) + (w - 1) * 7));
}

const _dmy = p => [p.d, _MON[p.m - 1], p.y].join(' ');
const _rangeText = (a, b) => (a.y === b.y && a.m === b.m)
  ? [a.d, '-', b.d, ' ', _MON[a.m - 1], ' ', a.y].join('')
  : [_dmy(a), ' - ', _dmy(b)].join('');

// Weekly rows -> one bar per Monday (gaps zero-filled).  Month = month of the Monday; Wk n =
// floor((Monday day - 1) / 7) + 1.  Over 104 weeks the axis switches to MONTHLY sums (monthly: true).
export function taWeekAxis(rows) {
  const pts = [];
  (rows || []).forEach(r => {
    const mo = taIsoWeekMonday(r.week);
    if (mo) pts.push({ ts: Date.UTC(mo.y, mo.m - 1, mo.d), r });
  });
  if (!pts.length) return [];
  pts.sort((a, b) => a.ts - b.ts);
  const byTs = new Map(pts.map(p => [p.ts, p.r]));
  const first = pts[0].ts, last = pts[pts.length - 1].ts;
  const nWeeks = Math.round((last - first) / (7 * _DAY_MS)) + 1;
  if (nWeeks > 104) return _monthAxis(pts);
  const bars = [];
  for (let ts = first; ts <= last; ts += 7 * _DAY_MS) {
    const r = byTs.get(ts) || {};
    const mo = _ymd(ts), en = _ymd(ts + 6 * _DAY_MS);
    const wk = Math.floor((mo.d - 1) / 7) + 1;
    const mname = _MON[mo.m - 1];
    bars.push({ key: r.week || [mo.y, mo.m, mo.d].join('-'), monday: mo, month: mname, wk, monthly: false,
      title: ['Wk ', wk, ' · ', mname, ' ', mo.y, ' (', _rangeText(mo, en), ')'].join(''),
      fills: r.fills || 0, closed: r.closed_trades || 0, active_days: r.active_days || 0 });
  }
  const long = bars.length > 26;
  bars.forEach((b, i) => {
    const p = bars[i - 1];
    const newMonth = !p || p.monday.m !== b.monday.m || p.monday.y !== b.monday.y;
    const mon = (i === 0 || b.monday.m === 1) && newMonth ? [b.month, String(b.monday.y % 100).padStart(2, '0')].join(' ') : b.month;
    const wkl = 'Wk ' + b.wk;
    b.label = long ? [newMonth ? mon : ''] : (newMonth ? [wkl, mon] : [wkl]);
  });
  return bars;
}

function _monthAxis(pts) {
  const agg = new Map();
  pts.forEach(p => {
    const mo = _ymd(p.ts), k = mo.y * 12 + mo.m - 1;
    const a = agg.get(k) || { fills: 0, closed: 0, active_days: 0 };
    a.fills += p.r.fills || 0; a.closed += p.r.closed_trades || 0; a.active_days += p.r.active_days || 0;
    agg.set(k, a);
  });
  const ks = [...agg.keys()];
  const lo = Math.min(...ks), hi = Math.max(...ks);
  const bars = [];
  for (let k = lo; k <= hi; k++) {
    const y = Math.floor(k / 12), m = (k % 12) + 1, a = agg.get(k) || { fills: 0, closed: 0, active_days: 0 };
    bars.push({ key: `${y}-${String(m).padStart(2, '0')}`, monday: { y, m, d: 1 }, month: _MON[m - 1], wk: null, monthly: true,
      label: [[_MON[m - 1], String(y % 100).padStart(2, '0')].join(' ')], title: [_MON[m - 1], ' ', y, ' (whole month)'].join(''),
      fills: a.fills, closed: a.closed, active_days: a.active_days });
  }
  return bars;
}

// Alternating faint month bands behind the bars (local plugin, never registered globally).
export const _monthBandsPlugin = {
  id: 'taMonthBands',
  beforeDatasetsDraw(chart, _args, opts) {
    const g = opts && opts.groups, x = chart.scales && chart.scales.x;
    if (!g || !g.length || !x || !chart.chartArea) return;
    const { top, bottom } = chart.chartArea, ctx = chart.ctx;
    const step = g.length > 1 ? x.getPixelForValue(1) - x.getPixelForValue(0) : (x.right - x.left);
    ctx.save();
    ctx.fillStyle = 'rgba(128,128,128,.10)';
    for (let i = 0; i < g.length;) {
      let j = i;
      while (j + 1 < g.length && g[j + 1] === g[i]) j += 1;
      if (g[i] % 2 === 1) {
        const x0 = x.getPixelForValue(i) - step / 2, x1 = x.getPixelForValue(j) + step / 2;
        ctx.fillRect(x0, top, x1 - x0, bottom - top);
      }
      i = j + 1;
    }
    ctx.restore();
  },
};

function _weeklyChartCfg(axis) {
  let grp = -1, prev = '';
  const groups = axis.map(a => { const k = [a.monday.y, a.monday.m].join('-'); if (k !== prev) { grp += 1; prev = k; } return grp; });
  const tick = { ..._axis.ticks, autoSkip: false, maxRotation: 0, font: { family: 'IBM Plex Mono, monospace', size: 10 } };
  return {
    type: 'bar',
    data: { labels: axis.map(a => a.label), datasets: [   // position-indexed: labels repeat, never key data by label
      { label: 'Fills', data: axis.map(a => a.fills), backgroundColor: 'rgba(0,86,184,.55)', borderRadius: 3 },
      { label: 'Closed trades', data: axis.map(a => a.closed), backgroundColor: 'rgba(26,107,60,.55)', borderRadius: 3 }] },
    options: _opts({
      plugins: { taMonthBands: { groups }, legend: { labels: { boxWidth: 10, font: { size: 10 } } },
        tooltip: { callbacks: { title: items => (axis[items[0].dataIndex] || {}).title || '',
          afterBody: items => [`${_num((axis[items[0].dataIndex] || {}).active_days)} active days`] } } },
      scales: { x: { ..._axis, grid: { display: false }, ticks: tick }, y: _axis } }),
    plugins: [_monthBandsPlugin],
  };
}

function _renderHoldingChart(h) {
  const b = (h && h.buckets) || [];
  const has = b.some(r => r.count > 0);
  _chart('ta-cv-holding', has ? {
    type: 'bar',
    data: { labels: b.map(r => r.label), datasets: [{ label: 'Closed same-day trades', data: b.map(r => r.count),
      backgroundColor: 'rgba(146,72,10,.5)', borderRadius: 3 }] },
    options: _opts({ plugins: { legend: { display: false } } }),
  } : null);
  setEl('ta-an-holding-empty', has ? (h.median_minutes != null ? `Same-day median ${_num(h.median_minutes, 1)} minutes` : '')
    : 'No same-day trades');
}

// ── Overtrading ───────────────────────────────────────────────────────────────────────

function _headlineOvertrading(d) {
  const a = d.activity || {}, c = d.churn || {}, ch = d.charges || {};
  const days = a.market_days != null ? `${_num(a.active_days)} of ${_num(a.market_days)} market days` : `${_num(a.active_days)} active days`;
  const med = (a.fills_per_day || {}).median;
  let t = `You placed ${_num(a.fills_total)} executions on ${days}${med != null ? ` (typically ${_num(med, 0)} on an active day)` : ''}.`;
  const parts = [];
  if (c.churn_qty_pct != null) parts.push(`${_pct(c.churn_qty_pct)} of the quantity in your closed trades was opened and closed on the same day`);
  if (ch.net_gross_negative) parts.push('estimated charges were paid while gross P&L was not positive');
  else if (ch.pct_of_gross != null) parts.push(`estimated charges equal ${_pct(ch.pct_of_gross)} of your gross P&L`);
  if (parts.length) { const s = parts.join(', and '); t += ' ' + s.charAt(0).toUpperCase() + s.slice(1) + '.'; }
  return t;
}

function _renderOvertrading(d) {
  _cache.overtrading = d;
  ['ta-cv-weekly', 'ta-cv-holding'].forEach(id => _chart(id, null));
  setEl('ta-an-overtrading-note', '');
  setEl('ta-an-holding-empty', '');
  if (!d.available) { _setUnavail('overtrading', d); return; }
  const a = d.activity || {}, w = d.winloss || {}, c = d.churn || {}, ch = d.charges || {}, h = d.holding || {};
  const b = d.bursts || {};
  const fpd = a.fills_per_day || {};
  const nz = ch.net_gross_negative;
  const kp = _kpis([
    _ck('Executions', _numShort(a.fills_total), '', `${_numShort(a.orders_total)} orders`,
      { title: `One order can produce several fills (executions). ${_num(a.fills_total)} executions from ${_num(a.orders_total)} orders.` }),
    _ck('Active days', _numShort(a.active_days), '', `of ${_numShort(a.market_days)} market days`,
      { title: 'Days on which you traded.' }),
    _ck('Fills per active day', _numShort(fpd.median), '', `max ${_numShort(fpd.max)}`,
      { title: `Typical number of fills on a day you traded. Mean ${_num(fpd.mean, 1)}, 90th percentile ${_num(fpd.p90, 1)}, max ${_num(fpd.max)}.` }),
    _ck('Same-day in-and-out', _pctShort(c.churn_qty_pct), '', `${_numShort(c.same_day_trades)} trades`,
      { title: `Share of closed quantity that was opened and closed on the same day. Gross P&L of those trades ${_pnl(c.churn_pnl)}.` }),
    _ck('Charges vs gross P&L', nz ? '—' : _pctShort(ch.pct_of_gross), '', nz ? 'gross not positive' : `${_pnlShort(ch.est_window)} est.`,
      { tag: 'est.', title: 'Brokerage and taxes are an estimate. Charges as a share of gross P&L.' }),
    _ck('Trades to cover charges', _numShort(ch.breakeven_trades_needed), '', `${_pnlShort(ch.per_closed_trade)}/trade`,
      { title: `Closed trades needed at the average gross per trade (${_pnl(ch.per_closed_trade)}) to pay the charges.` }),
    _ck('Win rate', _pctShort(w.win_rate), '', `${_numShort(w.wins)}W ${_numShort(w.losses)}L ${_numShort(w.scratch)}S`,
      { title: `Share of closed trades with a profit: ${_num(w.wins)} wins, ${_num(w.losses)} losses, ${_num(w.scratch)} scratch.` }),
    _ck('Avg win vs avg loss', _ratioShort(w.payoff), '', `exp. ${_pnlShort(w.expectancy)}/trade`,
      { title: `Average win divided by average loss. Expectancy ${_pnl(w.expectancy)} per closed trade; breakeven win rate ${_pct(w.breakeven_win_rate)}.` }),
  ], 'c8');
  _setHead('overtrading', _headlineOvertrading(d));
  _setPanel('overtrading', _quality(d) + kp,
    _defs(d, [['Activity.', a], ['Holding time.', h], ['Churn.', c], ['Bursts and re-entries.', b], ['Charges (estimate).', ch], ['Win / loss.', w]]));
  _chart('ta-cv-weekly', (d.weekly || []).length ? _weeklyChartCfg(taWeekAxis(d.weekly)) : null);
  _renderHoldingChart(h);
  const re = b.reentries_after_loss || {};
  setEl('ta-an-overtrading-note', b.available
    ? _esc(`${_num(b.count)} fast bursts; ${_num(re.count)} re-entries shortly after a loss (P&L ${_pnl(re.pnl)}).`)
    : _esc(`Bursts and re-entries: ${_REASONS[b.reason] || 'not available'}`));
}


// ── Position build-up (chain ladder) ────────────────────────────────────────────────

// The picker shows exactly the chains the SERVER ranked (story_rank, same ordering as chains[]), no re-sort.
// Older servers send no story_rank: the first chains (already P&L-ascending) get a schematic only.
function _storyChains(d) {
  const all = d.chains || [];
  const ranked = all.filter(c => c.story_rank != null).sort((a, b) => a.story_rank - b.story_rank);
  return ranked.length ? ranked : all.slice(0, 3);
}

const _size = (c, lotsOk) => lotsOk && c.peak_lots != null ? `${_num(c.peak_lots, 1)} lots` : `${_num(c.peak_qty)} units`;

function _headlineBuildup(d) {
  const ct = d.chain_totals || {}, ch = _storyChains(d), w = ch[0];
  if (!ct.count) return 'No position chains in this scope.';
  const adv = ct.with_adverse_add;
  let t = adv
    ? `${_num(adv)} of your ${_num(ct.count)} position chains were added to at a worse price.`
    : `None of your ${_num(ct.count)} position chains were added to at a worse price.`;
  if (w) {
    const lotsOk = w.peak_lots != null;
    t += ` Worst chain: ${_esc(w.symbol)} (${_esc(w.side)}) — you added ${_num(w.adds)} times, ${_num(w.adverse_adds)} at a worse price,`
      + ` the position peaked at ${_size(w, lotsOk)}${w.still_open ? ' and is still open' : ` and closed at ${_pnl(w.pnl_measured)}`}.`;
  }
  const ev = d.events || {};
  const entries = (ev.open_new || 0) + (ev.scale_in || 0);
  if (entries) t += ` ${_num(ev.scale_in)} of your ${_num(entries)} entries were adds to an existing position.`;
  return t;
}

function _renderChainPicker(chains) {
  setEl('ta-bu-chain-sel', chains.length
    ? chains.map((c, i) => `<button class="ta-chip${i === _chainSel ? ' active' : ''}" data-chain="${i}" onclick="taAnChainPick(${i})">`
      + `${_esc(c.symbol)} · ${_esc(_pnlShort(c.pnl_measured))}</button>`).join('')
    : '');
}

function _stepColor(s) {
  if (s.adverse) return '#9B1C1C';
  return s.cls === 'scale_in' ? '#1A6B3C' : '#8C877A';
}

const _dlabel = iso => iso.slice(8, 10) + ' ' + (_MON[Number(iso.slice(5, 7)) - 1] || '');
const _stepLabel = s => _dlabel(s.date) + (s.time ? ' ' + s.time : '');
const _CLS_TEXT = { open_new: 'opened', scale_in: 'added', scale_out: 'reduced', close: 'closed', flip: 'flipped' };

function _renderChainLadder(c) {
  _chart('ta-cv-buildup', null);
  setEl('ta-an-buildup-chain-note', '');
  if (!c) return;
  const steps = c.steps || [];
  const lotsOk = steps.length > 0 && steps.every(s => s.lots_after != null);
  let labels, sizes, colors, radius, tipSteps = null;
  const unit = (steps.length ? lotsOk : c.peak_lots != null) ? 'lots' : 'units';
  if (steps.length) {
    labels = steps.map(_stepLabel);
    sizes = steps.map(s => lotsOk ? s.lots_after : Math.abs(s.pos_after));
    colors = steps.map(_stepColor);
    radius = steps.map(s => s.adverse ? 6 : (s.cls === 'scale_in' ? 5 : 3));
    tipSteps = steps;
  } else {   // schematic fallback: open -> peak -> close; never an empty chart
    const peak = c.peak_lots != null ? c.peak_lots : c.peak_qty;
    labels = [c.open_date || 'open', 'peak size', c.close_date || 'now'];
    sizes = [0, peak, c.still_open ? peak : 0];
    colors = ['#8C877A', '#8C877A', '#8C877A'];
    radius = [3, 3, 3];
    setEl('ta-an-buildup-chain-note', _esc('Per-fill detail needs a newer server; showing a three-point outline.'));
  }
  const datasets = [{ label: `Position size (${unit})`, data: sizes, stepped: 'after',
    borderColor: '#0056B8', borderWidth: 1.5, pointBackgroundColor: colors, pointBorderColor: colors, pointRadius: radius, fill: false }];
  const last = steps.length ? steps[steps.length - 1] : null;
  if (last && last.pos_after === 0) {   // the close: an x point carrying the chain P&L
    const idx = steps.length - 1;
    datasets.push({ label: `Closed: ${_pnlShort(c.pnl_measured)}`, data: sizes.map((v, i) => i === idx ? v : null), showLine: false,
      pointStyle: 'crossRot', pointRadius: 9, pointBorderWidth: 2, pointBorderColor: '#1A1814', borderColor: '#1A1814' });
  }
  _chart('ta-cv-buildup', {
    type: 'line',
    data: { labels, datasets },
    options: _opts({
      plugins: { legend: { labels: { boxWidth: 10, usePointStyle: true, font: { size: 10 } } },
        tooltip: { callbacks: { afterBody: items => {
          const s = tipSteps && tipSteps[items[0].dataIndex];
          if (!s) return [];
          const kind = _CLS_TEXT[s.cls] || s.cls;
          const out = [`${_dash(kind)}: ${_num(Math.abs(s.qty_delta))} units at ${_num(s.price, 2)}`];
          if (s.avg_before != null) out.push(`your average before this fill: ${_num(s.avg_before, 2)}`);
          if (s.adverse) out.push(`added ${_num(s.worse_pct, 1)}% worse than your average`);
          return out;
        } } } },
      scales: { x: { ..._axis, ticks: { ..._axis.ticks, maxTicksLimit: 10 } }, y: { ..._axis, beginAtZero: true, title: { display: true, text: unit, font: { size: 10 } } } } }),
  });
  if (c.steps_truncated) {
    setEl('ta-an-buildup-chain-note', _esc(`Showing ${_num(steps.length)} of ${_num(c.steps_total)} fills (first, last and all adds at a worse price are kept).`));
  }
}

// re-renders ONLY the chart (and the picker highlight) from the cached build-up payload
export function taAnChainPick(i) {
  const d = _cache.buildup;
  if (!d || !d.available) return;
  const ch = _storyChains(d);
  if (!ch.length) return;
  _chainSel = Math.min(Math.max(Number(i) || 0, 0), ch.length - 1);
  _renderChainPicker(ch);
  _renderChainLadder(ch[_chainSel]);
}

function _renderBuildup(d) {
  _cache.buildup = d;
  _chart('ta-cv-buildup', null);
  setEl('ta-bu-chain-sel', '');
  setEl('ta-an-buildup-chain-note', '');
  if (!d.available) { _setUnavail('buildup', d); return; }
  const av = d.averaging || {}, ct = d.chain_totals || {}, lots = d.lots || {};
  const advLots = av.adverse_add_lots != null ? ` (${_num(av.adverse_add_lots, 1)} lots)` : '';
  const kp = _kpis([
    _ck('Adds at a worse price', _numShort(av.adverse_add_fills), '', `${_pctShort(av.share_of_entries_pct)} of entries`,
      { title: `${_num(av.adverse_add_fills)} fills, ${_num(av.adverse_add_units)} units${advLots}, that increased a position at a price worse than your average entry.` }),
    _ck('Closed P&L of those adds', _pnlShort(av.adverse_add_closed_pnl), _cls(av.adverse_add_closed_pnl),
      `${_numShort(av.adverse_add_open_units)} units still open`,
      { title: `Gross P&L of the slices those adds opened (${_pnl(av.adverse_add_closed_pnl)}). Slices still open are counted as units and not priced.` }),
    _ck('Most adds in one chain', _numShort(ct.max_adds), '', `of ${_numShort(ct.count)} chains`,
      { title: `${_num(ct.with_adverse_add)} of ${_num(ct.count)} chains had at least one add at a worse price.` }),
    _ck('Adds after a worse spot move', av.spot_adverse_adds == null ? '—' : _numShort(av.spot_adverse_adds), '', 'needs spot data',
      { title: 'Adds made after the market had already moved against the position since it was first opened.' }),
  ], 'c4');
  const lotNote = _note(lots.lots_available ? `Lots from the Kite master (${_esc(lots.lots_basis)}, ${_pct(lots.coverage_pct)} of symbols)`
    : 'Lots unavailable (Kite master not reachable): quantities shown in units.');
  _setHead('buildup', _headlineBuildup(d));
  _setPanel('buildup', _quality(d) + kp + lotNote,
    _defs(d, [['Adverse adds.', av], ['Chains.', d.chains_info], ['Timeline.', d.timeline_info]]));
  const ch = _storyChains(d);
  _chainSel = 0;
  _renderChainPicker(ch);
  _renderChainLadder(ch[0]);
  if (!ch.length) setEl('ta-an-buildup-chain-note', _esc('No position chains to draw.'));
}


function _renderMarketTurn(d) {
  _chart('ta-cv-turn', null);
  if (!d.available) { _setPanel('marketturn', _unavail(d)); return; }
  const k = d.kpis || {}, sp = d.spot || {};
  const kp = _kpis([
    _kpi('Reversal days', _num(k.n_turn_days), '', `${_num(k.n_big_move_days)} big-move days`),
    _kpi('Adverse-exposed', _pct(k.adverse_exposed_pct), '', `${_num(k.n_adverse_exposed)} of ${_num(k.n_turn_days)} reversal days`),
    _kpi('Realised on adverse turns', _pnl(k.realised_pnl_turn_adverse), _cls(k.realised_pnl_turn_adverse),
      `carried in ${_pnl(k.realised_from_carried_in)} · opened that day ${_pnl(k.realised_from_opened_that_day)}`),
    _kpi('Avg realised, other days', _pnl(k.avg_realised_other_days), _cls(k.avg_realised_other_days)),
  ]);
  const worst = _tbl('Largest realised-loss days (drawdown days)', ['Date', 'Realised P&L', 'Open at end of day'],
    (d.worst_days || []).map(r => [_esc(r.date), _pnlCell(r.realised_pnl_day), _esc((r.open_symbols || []).join(', '))]), 'No loss days');
  let turn = '';
  if (sp.available) {
    turn = _tbl('Big-move days', ['Date', 'Underlying', 'Spot close', 'Move %', 'Reversal', 'Positioning in', 'Adverse', 'Realised P&L', 'Delta-1 bound (est.)', 'Open in'],
      (d.turn_days || []).map(r => [_esc(r.date), _esc(r.underlying), _num(r.spot_close, 2), _num(r.ret_pct, 2),
        r.is_reversal ? 'yes' : 'no', `${_esc(r.bias_label)} (${_num(r.bias_units_in)})`, r.adverse_exposed ? 'yes' : 'no',
        _pnlCell(r.realised_pnl_day), _pnlCell(r.delta1_bound_pnl), _esc((r.open_symbols_in || []).join(', '))]), 'No big-move days')
      + _note(d.delta1_note || '')
      + (sp.stale ? _note('Spot history looks stale: the last close is more than a few days old.') : '');
  } else {
    turn = _unavail({ reason: 'spot_unavailable' });
  }
  _setPanel('marketturn', _quality(d) + kp + turn + worst, _defs(d, [['Market turns.', d.info]]));
  const s = (d.series || [])[0];
  _chart('ta-cv-turn', s && s.dates.length ? {
    data: { labels: s.dates, datasets: [
      { type: 'line', label: s.underlying + ' close', data: s.spot_close, borderColor: '#0056B8', borderWidth: 1.5, pointRadius: 1, yAxisID: 'y', order: 1 },
      { type: 'bar', label: 'Positioning bias (units)', data: s.bias_units, backgroundColor: 'rgba(146,72,10,.45)', yAxisID: 'y1', order: 2 }] },
    options: _opts({ scales: { x: _axis, y: { ..._axis, position: 'left' }, y1: { ..._axis, position: 'right', grid: { drawOnChartArea: false } } } }),
  } : null);
}

// ── Margin trap (cash vs exposure) ───────────────────────────────────────────────────

const _MAX_CASH_POINTS = 400;

// Indices of cash_series rows to draw.  Over 400 days every k-th day is kept, but trap days (cash below the
// threshold with open losers) and add days are ALWAYS kept so the markers never vanish.  Pure; exported.
export function _cashIdx(cs, thr) {
  if (cs.length <= _MAX_CASH_POINTS) return cs.map((_, i) => i);
  const k = Math.ceil(cs.length / _MAX_CASH_POINTS);
  return cs.map((_, i) => i).filter(i => i % k === 0 || i === cs.length - 1
    || (cs[i].cash != null && cs[i].cash < thr && (cs[i].open_losers_count || 0) > 0) || (cs[i].adverse_add_units || 0) > 0);
}

export const _dayBandsPlugin = {
  id: 'taDayBands',
  beforeDatasetsDraw(chart, _args, opts) {
    const x = chart.scales && chart.scales.x;
    if (!opts || !x || !chart.chartArea) return;
    const { top, bottom } = chart.chartArea, ctx = chart.ctx;
    const n = (chart.data.labels || []).length;
    const step = n > 1 ? x.getPixelForValue(1) - x.getPixelForValue(0) : (x.right - x.left);
    const band = (i0, i1, fill) => {
      ctx.fillStyle = fill;
      const x0 = x.getPixelForValue(i0) - step / 2, x1 = x.getPixelForValue(i1) + step / 2;
      ctx.fillRect(x0, top, x1 - x0, bottom - top);
    };
    ctx.save();
    (opts.streaks || []).forEach(([a, b]) => band(a, b, 'rgba(217,119,6,.14)'));
    (opts.low || []).forEach(i => band(i, i, 'rgba(155,28,28,.10)'));
    ctx.restore();
  },
};

// {low: [chart idx of days below the threshold], streaks: [[first idx, last idx]]} on the drawn subset
export function _bandRanges(cs, idx, thr, streaks) {
  const low = [];
  idx.forEach((si, ci) => { if (cs[si].cash != null && cs[si].cash < thr) low.push(ci); });
  const out = [];
  (streaks || []).forEach(s => {
    let a = -1, b = -1;
    idx.forEach((si, ci) => { if (cs[si].date >= s.start && cs[si].date <= s.end) { if (a < 0) a = ci; b = ci; } });
    if (a >= 0) out.push([a, b]);
  });
  return { low, streaks: out };
}

const _filterActive = () => { const f = taGetFilters() || {}; return (f.underlying && f.underlying !== 'ALL') || !!f.month; };

function _headlineMarginTrap(d) {
  const l = d.ledger || {}, c = d.cash || {}, t = d.trap || {};
  if (!l.available) return `${_unavailText(d)} Import your Console ledger to see this panel.`;
  const thr = `₹${_num(c.threshold)}`;
  if (!t.days) return `Cash stayed above ${thr} on every day that you held a losing position.`;
  const g = t.loss_growth_est, a = t.adds_on_low_cash;
  let s = `In the selected scope, on ${_num(t.days)} days your account cash was below ${thr} while you held positions that were at a loss (estimate).`;
  if (g) {
    s += ` On the first such day ${_num(g.symbols_n)} positions showed about ${_pnl(g.loss_at_first_trap_est)} of loss (estimate);`
      + ` the same positions closed at ${_pnl(g.final_closed_pnl)} in total.`;
  }
  if (a) s += ` You added ${_num(a.adverse_fills)} fills at a worse price on low-cash days.`;
  if (_filterActive()) s += ' (cash: whole account; positions and adds: selected underlying/expiry)';
  return s;
}

function _marginKpis(d) {
  const l = d.ledger || {}, c = d.cash || {}, t = d.trap || {};
  if (!l.available) return [];
  const worst = (d.debit_streaks || []).reduce((m, r) => Math.max(m, r.days || 0), 0);
  const a = t.adds_on_low_cash;
  const items = [
    _ck('Lowest cash', _pnlShort(c.min), _cls(c.min), `on ${_esc(c.min_date || '—')}`, { title: `Lowest ledger cash ${_pnl(c.min)} on ${_dash(c.min_date)}.` }),
    _ck(`Days below ${_pnlShort(c.threshold)}`, _numShort(c.days_below_threshold), '', `${_numShort(c.days_negative)} negative`,
      { title: `Days with ledger cash below ${_pnl(c.threshold)}; ${_num(c.days_negative)} of them negative.` }),
    _ck('Longest debit streak', `${_numShort(worst)}d`, '', `${_numShort((d.debit_streaks || []).length)} streaks`,
      { title: 'Longest run of 3 or more days when more money went out than came in.' }),
    _ck('Low-cash days with open losers', _numShort(t.days), '', 'proxy, no cause shown',
      { tag: 'est.', title: 'Days when ledger cash was below the level while at least one open position was at a loss (estimate).' }),
  ];
  if (a) {
    items.push(_ck('Adds on low-cash days (selected scope)', _numShort(a.fills), '', `${_numShort(a.adverse_units)} units worse`,
      { title: `${_num(a.fills)} fills (${_num(a.units)} units) added to positions on low-cash days; ${_num(a.adverse_fills)} fills (${_num(a.adverse_units)} units) at a worse price than your average.` }));
  }
  return items;
}

function _cashChartCfg(d) {
  const c = d.cash || {}, cs = d.cash_series || [], thr = c.threshold;
  const idx = _cashIdx(cs, thr), rows = idx.map(i => cs[i]);
  const hasExp = rows.some(r => r.short_notional_proxy != null);
  const hasAdd = rows.some(r => (r.adverse_add_units || 0) > 0);
  const datasets = [
    { type: 'line', label: 'Cash in your account (ledger)', data: rows.map(r => r.cash), borderColor: '#0056B8', borderWidth: 1.5, pointRadius: 0, fill: false, yAxisID: 'y', order: 2 },
    { type: 'line', label: 'Low-cash level', data: rows.map(() => thr), borderColor: '#9B1C1C', borderWidth: 1, borderDash: [6, 4], pointRadius: 0, fill: false, yAxisID: 'y', order: 3 },
  ];
  if (hasExp) datasets.push({ type: 'bar', label: 'Short option exposure (estimate)', data: rows.map(r => r.short_notional_proxy), backgroundColor: 'rgba(234,120,20,.40)', yAxisID: 'y1', order: 4 });
  if (hasAdd) datasets.push({ type: 'line', label: 'Added at a worse price', data: rows.map(r => (r.adverse_add_units || 0) > 0 ? r.cash : null),
    showLine: false, pointStyle: 'circle', pointRadius: 5, pointBackgroundColor: '#9B1C1C', pointBorderColor: '#9B1C1C', yAxisID: 'y', order: 1 });
  const scales = { x: { ..._axis, ticks: { ..._axis.ticks, maxTicksLimit: 10 } }, y: { ..._axis, position: 'left' } };
  if (hasExp) scales.y1 = { ..._axis, position: 'right', grid: { drawOnChartArea: false } };
  return {
    data: { labels: rows.map(r => _dlabel(r.date)), datasets },
    options: _opts({
      plugins: { taDayBands: _bandRanges(cs, idx, thr, d.debit_streaks), legend: { labels: { boxWidth: 10, usePointStyle: true, font: { size: 10 } } },
        tooltip: { callbacks: {
          title: items => (rows[items[0].dataIndex] || {}).date || '',
          afterBody: items => {
            const r = rows[items[0].dataIndex] || {};
            const out = [];
            if ((r.adverse_add_units || 0) > 0) out.push(`added ${_num(r.adverse_add_units)} units at a worse price`);
            if ((r.open_losers_count || 0) > 0) out.push(`${_num(r.open_losers_count)} open losers (est. ${_pnl(r.known_loss_est)})`);
            return out;
          } } } },
      scales }),
    plugins: [_dayBandsPlugin],
  };
}

function _renderMarginTrap(d) {
  _cache.margintrap = d;
  _chart('ta-cv-cash', null);
  if (!d.available) { _setUnavail('margintrap', d); return; }
  const l = d.ledger || {}, c = d.cash || {}, t = d.trap || {}, ex = d.exposure || {};
  const items = _marginKpis(d);
  const ledgerNote = l.available
    ? _note(`Cash is MEASURED from the ledger (account-wide, settled cash only; sign auto-detected, match ${_pct(l.balance_sign_match_pct)}). `
      + `${_num(l.ledger_gap_days)} carried-forward days · ${_num(l.ordering_ambiguous_days)} ambiguous-order days. `
      + `Exposure proxy covers in-scope symbols only: peak short notional ${_pnl(ex.peak_short_notional_proxy)} (estimate, not margin).`)
    : '';
  _setHead('margintrap', _headlineMarginTrap(d));
  _setPanel('margintrap', _quality(d) + (items.length ? _kpis(items, 'c5') : '') + ledgerNote,
    _defs(d, [['Cash and streaks.', c], ['Low-cash days with open losers.', t]]));
  _chart('ta-cv-cash', l.available && (d.cash_series || []).length ? _cashChartCfg(d) : null);
}


// ── Stops table (ONE builder: used inside the Suggestions stop-discipline card and the legacy full tables) ──

const _STOP_COLS = [
  ['Multiple', 'Stop level as a multiple of the premium you received.'],
  ['Trades beyond', 'Closed short trades whose loss went beyond that stop level.'],
  ['Loss beyond stop', 'The part of those losses that lay beyond the stop level.'],
  ['Saved if stopped (est.)', 'What stopping at the level would have saved, assuming the stop fills at the level (estimate).'],
  ['% of total loss', 'Share of your total realised loss that this saving represents.'],
  ['Open beyond (est.)', 'Open short positions already beyond the level, and their excess loss (estimate).'],
];

function _stopsTable(st) {
  const rows = (st.rows || []).map(r => [`${_num(r.multiple, 2)}x`, _num(r.n_exceeded), _pnl(r.realised_loss_exceeding),
    _pnlCell(r.saved_if_stopped), _pct(r.share_of_total_loss_pct), `${_num(r.open_beyond_n)} · ${_pnl(r.open_beyond_excess_est)}`]);
  return _tbl('Planned vs actual: stop at a multiple of premium (closed short trades)', _STOP_COLS.map(c => c[0]), rows, 'No stop what-if rows')
    + `<div class="kpi-sub">${_STOP_COLS.map(c => `<div><b>${_esc(c[0])}</b>: ${_esc(c[1])}</div>`).join('')}</div>`
    + `<div class="kpi-sub" style="margin:6px 0">${_esc(`${_num(st.long_closed_excluded)} closed long trades are excluded (loss bounded by premium). One-sided: whipsaw stops and slippage cannot be seen.`)}${_badge('estimated')}</div>`;
}

// ── Consolidated details: Table A and Table B ──────────────────────────────────────

const _tip = (h, t) => `<th title="${_ea(t)}" style="padding:6px 8px;text-align:left;font-weight:700;white-space:nowrap">${_esc(h)}</th>`;
const _pill = k => `<span style="font-family:var(--fm);font-size:9px;padding:1px 6px;border-radius:8px;background:var(--surface2);border:1px solid var(--border)">${_esc(k)}</span>`;
const _byPnl = (a, b) => (a.pnl == null) - (b.pnl == null) || (a.pnl - b.pnl) || String(a.when).localeCompare(String(b.when));

const _A_COLS = [
  ['Group', 'A section header, then one row per value.'], ['Executions', 'Fills in that group (blank for side rows: only closed trades are known there).'],
  ['Closed trades', 'Trades fully closed in that group.'], ['Win rate', 'Share of those closed trades that made money.'],
  ['P&L', 'Realised P&L of those closed trades.'],
];

function _tableA(d) {
  if (!d) return '<div class="kpi-sub">— could not be loaded</div>';
  if (!d.available) return _unavail(d);
  const w = d.winloss || {}, mo = w.measured_only || {};
  const grp = (title, list, cnt) => [`<tr><td colspan="5" style="padding:6px 8px;font-weight:700;background:var(--surface2)">${_esc(title)}</td></tr>`]
    .concat([...list].sort((x, y) => (x.pnl == null) - (y.pnl == null) || (x.pnl - y.pnl)).map(r => `<tr>${[
      _esc(r.key), cnt ? _num(r.fills) : '—', _num(cnt ? r.closed_trades : r.n), _pct(r.win_rate), _pnlCell(r.pnl)].map(_td).join('')}</tr>`));
  const rows = [...grp('By underlying', d.by_underlying || [], true), ...grp('By expiry month', d.by_expiry || [], true),
    ...grp('By side', w.by_side || [], false)];
  return `<div style="font-weight:700;font-size:12px">Where your results came from</div>`
    + `<div class="kpi-sub">Closed trades and their realised P&amp;L, split by underlying, expiry month and side. Worst P&amp;L first inside each group.</div>`
    + `<div class="ta-tbl-wrap"><table style="width:100%;border-collapse:collapse;font-size:12px"><thead><tr>${_A_COLS.map(c => _tip(c[0], c[1])).join('')}</tr></thead>`
    + `<tbody>${rows.join('')}</tbody></table></div>`
    + `<div class="kpi-sub">${_A_COLS.map(c => `<div><b>${_esc(c[0])}</b>: ${_esc(c[1])}</div>`).join('')}</div>`
    + _note(`Measured only (no expiry estimate): ${_num(mo.n)} trades · win rate ${_pct(mo.win_rate)} · P&L ${_pnl(mo.pnl)}`
      + ` · largest win ${_pnl(w.largest_win)} · largest loss ${_pnl(w.largest_loss)} · longest losing streak ${_num(w.max_loss_streak)}`);
}

const _B_COLS = [
  ['Kind', 'Fast burst = many fills in a short time; Position = one position from first fill to flat; Low-cash day = a day with low ledger cash and open losers.'],
  ['When', 'Date (burst, low-cash day) or open to close dates (position).'],
  ['What happened', 'A short description of the moment.'], ['P&L', 'Realised P&L (burst, position) or estimated open loss (low-cash day).'],
  ['Basis', 'measured = from your rows; estimated = uses a mark or an expiry estimate.'],
];

function _momentRows() {
  const rows = [], notes = [];
  const ot = _cache.overtrading, bu = _cache.buildup, mt = _cache.margintrap;
  if (!ot) notes.push('bursts could not be loaded');
  else if (ot.available && (ot.bursts || {}).available) {
    ((ot.bursts || {}).top || []).forEach(r => rows.push({ kind: 'Fast burst', when: `${_esc(r.date)}${r.start ? ` ${_esc(r.start)}` : ''}`,
      what: `${_num(r.fills)} fills in ${_num(r.symbols_count)} symbols`, pnl: r.pnl, basis: 'measured', sub: '' }));
  }
  if (!bu) notes.push('positions could not be loaded');
  else if (bu.available) {
    (bu.chains || []).forEach(c => rows.push({ kind: 'Position', when: `${_dash(c.open_date)} → ${_dash(c.close_date || (c.still_open ? 'open' : null))}`,
      what: `${_esc(c.symbol)} ${_esc(c.side)}, peak ${c.peak_lots != null ? `${_num(c.peak_lots, 1)} lots` : `${_num(c.peak_qty)} units`}, `
        + `${_num(c.adds)} adds (${_num(c.adverse_adds)} at a worse price)`,
      pnl: c.pnl_measured, basis: 'measured', sub: c.pnl_estimated != null ? `expiry est. ${_pnl(c.pnl_estimated)}` : '' }));
  }
  if (!mt) notes.push('low-cash days could not be loaded');
  else if (mt.available) {
    ((mt.trap || {}).days_list || []).forEach(r => rows.push({ kind: 'Low-cash day', when: _esc(r.date),
      what: `cash ${_pnl(r.cash)}, ${_num(r.open_losers_count)} open losers`, pnl: r.known_loss_est, basis: 'estimated', sub: '' }));
  }
  // keep a row unless its P&L is null AND its basis is estimated (a measured zero is always kept)
  return { rows: rows.filter(r => !(r.pnl == null && r.basis === 'estimated')).sort(_byPnl), notes };
}

function _tableB() {
  const { rows, notes } = _momentRows();
  if (!_cache.overtrading && !_cache.buildup && !_cache.margintrap) return '<div class="kpi-sub">— could not be loaded</div>';
  const shown = _detailBAll ? rows : rows.slice(0, 10);
  const body = shown.map(r => `<tr>${[_pill(r.kind), _html(r.when), _html(r.what), `${r.pnl == null ? '—' : _pnlCell(r.pnl)}${r.sub ? `<div class="kpi-sub">${_esc(r.sub)}</div>` : ''}`,
    _badge(r.basis)].map(_td).join('')}</tr>`).join('') || `<tr><td colspan="5" style="color:var(--t3);text-align:center">No notable moments</td></tr>`;
  const more = rows.length > 10
    ? `<button onclick="taAnDetailBToggle()" style="margin:6px 0;padding:3px 10px;border:1px solid var(--border);border-radius:6px;background:var(--surface);cursor:pointer;font-size:11px">${_detailBAll ? 'Show top 10' : `Show all ${_num(rows.length)}`}</button>` : '';
  return `<div style="font-weight:700;font-size:12px">Notable moments by P&amp;L</div>`
    + `<div class="kpi-sub">The biggest bursts, positions and low-cash days, lowest P&amp;L first.</div>`
    + `<div class="kpi-sub" style="font-weight:700">Rows overlap and are not additive: a burst&rsquo;s fills can sit inside a position, and a low-cash day&rsquo;s open losers are positions listed here. Do not add the rows up. No total is shown.</div>`
    + notes.map(_note).join('')
    + `<div class="ta-tbl-wrap"><table style="width:100%;border-collapse:collapse;font-size:12px"><thead><tr>${_B_COLS.map(c => _tip(c[0], c[1])).join('')}</tr></thead><tbody>${body}</tbody></table></div>`
    + more + `<div class="kpi-sub">${_B_COLS.map(c => `<div><b>${_esc(c[0])}</b>: ${_esc(c[1])}</div>`).join('')}</div>`;
}

function _renderBehaviourDetails() {
  setEl('ta-an-detail-a', _tableA(_cache.overtrading));
  setEl('ta-an-detail-b', _tableB());
}

export function taAnDetailBToggle() {
  _detailBAll = !_detailBAll;
  setEl('ta-an-detail-b', _tableB());
}

// ── Legacy "Full data tables (11)": the original tables, rendered lazily from the cache ──

const _tblByExpiry = d => _tbl('By expiry', ['Expiry', 'Fills', 'Closed', 'Win rate', 'P&L'],
  (d.by_expiry || []).map(r => [_esc(r.key), _num(r.fills), _num(r.closed_trades), _pct(r.win_rate), _pnlCell(r.pnl)]));
const _tblByUnderlying = d => _tbl('By underlying', ['Underlying', 'Fills', 'Closed', 'Win rate', 'P&L'],
  (d.by_underlying || []).map(r => [_esc(r.key), _num(r.fills), _num(r.closed_trades), _pct(r.win_rate), _pnlCell(r.pnl)]));
const _tblHolding = h => _tbl(`Holding time${h.median_minutes != null ? ` (same-day median ${_num(h.median_minutes, 1)} min)` : ''}`,
  ['Bucket', 'Closed trades'], (h.buckets || []).map(r => [_esc(r.label), _num(r.count)]));
const _tblBursts = b => b.available
  ? _tbl(`Bursts (${_num(b.count)}) · re-entries within window after a loss: ${_num((b.reentries_after_loss || {}).count)} `
    + `(P&L ${_pnl((b.reentries_after_loss || {}).pnl)})`, ['Date', 'Start', 'Fills', 'Symbols', 'P&L'],
  (b.top || []).map(r => [_esc(r.date), _dash(r.start), _num(r.fills), _num(r.symbols_count), _pnlCell(r.pnl)]), 'No bursts')
  : _note(`Bursts and re-entries: ${_REASONS[b.reason] || 'not available'}`);
const _tblWeekly = d => _tbl('Per week', ['ISO week', 'Fills', 'Active days', 'Closed trades'],
  (d.weekly || []).map(r => [_esc(r.week), _num(r.fills), _num(r.active_days), _num(r.closed_trades)]));
const _tblBySide = w => _tbl('Win / loss by side', ['Side', 'Closed', 'Win rate', 'P&L'],
  (w.by_side || []).map(r => [_esc(r.key), _num(r.n), _pct(r.win_rate), _pnlCell(r.pnl)]));
const _tblChains = d => _tbl('Worst position chains (flat to flat)',
  ['Symbol', 'Expiry', 'Side', 'Opened', 'Closed', 'Peak qty', 'Adds', 'Adverse adds', 'P&L (measured)', 'Status'],
  (d.chains || []).map(r => [_esc(r.symbol), _dash(r.expiry_ym), _esc(r.side), _dash(r.open_date), _dash(r.close_date),
    _num(r.peak_qty), _num(r.adds), _num(r.adverse_adds), _pnlCell(r.pnl_measured),
    r.still_open ? 'open' : (r.pnl_estimated != null ? `expiry est. ${_pnl(r.pnl_estimated)}` : 'closed')]));
const _tblFillClasses = ev => _tbl('Fill classes', ['Open new', 'Scale in', 'Scale out', 'Close', 'Flip'],
  [[_num(ev.open_new), _num(ev.scale_in), _num(ev.scale_out), _num(ev.close), _num(ev.flip)]]);
const _tblStreaks = d => _tbl('Debit streaks', ['From', 'To', 'Days', 'Net outflow', 'Cash at end'],
  (d.debit_streaks || []).map(r => [_esc(r.start), _esc(r.end), _num(r.days), _pnl(r.net_outflow), _pnl(r.cash_at_end)]), 'No streaks');
const _tblTrapDays = t => _tbl('Low-cash days with open losers (proxy; no causal claim)',
  ['Date', 'Cash', 'Open losers', 'Short notional proxy', 'Proxy / cash', 'Known loss (est.)'],
  (t.days_list || []).map(r => [_esc(r.date), _pnl(r.cash), _num(r.open_losers_count), _num(r.short_notional_proxy),
    _num(r.proxy_to_cash_ratio, 2), _pnlCell(r.known_loss_est)]), 'No such days');

function _fullTablesHtml() {
  const ot = _cache.overtrading, bu = _cache.buildup, mt = _cache.margintrap;
  const off = n => `<div class="kpi-sub">${_esc(n)} could not be loaded.</div>`;
  let h = '';
  if (!ot) h += off('Overtrading tables');
  else if (ot.available) {
    h += _tblByExpiry(ot) + _tblByUnderlying(ot) + _tblHolding(ot.holding || {}) + _tblBursts(ot.bursts || {})
      + _tblWeekly(ot) + _tblBySide(ot.winloss || {});
  } else h += _unavail(ot);
  if (!bu) h += off('Build-up tables');
  else if (bu.available) h += _tblChains(bu) + _tblFillClasses(bu.events || {});
  else h += _unavail(bu);
  if (!mt) h += off('Margin trap tables');
  else if (mt.available) {
    if ((mt.ledger || {}).available) h += _tblStreaks(mt) + _tblTrapDays(mt.trap || {});
    h += _stopsTable(mt.stops || {});
  } else h += _unavail(mt);
  return h;
}

function _renderFullTablesIfOpen() {
  if (_fullOpen) setEl('ta-an-fulltables-body', _fullTablesHtml());
}

export function taAnFullToggle(open) {
  _fullOpen = !!open;
  if (_fullOpen) setEl('ta-an-fulltables-body', _fullTablesHtml());
}


function _ruleCard(r) {
  const w = r.what_if;
  const p = r.parameter;
  const status = r.status === 'applicable' ? '' : ' (' + r.status.replace('_', ' ') + ')';  // escaped at use
  const wi = w ? `<div>Had this applied: baseline ${_pnl(w.baseline_pnl)} → ${_pnl(w.whatif_pnl)} `
    + `(<span class="${_cls(w.delta)}">${_pnl(w.delta)}</span>) · ${_num(w.trades_removed)} entries removed · `
    + `${_num(w.units_removed, 0)} units · ${_num(w.closed_trades_affected)} closed trades affected`
    + ` · ${_num(w.open_units_vetoed, 0)} open units vetoed</div>` : '';
  const ill = r.status === 'illustrative' && p
    ? `<div class="kpi-sub">Illustrative bound (estimate): ${_pnl(p.value)}. Not P&L you would have had.</div>` : '';
  const ev = (r.evidence || []).map(e => `<li>${_esc(e.label)}: ${_dash(e.value)} <span style="color:var(--t3)">(${_esc(e.source)})</span></li>`).join('');
  const vs = (r.variants || []).length ? _tbl('Other stop multiples', ['Multiple', 'Trades beyond', 'Saved (est.)'],
    r.variants.map(v => [`${_num(v.multiple, 2)}x`, _num(v.n_exceeded), _pnlCell(v.saved_if_stopped)])) : '';
  return `<div class="kpi" style="margin:10px 0"><div class="kpi-label">${_esc(r.title)}${_esc(status)}</div>`
    + `${p ? `<div class="kpi-sub">Parameter: ${_esc(p.name)} = ${_dash(p.value)} ${_esc(p.unit)}${p.lots != null ? ` (~${_num(p.lots, 1)} lots)` : ''}</div>` : ''}`
    + `<div class="kpi-sub">Basis: ${_esc(r.threshold_basis)}</div>${wi}${ill}`
    + `<ul style="margin:4px 0 4px 18px;padding:0;font-size:12px">${ev}</ul>${vs}`
    + `<div class="kpi-sub">${_list(r.caveats)}</div></div>`;
}

// ── Suggestions: collapsible multi-column card grid ───────────────────────────────────

// Plain-language title and one-line "what this looks at", keyed by the server rule id.  Unknown ids fall back
// to the server title/basis.  A backend test compares these keys with RULE_IDS in fno_trade_suggestions.py.
const _RULE_COPY = {
  max_trades_per_day: ['Daily entry cap', 'Days on which you opened more new entries than your typical busy day, and what those extra entries made or lost.'],
  cooling_off_after_loss: ['Pause after a loss', 'Entries made soon after a losing close, and how they turned out.'],
  no_averaging_down: ['Averaging down', 'Adds made at a worse price than your average entry, and how those slices closed.'],
  stop_discipline: ['Stop at a multiple of premium', 'Closed short trades that lost more than 1x, 1.5x or 2x the premium received (one-sided estimate).'],
  qty_cap_per_expiry: ['Size per expiry', 'Expiries where your open size exceeded your usual maximum.'],
  margin_headroom_floor: ['Cash headroom', 'Entries made when ledger cash was already low.'],
  counter_move_entries: ['Entries against the day\'s move', 'Entries in the direction opposite to that day\'s spot move (needs spot data).'],
  expiry_proximity_entries: ['Entries close to expiry', 'New entries within a few days of expiry.'],
  bias_limit: ['Directional lean', 'Days when your book leaned strongly in one direction (needs spot data).'],
  bias_hedge_illustrative: ['Hedge bound (illustrative)', 'What a simple hedge would have bounded, as an upper estimate (needs spot data).'],
};
const _copy = r => _RULE_COPY[r.id] || [r.title, r.threshold_basis];

const _SG_STATUS = { applicable: 'Applicable', not_triggered: 'Not triggered', illustrative: 'Illustrative', insufficient_data: 'Not enough data' };

function _sgEffect(r, d) {
  const w = r.what_if, p = r.parameter, smp = d.sample || {};
  if (r.status === 'applicable' && w) {
    return `Had this applied: <span class="${_cls(w.delta)}">${_pnl(w.delta)}</span> on closed P&amp;L (${_pnl(w.baseline_pnl)} → ${_pnl(w.whatif_pnl)})`;
  }
  if (r.status === 'illustrative') return `Illustrative bound ${_pnl(p && p.value)} (estimate, not P&amp;L you would have had)`;
  if (r.status === 'not_triggered') return 'Never exceeded in this period';
  if (/too few closed trades/.test(r.threshold_basis || '')) return `Needs more closed trades (have ${_num(smp.closed_trades)}, need ${_num(smp.min_required)})`;
  return _esc(r.threshold_basis || 'Not enough data');
}

function _sgKey(r) {
  const w = r.what_if, p = r.parameter, bits = [];
  if (p) bits.push(`limit ${_dash(p.value)} ${_esc(p.unit)}`);
  if (w) bits.push(`${_num(w.trades_removed)} entries / ${_num(w.closed_trades_affected)} closed trades affected`);
  return bits.join(' · ');
}

function _sgBody(r, d) {
  const [, what] = _copy(r), w = r.what_if, p = r.parameter;
  const mt = _cache.margintrap;
  const mini = w ? `<div class="ta-sg-mini"><div>Baseline closed P&amp;L<br><b>${_pnl(w.baseline_pnl)}</b></div><div>With the rule<br><b>${_pnl(w.whatif_pnl)}</b></div>`
    + `<div>Entries removed<br><b>${_num(w.trades_removed)}</b></div><div>Open units vetoed<br><b>${_num(w.open_units_vetoed, 0)}</b></div></div>` : '';
  const ill = r.status === 'illustrative' && p ? `<div class="kpi-sub">Illustrative bound (estimate): ${_pnl(p.value)}. Not P&amp;L you would have had.</div>` : '';
  const ev = (r.evidence || []).map(e => `<li>${_esc(e.label)}: ${_dash(e.value)} <span style="color:var(--t3)">(${_esc(e.source)})</span></li>`).join('');
  let extra = '';
  if (r.id === 'stop_discipline') {
    extra = mt && mt.available ? _stopsTable(mt.stops || {})
      : (r.variants || []).length
        ? _tbl('Other stop multiples', ['Multiple', 'Trades beyond', 'Saved (est.)'], r.variants.map(v => [`${_num(v.multiple, 2)}x`, _num(v.n_exceeded), _pnlCell(v.saved_if_stopped)]))
        : '';
    if (!mt) extra += _note('Stop what-if table could not be loaded');
  } else if ((r.variants || []).length) {
    extra = _tbl('Other stop multiples', ['Multiple', 'Trades beyond', 'Saved (est.)'], r.variants.map(v => [`${_num(v.multiple, 2)}x`, _num(v.n_exceeded), _pnlCell(v.saved_if_stopped)]));
  }
  const cav = (r.caveats || []).length ? `<div class="kpi-sub">${_list(r.caveats)}</div>` : '';
  return `<div class="ta-sg-body"><div><b>What this rule looks at.</b> ${_esc(what)}</div>`
    + `<div class="kpi-sub">Basis: ${_esc(r.threshold_basis)}${p ? ` · ${_esc(p.name)} = ${_dash(p.value)} ${_esc(p.unit)}${p.lots != null ? ` (~${_num(p.lots, 1)} lots)` : ''}` : ''}</div>`
    + `${mini}${ill}<ul style="margin:4px 0 4px 18px;padding:0">${ev}</ul>${extra}${cav}</div>`;
}

function _sgCard(r, d) {
  const [title] = _copy(r);
  const est = r.status === 'illustrative' ? _badge('estimated') : '';
  const open = _sgOpen.has(r.id) ? ' open' : '';
  return `<details class="ta-sg-card" data-rule="${_ea(r.id)}"${open} ontoggle="taAnSgToggle(this)">`
    + `<summary class="ta-sg-sum"><div class="ta-sg-top"><span>${_esc(title)}</span>`
    + `<span><span class="ta-sg-badge" data-status="${_ea(r.status)}">${_esc(_SG_STATUS[r.status] || r.status)}</span>${est}</span></div>`
    + `<div class="ta-sg-eff">${_sgEffect(r, d)}</div><div class="kpi-sub">${_sgKey(r)}</div></summary>`
    + `${_sgBody(r, d)}</details>`;
}

function _renderSgGrid() {
  const d = _cache.suggestions;
  if (!d || !d.available) { setEl('ta-an-sg-grid', ''); setEl('ta-an-sg-counts', ''); return; }
  const rules = d.rules || [];
  const n = k => rules.filter(r => r.status === k).length;
  setEl('ta-an-sg-counts', _esc(`${n('applicable')} applicable · ${n('not_triggered')} not triggered · ${rules.length - n('applicable') - n('not_triggered')} not enough data or illustrative`));
  setEl('ta-an-sg-grid', rules.map(r => _sgCard(r, d)).join(''));
}

// the user opening/closing one card (inline ontoggle) updates the remembered open-state Set
export function taAnSgToggle(el) {
  const id = el && el.dataset && el.dataset.rule;
  if (!id) return;
  if (el.open) _sgOpen.add(id); else _sgOpen.delete(id);
}
export function taAnSgExpandAll() {
  ((_cache.suggestions || {}).rules || []).forEach(r => _sgOpen.add(r.id));
  _renderSgGrid();
}
export function taAnSgCollapseAll() {
  _sgOpen.clear();
  _renderSgGrid();
}

function _renderSuggestions(d) {
  _cache.suggestions = d;
  const disc = `<div class="kpi-sub" style="font-weight:700;margin-bottom:8px">${_esc(d.disclaimer || _DISCLAIMER)}</div>`;
  ['ta-an-sg-summary', 'ta-an-sg-obs', 'ta-an-sg-counts', 'ta-an-sg-grid'].forEach(id => setEl(id, ''));
  const mt = _cache.margintrap;
  const defs = (blocks) => _defs(d, blocks);
  if (!d.available) { _setHead('suggestions', ''); _setPanel('suggestions', disc + _unavail(d)); return; }
  const scope = _query();
  if (_sgScope !== scope) { _sgOpen.clear(); _sgScope = scope; }   // a new filter scope forgets the opened cards
  const cb = d.combined || {}, cw = cb.what_if || {}, smp = d.sample || {};
  const stop1 = ((mt && mt.stops && mt.stops.rows) || [])[0];
  const items = [
    _ck('Baseline closed P&L', _pnlShort(d.baseline_pnl), _cls(d.baseline_pnl), `${_numShort(smp.closed_trades)} closed trades`,
      { title: `${_pnl(d.baseline_pnl)} over ${_num(smp.closed_trades)} closed trades (minimum ${_num(smp.min_required)}).` }),
    _ck('Combined entry what-if', _pnlShort(cw.delta), _cls(cw.delta), `would give ${_pnlShort(cw.whatif_pnl)}`,
      { title: `Combined entry rules: ${_pnl(cw.delta)} (would give ${_pnl(cw.whatif_pnl)}). Rules: ${(cb.rules_included || []).join(', ') || '—'}.` }),
    _ck('Stop what-if add-on', _pnlShort(cb.stop_addon), '', `combined ${_pnlShort(cb.combined_with_stop)}`,
      { tag: 'est.', title: `Stop rule add-on ${_pnl(cb.stop_addon)}; combined with the entry rules ${_pnl(cb.combined_with_stop)} (estimate).` }),
  ];
  if (stop1) {
    items.push(_ck('Stop what-if saving', _pnlShort(stop1.saved_if_stopped), '', `at ${_num(stop1.multiple, 2)}x premium`,
      { tag: 'est.', title: `${_pnl(stop1.saved_if_stopped)} saved at ${_num(stop1.multiple, 2)}x premium over ${_num(stop1.n_exceeded)} trades (estimate).` }));
  }
  const obs = d.observations || [];
  const nApp = (d.rules || []).filter(r => r.status === 'applicable').length;
  _setHead('suggestions', `${_num(nApp)} of ${_num((d.rules || []).length)} rules applied to your history`
    + `${cw.delta != null ? `; the entry rules combined would have changed closed P&amp;L by ${_pnl(cw.delta)}` : ''}.`);
  _setPanel('suggestions', disc + _quality(d), defs([['Combined.', cb], ['Planned vs actual stops.', (mt && mt.stops) || null]]));
  setEl('ta-an-sg-summary', _kpis(items, 'c4'));
  setEl('ta-an-sg-obs', obs.length ? `<summary style="cursor:pointer;font-weight:700">Observations (${_num(obs.length)})</summary><ul style="margin:4px 0 4px 18px;padding:0">${obs.map(o => `<li>${_esc(o.text)}</li>`).join('')}</ul>` : '');
  _renderSgGrid();
}


function _renderFoundation(d) {
  if (!d.available) { setEl('ta-an-recon', _unavail(d)); return; }
  const r = d.reconciliation || {};
  const t = r.totals || {};
  const head = `<div>Reconciliation: ${_num(t.n_symbols_ok)} of ${_num(t.symbols)} symbols within tolerance; total gap ${_pnl(t.gap_measured)}`
    + ` (expiry estimate explains ${_pnl(t.expiry_estimate_explains)})</div>`;
  const rows = (r.rows || []).map(x => [_esc(x.symbol), _pnl(x.fifo_measured), _pnl(x.fifo_expiry_estimate), _pnl(x.sheet_realised),
    _pnlCell(x.gap_measured), _pnlCell(x.gap_with_estimate), _num(x.fifo_open_qty), _dash(x.sheet_open_qty),
    _num(x.intrinsic_px, 2), _num(x.sheet_implied_px, 2), _esc((x.causes || []).join(', '))]);
  setEl('ta-an-recon', head + `<details><summary style="cursor:pointer">Show per-symbol reconciliation</summary>`
    + _tbl('FIFO vs P&L sheet (gaps are shown, never hidden)',
      ['Symbol', 'FIFO measured', 'FIFO expiry est.', 'Sheet realised', 'Gap', 'Gap after estimate', 'FIFO open', 'Sheet open', 'Intrinsic px', 'Sheet-implied px', 'Causes'], rows)
    + `${_infoBlock('Reconciliation.', r)}</details>`);
}

// ── F42 P4: Spot vs P&L (lazy, collapsed card) ─────────────────────────────────────────

const _GREEN = 'rgba(26,107,60,.6)', _RED = 'rgba(155,28,28,.6)', _BLUE = '#0056B8', _WARN = '#92480A';
const _GREEN_L = 'rgba(26,107,60,.28)', _RED_L = 'rgba(155,28,28,.28)';
const _need = b => `needs at least ${_num(b.min_required)} days (have ${_num(b.n != null ? b.n : b.n_days)})`;

const _verdict = v => _VERDICTS[v] || '—';

function _spotVerdictLine(u) {
  if (!u.available) return `${_esc(u.underlying)}: ${_esc(_REASONS[u.reason] || 'Not available.')}`;
  const al = u.alignment || {}, ad = (u.relationship || {}).all_days || {};
  const scored = (al.with_n || 0) + (al.against_n || 0);
  const alNeed = _need({ min_required: al.min_required, n: scored });
  const lean = al.verdict === 'insufficient_sample'
    ? _verdict('insufficient_sample') + ' (' + alNeed + ')'
    : _verdict(al.verdict) + ' (' + _pct(al.pct_with) + ' of ' + _num(scored) + ' scored days with the market)';
  const corr = ad.reason ? `correlation ${ad.reason === 'insufficient_sample' ? _need(ad) : 'no variation'}`
    : `correlation ${_num(ad.pearson, 2)} (n=${_num(ad.n)})`;
  return `<b>${_esc(u.underlying)}</b>: ${_esc(lean)} · ${_esc(corr)}`;
}

function _bucketRows(list) {
  return (list || []).map(b => b.available
    ? [_esc(b.key), _num(b.n_days), _num(b.n_closing_days), _pnlCell(b.total_pnl),
      `${_pnl(b.total_measured)} / ${_pnl(b.total_estimate)}`, _pnl(b.mean_pnl), _pnl(b.median_pnl), _pct(b.hit_rate_pct), _pct(b.share_of_total_loss_pct)]
    : [_esc(b.key), _num(b.n_days), _num(b.n_closing_days), `<span style="color:var(--t3)">${_esc(_need(b))}</span>`, '—', '—', '—', '—', '—']);
}
const _BUCKET_COLS = ['Bucket', 'Days', 'Closing days', 'P&L', 'Measured / estimate', 'Mean', 'Median', 'Hit rate', 'Share of total loss'];

function _corrRow(label, c) {
  return c.reason
    ? [_esc(label), _num(c.n), `<span style="color:var(--t3)">${_esc(c.reason === 'insufficient_sample' ? _need(c) : 'no variation')}</span>`, '—', '—', '—', '—']
    : [_esc(label), _num(c.n), _num(c.pearson, 3), _num(c.spearman, 3), _num(c.beta_inr_per_pct, 0), _num(c.r2, 3),
      `${c.significant ? 'yes' : 'no'}${_badge(c.basis_tag === 'mixed' ? 'estimated' : 'measured')}`];
}

function _spotRelationHtml(u) {
  if (!u.available) return _unavail({ reason: u.reason });
  const rel = u.relationship || {}, al = u.alignment || {}, tt = u.totals || {}, sn = u.unrealised_snapshot || {};
  const bb = al.by_bias || {};
  const corr = _tbl('Correlation and beta (daily realised P&L vs spot return)',
    ['Basis', 'Days', 'Pearson', 'Spearman', 'Beta (INR per +1%)', 'R squared', 'Beyond no-correlation band'],
    [_corrRow('All days', rel.all_days || {}), _corrRow('Closing days', rel.closing_days || {})]);
  const dir = _tbl('Up, down and flat days', _BUCKET_COLS, _bucketRows(rel.by_direction));
  const big = _tbl('Big-move days (reversal days can also be big-up or big-down)', _BUCKET_COLS,
    _bucketRows([...(rel.big_move || []), ...(rel.big_any ? [rel.big_any] : [])]));
  const exp = _tbl('Expiry days', _BUCKET_COLS, _bucketRows(rel.expiry_days));
  const align = _tbl('Positioning vs spot (start-of-day book)', ['Measure', 'Value'], [
    ['Days with the market / against / flat market / flat book', `${_num(al.with_n)} / ${_num(al.against_n)} / ${_num(al.flat_market_n)} / ${_num(al.flat_book_n)}`],
    ['Share with the market (95% interval)', `${_pct(al.pct_with)} (${_pct(al.pct_with_ci_low)} to ${_pct(al.pct_with_ci_high)})`],
    ['Units x points: with / against / net', `${_pnl(al.with_units_pts)} / ${_pnl(al.against_units_pts)} / ${_pnl(al.net_units_pts)}${_badge('estimated')}`],
    ['Mean same-day return when book bullish / bearish', `${_pct((bb.bullish || {}).mean_ret_pct)} (n=${_num((bb.bullish || {}).n)}) / ${_pct((bb.bearish || {}).mean_ret_pct)} (n=${_num((bb.bearish || {}).n)})`],
  ]) + _note(al.caveat || '');
  const snap = sn.available
    ? `Unrealised (sheet snapshot, as of ${_esc(sn.as_of || '—')}): ${_pnl(sn.amount)} over ${_num(sn.n_symbols)} symbols`
      + `${sn.stale ? ' (older than the latest spot day)' : ''}${_badge('measured')}`
    : `Unrealised snapshot: ${_esc(_REASONS[sn.reason] || 'not available')}`;
  const tot = _note(`Realised measured ${_pnl(tt.measured_realised)} · expiry estimate ${_pnl(tt.estimated_realised)} · rolled forward `
    + `${_pnl(tt.pnl_rolled_amount)} (${_num(tt.pnl_rolled_days)} days) · after last spot day ${_pnl(tt.pnl_after_last_spot)} (${_num(tt.pnl_after_last_spot_count)} closes)`
    + ` · realised plus unrealised (periods may differ) ${_pnl(tt.realised_plus_unrealised)}`);
  return corr + dir + big + exp + align + `<div class="kpi-sub" style="margin:6px 0">${snap}</div>` + tot;
}

function _spotObsHtml(d) {
  const rows = [];
  (d.underlyings || []).forEach(u => (u.observations || []).forEach(o => rows.push(`<li>${_esc(o.text)}</li>`)));
  return rows.length ? `<ul style="margin:4px 0 4px 18px;padding:0">${rows.join('')}</ul>`
    : '<div class="kpi-sub">No observations: nothing passed its minimum-sample gate.</div>';
}

function _spotRulesHtml(d) {
  const im = d.improvement || {};
  const rel = (im.related || []).map(r => `<li>${_esc(r.observation_id)} relates to ${_esc(r.rule_id)}</li>`).join('');
  return `<div class="kpi-sub" style="font-weight:700;margin:6px 0">${_esc(im.disclaimer || _DISCLAIMER)}</div>`
    + (im.rules || []).map(_ruleCard).join('')
    + (rel ? `<div class="kpi-sub">Related observations and rules:<ul style="margin:4px 0 4px 18px;padding:0">${rel}</ul></div>` : '');
}

function _spotChart(slot, u) {
  const id = `ta-cv-spot-${slot}`;
  _chart(id, null);
  const s = u.series || {};
  if (!u.available || !(s.dates || []).length) return;
  const n = s.dates.length;
  const idx = [...Array(n).keys()];
  const style = idx.map(i => s.expiry_flag[i] ? 'rect' : (s.big_move_flag[i] ? 'triangle' : 'circle'));
  const rad = idx.map(i => s.reversal_flag[i] ? 6 : (s.big_move_flag[i] || s.expiry_flag[i] ? 4 : 1));
  const bord = idx.map(i => (s.big_move_flag[i] && s.adverse_flag[i]) ? '#9B1C1C' : _BLUE);
  const sn = u.unrealised_snapshot || {};
  const hasEst = (s.realised_estimate || []).some(v => v);
  const datasets = [
    { type: 'line', label: u.underlying + ' close', data: s.spot_close, borderColor: _BLUE, borderWidth: 1.5, pointStyle: style,
      pointRadius: rad, pointBackgroundColor: _BLUE, pointBorderColor: bord, yAxisID: 'y', order: 1 },
    { type: 'bar', label: 'Realised P&L (measured)', data: s.realised_measured, stack: 'pnl', yAxisID: 'y1', order: 3,
      backgroundColor: s.realised_measured.map(v => (v || 0) >= 0 ? _GREEN : _RED) },
  ];
  if (hasEst) {
    datasets.push({ type: 'bar', label: 'Expiry estimate', data: s.realised_estimate, stack: 'pnl', yAxisID: 'y1', order: 4,
      backgroundColor: s.realised_estimate.map(v => (v || 0) >= 0 ? _GREEN_L : _RED_L) });
  }
  datasets.push({ type: 'line', label: 'Cumulative P&L', data: s.cum_total, borderColor: _WARN, borderWidth: 1, pointRadius: 0, yAxisID: 'y2', order: 2 });
  if (sn.available && sn.amount != null) {
    const pt = s.dates.map((_, i) => i === n - 1 ? sn.amount : null);
    datasets.push({ type: 'line', label: 'Unrealised (sheet, as of ' + (sn.as_of || '—') + ')', data: pt, borderColor: _WARN,
      backgroundColor: _WARN, pointStyle: 'rectRot', pointRadius: 6, showLine: false, yAxisID: 'y2', order: 0 });
  }
  const tick = { font: { family: 'IBM Plex Mono, monospace', size: 10 } };
  _chart(id, {
    data: { labels: s.dates, datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { labels: { boxWidth: 10, font: { size: 10 } } }, tooltip: { callbacks: { afterBody: items => {
        const i = items && items.length ? items[0].dataIndex : -1;
        if (i < 0 || i >= n) return [];
        const out = [`Close ${_num(s.spot_close[i], 2)} · return ${_pct(s.ret_pct[i])} · bias ${_num(s.bias_in[i])}`,
          `Realised ${_pnl(s.realised_measured[i])} · estimate ${_pnl(s.realised_estimate[i])} · cumulative ${_pnl(s.cum_total[i])}`];
        if (sn.available && i === n - 1) out.push('Unrealised as of ' + (sn.as_of || '—') + (sn.stale ? ' (stale)' : '') + ': ' + _pnl(sn.amount));
        return out;
      } } } },
      scales: { x: { ..._axis, ticks: { ...tick, maxTicksLimit: 8 } }, y: { ..._axis, position: 'left' },
        y1: { ..._axis, position: 'right', stacked: true, grid: { drawOnChartArea: false } }, y2: { display: false, grid: { display: false } } },
    },
  });
}

function _renderSpotPnl(d) {
  const unds = d.underlyings || [];
  [0, 1].forEach(i => { _chart(`ta-cv-spot-${i}`, null); setEl(`ta-an-spotpnl-rel-${i}`, ''); });
  const grid = document.getElementById('ta-an-spotpnl-grid');
  if (!d.available || !unds.length) {
    [0, 1].forEach(i => { const el = document.getElementById(`ta-an-spotpnl-slot-${i}`); if (el) el.style.display = 'none'; });
    setEl('ta-an-spotpnl-body', _unavail(d));
    setEl('ta-an-spotpnl-obs', ''); setEl('ta-an-spotpnl-rules', ''); setEl('ta-an-spotpnl-def', '');
    return;
  }
  const lines = unds.map(u => `<div style="margin:4px 0">${_spotVerdictLine(u)}</div>`).join('');
  const trunc = unds.some(u => (u.series || {}).truncated) ? _note('Older days not drawn (the statistics use the full window).') : '';
  const stale = unds.some(u => u.spot_stale) ? _note('Spot history looks stale: the last close is more than a few days old.') : '';
  setEl('ta-an-spotpnl-body', (d.reason ? _unavail(d) : '') + lines + trunc + stale + _note(d.delta1_note || '')
    + _note('In this sample. Observed, not a prediction.'));
  [0, 1].forEach(i => {
    const u = unds[i];
    const el = document.getElementById(`ta-an-spotpnl-slot-${i}`);
    if (el) el.style.display = u ? '' : 'none';
    if (!u) return;
    setEl(`ta-an-spotpnl-title-${i}`, `${_esc(u.underlying)}${_badge('measured')}${_badge('estimated')}`);
    _spotChart(i, u);
    setEl(`ta-an-spotpnl-rel-${i}`, _spotRelationHtml(u));
  });
  if (grid) grid.style.display = 'grid';
  setEl('ta-an-spotpnl-obs', _spotObsHtml(d));
  setEl('ta-an-spotpnl-rules', _spotRulesHtml(d));
  setEl('ta-an-spotpnl-def', _defs(d, [['Spot vs P&L.', d.info]]));
}

async function loadSpotPnl() {
  const seq = ++_spotSeq;
  const qs = _query();
  setEl('ta-an-spotpnl-body', '<div class="kpi-sub">Loading…</div>');
  try {
    const d = await api(`${_BASE}spot-vs-pnl?${qs}`);
    if (seq !== _spotSeq) return;
    if (!d) throw new Error('no data');
    _renderSpotPnl(d);
    _spotKey = qs;
    _spotLoaded = true;
    _spotStale = false;
  } catch (e) {
    if (seq !== _spotSeq) return;
    _spotLoaded = false;
    [0, 1].forEach(i => _chart(`ta-cv-spot-${i}`, null));
    setEl('ta-an-spotpnl-body', '<div class="kpi-sub">— could not be loaded</div>');
  }
}

// Fetch only when the card is open AND (never loaded, or the filter key changed, or a refresh was asked for).
function _spotSync() {
  if (_spotKey !== _query()) _spotStale = true;
  if (_spotOpen && (!_spotLoaded || _spotStale)) loadSpotPnl();
}

export function taAnSpotToggle(open) {
  _spotOpen = !!open;
  if (_spotOpen) _spotSync();
}

const _RENDER = {
  foundation: _renderFoundation, overtrading: _renderOvertrading, buildup: _renderBuildup,
  marketturn: _renderMarketTurn, margintrap: _renderMarginTrap, suggestions: _renderSuggestions,
};


function _query() {
  const f = taGetFilters();
  const qs = new URLSearchParams({ underlying: f.underlying || 'ALL' });
  if (f.month) qs.set('expiry_month', f.month);
  if (_from) qs.set('date_from', _from);
  if (_estimate !== null) qs.set('include_expiry_estimate', String(_estimate));
  return qs.toString();
}

// Loads all six endpoints in parallel; each panel renders (or fails) on its own.
// F42 P6 lifecycle: (1) reset _cache, (2) allSettled, (3) _seq guard, (4) fill _cache from the settled results,
// (5) only then run the per-panel renderers (so any renderer may read any cache key), then the joined views.
export async function loadAnalyticsPanels() {
  _spotSync();   // F42 P4: closed card only marks itself stale; an open one reloads
  const seq = ++_seq;
  Object.keys(_cache).forEach(k => { _cache[k] = null; });
  const qs = _query();
  const keys = Object.keys(_ENDPOINTS);
  const results = await Promise.allSettled(keys.map(k => api(`${_BASE}${_ENDPOINTS[k]}?${qs}`)));
  if (seq !== _seq) return;  // a newer load superseded this one
  keys.forEach((key, i) => {
    if (key in _cache) _cache[key] = results[i].status === 'fulfilled' && results[i].value ? results[i].value : null;
  });
  let ok = 0;
  results.forEach((res, i) => {
    const key = keys[i];
    try {
      if (res.status !== 'fulfilled' || !res.value) throw new Error('no data');
      const data = res.value;
      _RENDER[key](data);
      ok += 1;
      const est = document.getElementById('ta-an-expiry-est');
      if (est && _estimate === null && data.filter) est.checked = !!data.filter.include_expiry_estimate;
      const from = document.getElementById('ta-an-from');
      if (from && !_from && data.filter && data.filter.date_from) from.value = data.filter.date_from;
    } catch (e) {
      if (key === 'foundation') setEl('ta-an-recon', '— could not be loaded');
      else _fail(key);
    }
  });
  _renderBehaviourDetails();
  _renderFullTablesIfOpen();
  setEl('ta-an-status', ok === keys.length ? '' : `${_num(keys.length - ok)} of ${_num(keys.length)} analytics panels could not be loaded`);
}


export function taAnRefresh() {
  _spotStale = true;   // an explicit refresh re-fetches the Spot vs P&L card when it is open
  return loadAnalyticsPanels();
}

export function taAnFromChanged(v) {
  _from = v || '';
  return loadAnalyticsPanels();
}

export function taAnToggleEstimate(flag) {
  _estimate = !!flag;
  return loadAnalyticsPanels();
}

export function taAnToggleInfo(panelId) {
  if (!_INFO_IDS.includes(panelId)) return;
  const el = document.getElementById(`ta-an-${panelId}-def`);
  if (el) el.style.display = el.style.display === 'none' ? '' : 'none';
}

