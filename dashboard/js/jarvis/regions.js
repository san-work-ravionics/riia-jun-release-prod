// Jarvis — F44 P4c: Europe / India / US side by side, as RITA Portfolio Builder (_regionDisplay
// grouping, region avg, ranked instruments, risk-vs-return map, sortable table). Read-only.
// Data: geography-overview (G, all instruments, returns in %) + each location's own A5 payload.
// D1: nothing is summed or converted across locations — returns and risk are unitless; a price is
// shown with its own instrument currency. No shared/fx.js.
import { api } from '../shared/api.js';
import { mkChart, destroyChart, C } from '../shared/charts.js';
import { REGION_CCY, instrumentCurrency } from '../shared/portfolio-currency.js';
import { esc } from './esc.js?v=3';
import { t } from './copy.js?v=3';
import { fmtMoney, fmtNum, fmtPctPoint, isNum, locationName } from './format.js?v=3';
import { locPortfolioHtml } from './portfolio.js?v=3';

export const LOCS = ['europe', 'india', 'us'];
export const LOC_REGION = { europe: 'EU', india: 'India', us: 'US' };
const _LOC_COLOR = { europe: C.run, india: C.warn, us: C.mon, other: C.t4 };

export function loadGeography() {
  return api('/api/v1/experience/rita/geography-overview');            // G
}

// EUR conversion rates: fetches INR and USD rates from the FX endpoint.
// Returns { INR: float|null, USD: float|null } — null when the rate is unavailable.
export function loadEurRates() {
  return Promise.allSettled([
    api('/api/v1/experience/rita/fx?base=EUR&quote=INR'),
    api('/api/v1/experience/rita/fx?base=EUR&quote=USD'),
  ]).then(([inr, usd]) => ({
    INR: inr.status === 'fulfilled' ? inr.value.rate : null,
    USD: usd.status === 'fulfilled' ? usd.value.rate : null,
  }));
}

function _toEur(value, ccy, rates) {
  if (!isNum(value)) return null;
  if (!ccy || ccy === 'EUR') return value;
  const r = rates && rates[ccy];
  return isNum(r) ? value / r : null;
}

// geography region (EU / India / US / Other) → location key, or null for Other / unknown.
export function locationOfRegion(region) {
  return LOCS.find(l => LOC_REGION[l] === region) || null;
}

function _annotate(inst, region) {
  const loc = locationOfRegion(region);
  return { ...inst, region, loc, ccy: instrumentCurrency(inst, region) };
}

// Every instrument, annotated with region / loc / ccy (Other kept: map + table only).
export function allInstruments(geo) {
  return ((geo && geo.regions) || []).flatMap(g => (g.instruments || []).map(i => _annotate(i, g.region)));
}

// { europe: [...], india: [...], us: [...] } — Other is not a column.
export function groupByLocation(geo) {
  const out = { europe: [], india: [], us: [] };
  for (const i of allInstruments(geo)) if (i.loc) out[i.loc].push(i);
  return out;
}

const _ret = i => (isNum(i.return_1y_pct) ? i.return_1y_pct : isNum(i.daily_return_pct) ? i.daily_return_pct : null);
const _isEst = i => !isNum(i.return_1y_pct) && isNum(i.daily_return_pct);

// D7: average 1Y return of the instruments that have one; none → daily average, marked (est.).
export function regionAvg(insts) {
  const avg = xs => (xs.length ? xs.reduce((s, v) => s + v, 0) / xs.length : null);
  const y1 = (insts || []).map(i => i.return_1y_pct).filter(isNum);
  if (y1.length) return { value: avg(y1), est: false };
  const d = (insts || []).map(i => i.daily_return_pct).filter(isNum);
  return { value: avg(d), est: d.length > 0 };
}

// Best 1Y return first (daily "(est.)" fallback, as RITA); no return at all → last.
export function rankInstruments(insts) {
  return (insts || []).slice().sort((a, b) => {
    const ra = _ret(a), rb = _ret(b);
    if (ra === null && rb === null) return String(a.id).localeCompare(String(b.id));
    if (ra === null) return 1;
    if (rb === null) return -1;
    return rb - ra;
  });
}

// ── "yours": Held / Picked from the location's own A5 rows (instrument id case-insensitive) ──
function _upper(v) { return String(v ?? '').toUpperCase(); }

function _a5Row(id, pf) {
  return ((pf && pf.instruments) || []).find(r => _upper(r.instrument_id) === _upper(id)) || null;
}

function _inKey(row) {
  if (!row) return null;
  if (row.held && row.selected) return 'both';
  if (row.held) return 'held';
  if (row.selected) return 'selected';
  return null;
}

export function yoursText(id, pfs, loc = null) {
  const locs = loc ? [loc] : LOCS;
  for (const l of locs) {
    const k = _inKey(_a5Row(id, pfs && pfs[l]));
    if (k) return t(`grid.in.${k}`);
  }
  return '—';
}

function _isHeld(inst, pfs) {
  const row = inst.loc ? _a5Row(inst.id, pfs && pfs[inst.loc]) : null;
  return !!(row && row.held);
}

function _sign(v) { return isNum(v) ? (v > 0 ? 'pos' : v < 0 ? 'neg' : '') : ''; }

export function retLabel(inst) {
  const v = _ret(inst);
  if (v === null) return '—';
  return _isEst(inst) ? `${fmtPctPoint(v)} ${t('loc.est')}` : fmtPctPoint(v);
}

function _miniBar(v) {
  const w = Math.min(Math.abs(isNum(v) ? v : 0), 40);
  return `<span class="jv-minibar ${_sign(v)}" style="width:${w.toFixed(0)}px"></span>`;
}

export function locHeaderMeta(insts) {
  return t('loc.meta', { n: (insts || []).length });
}

export function locAvgHtml(insts) {
  const a = regionAvg(insts);
  const label = a.est ? t('loc.avg.day') : t('loc.avg');
  return `<span class="jv-muted">${esc(label)}</span> <b class="${_sign(a.value)}">${esc(isNum(a.value) ? fmtPctPoint(a.value) : '—')}</b>`;
}

// One column's ranked instrument list as compact geo-kpi tiles (auto-fit grid).
// Each tile keeps class jv-loc-row for test assertions and held/selected highlighting.
export function locInstrumentsHtml(insts, pf, loc) {
  const rows = rankInstruments(insts);
  if (!rows.length) return `<p class="jv-muted">${esc(t('loc.inst.empty', { location: locationName(loc) }))}</p>`;
  const tiles = rows.map(i => {
    const k = _inKey(_a5Row(i.id, pf));
    const v = _ret(i);
    const sig = i.signal ? (i.signal.charAt(0).toUpperCase() + i.signal.slice(1)) : (i.sector || '');
    const badge = k ? `<span class="jv-badge jv-badge-${k}" style="display:block;margin-top:3px">${esc(t(`grid.in.${k}`))}</span>` : '';
    return `<div class="kpi jv-loc-row${k ? ' is-mine' : ''}" style="padding:5px 6px;box-shadow:none">
      <div class="kpi-label" style="font-size:10px;font-weight:600;min-height:2.2em;line-height:1.3">${esc(i.id)}</div>
      <div class="kpi-value ${_sign(v)}" style="font-size:13px">${esc(retLabel(i))}</div>
      ${sig ? `<div class="kpi-delta" style="font-size:10px">${esc(sig)}</div>` : ''}${badge}</div>`;
  }).join('');
  return `<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(72px,1fr));gap:5px;padding:2px 0">${tiles}</div>`;
}

// ── sortable table ─────────────────────────────────────────────────────────────
export const GEO_COLS = ['id', 'loc', 'ccy', 'close', 'ret', 'risk', 'signal', 'yours'];
const _SORTABLE = new Set(['id', 'loc', 'ccy', 'close', 'ret', 'risk', 'signal']);
const _KEY = {
  id: i => i.id ?? null,
  loc: i => locationName(i.loc || 'Other'),
  ccy: i => i.ccy ?? null,
  close: i => (isNum(i.close) ? i.close : null),
  ret: _ret,
  risk: i => (isNum(i.risk_score) ? i.risk_score : null),
  signal: i => i.signal ?? null,
};

// Nulls sort last in both directions.
export function sortGeo(rows, col, asc) {
  const key = _KEY[col] || _KEY.ret;
  return (rows || []).slice().sort((a, b) => {
    const va = key(a), vb = key(b);
    if (va === null && vb === null) return 0;
    if (va === null) return 1;
    if (vb === null) return -1;
    const cmp = typeof va === 'number' && typeof vb === 'number' ? va - vb : String(va).localeCompare(String(vb));
    return asc ? cmp : -cmp;
  });
}

function _riskDots(v) {
  if (!isNum(v)) return '—';
  const n = Math.max(0, Math.min(5, Math.round(v)));
  return `<span class="jv-risk" title="${esc(`${n}/5`)}">${'<i class="on"></i>'.repeat(n)}${'<i></i>'.repeat(5 - n)}</span>`;
}

function _signalText(s) {
  return t(`geo.signal.${s}`) || (s ? String(s) : '—');
}

export function geoTableHtml(rows, sort = { col: 'ret', asc: false }, pfs = {}) {
  const th = col => {
    const num = ['close', 'ret'].includes(col) ? ' class="num"' : '';
    const label = esc(t(`geo.col.${col}`));
    if (!_SORTABLE.has(col)) return `<th${num}>${label}</th>`;
    const arrow = sort.col === col ? (sort.asc ? ' ▲' : ' ▼') : '';
    return `<th${num}><button type="button" class="jv-sort" data-sort="${col}">${label}${arrow}</button></th>`;
  };
  const body = sortGeo(rows, sort.col, sort.asc).map(i => {
    const v = _ret(i);
    return `<tr><td class="mono">${esc(i.id)}</td><td>${esc(locationName(i.loc || 'Other'))}</td>
      <td class="mono">${esc(i.ccy || '—')}</td><td class="num">${esc(fmtNum(i.close))}</td>
      <td class="num ${_sign(v)}">${esc(retLabel(i))}</td><td>${_riskDots(i.risk_score)}</td>
      <td>${esc(_signalText(i.signal))}</td><td>${esc(i.loc ? yoursText(i.id, pfs, i.loc) : '—')}</td></tr>`;
  }).join('');
  return `<thead><tr>${GEO_COLS.map(th).join('')}</tr></thead><tbody>${body}</tbody>`;
}

// Delegated: one listener on the table; the header button's data-sort is read from the dataset.
export function initGeoTable(onSort) {
  document.getElementById('jv-geo-table')?.addEventListener('click', e => {
    const b = e.target.closest('thead button[data-sort]');
    if (b && _SORTABLE.has(b.dataset.sort)) onSort(b.dataset.sort);
  });
}

// ── total panel (all-regions aggregate in EUR) ─────────────────────────────────
export function renderTotalPanel(pfs, rates) {
  const kpisEl = document.getElementById('jv-loc-total-kpis');
  const noteEl = document.getElementById('jv-loc-total-note');
  if (!kpisEl) return;
  let totalVal = null, totalPnl = null;
  for (const loc of LOCS) {
    const pf = pfs[loc];
    const m = pf && pf.perf && pf.perf.money;
    if (!m) continue;
    const ccy = locCurrency(loc, pf);
    const v = _toEur(m.value_now, ccy, rates);
    const p = _toEur(m.pnl, ccy, rates);
    if (v !== null) totalVal = (totalVal ?? 0) + v;
    if (p !== null) totalPnl = (totalPnl ?? 0) + p;
  }
  const hasRates = rates && (rates.INR !== null || rates.USD !== null);
  if (noteEl) { noteEl.textContent = hasRates ? t('loc.total.note') : ''; noteEl.hidden = !hasRates; }
  const _s = v => (v !== null && v > 0 ? 'pos' : v !== null && v < 0 ? 'neg' : '');
  kpisEl.innerHTML = totalVal !== null
    ? `<div class="jv-loc-kpis">
        <div class="kpi kpi-sm"><div class="kpi-label">${esc(t('pf.kpi.value'))}</div><div class="kpi-value">${esc(fmtMoney(totalVal, 'EUR'))}</div></div>
        ${totalPnl !== null ? `<div class="kpi kpi-sm"><div class="kpi-label">${esc(t('pf.kpi.pnl'))}</div><div class="kpi-value ${_s(totalPnl)}">${esc(fmtMoney(totalPnl, 'EUR'))}</div></div>` : ''}
      </div>`
    : `<p class="jv-muted" style="font-size:11px">${esc(t('loc.total.empty'))}</p>`;
}

// ── geography & portfolio performance charts (rendered side by side) ──────────
// Left: line chart — market avg 1Y vs portfolio YTD per region.
// Right: horizontal bar chart — top instrument returns, coloured by location.
// renderUniverse manages the shared wrapper visibility.

function _drawPerfChart(geo, pfs) {
  const canvas = document.getElementById('jv-perf-chart');
  if (!canvas) return false;
  const byLoc = geo ? groupByLocation(geo) : {};
  const labels = LOCS.map(l => locationName(l));
  const marketData = LOCS.map(l => { const a = regionAvg(byLoc[l] || []); return isNum(a.value) ? a.value : null; });
  const pfData = LOCS.map(l => { const pf = pfs[l]; return pf && pf.perf && isNum(pf.perf.ytd_return) ? pf.perf.ytd_return : null; });
  if (!marketData.some(v => v !== null) && !pfData.some(v => v !== null)) { destroyChart('jv-perf-chart'); return false; }
  const mono = { family: C.mono, size: 10 };
  mkChart('jv-perf-chart', {
    type: 'line',
    data: {
      labels,
      datasets: [
        { label: t('perf.chart.market'), data: marketData, borderColor: C.warn, backgroundColor: `${C.warn}18`, fill: false, pointRadius: 5, pointHoverRadius: 7, borderWidth: 2, tension: 0.25, spanGaps: true },
        { label: t('perf.chart.portfolio'), data: pfData, borderColor: C.run, backgroundColor: `${C.run}18`, fill: false, pointRadius: 5, pointHoverRadius: 7, borderWidth: 2, tension: 0.25, spanGaps: true },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { position: 'top', labels: { usePointStyle: true, boxWidth: 8, font: { size: 11 } } },
        tooltip: { callbacks: { label: ctx => `${ctx.dataset.label}: ${ctx.raw !== null ? fmtPctPoint(ctx.raw) : '—'}` } },
      },
      scales: {
        x: { grid: { display: false }, ticks: { font: mono } },
        y: { grid: { color: 'rgba(0,0,0,.05)' }, ticks: { font: mono, callback: v => `${v}%` } },
      },
    },
  });
  return true;
}

function _drawInstChart(geo, filter) {
  const canvas = document.getElementById('jv-geo-inst-chart');
  if (!canvas) return false;
  const all = (geo ? allInstruments(geo) : []).filter(i => isNum(_ret(i)));
  const src = filter ? all.filter(i => i.loc === filter) : all;
  const top = rankInstruments(src).slice(0, 12);
  if (!top.length) { destroyChart('jv-geo-inst-chart'); return false; }
  const labels = top.map(i => i.id);
  const data = top.map(i => _ret(i));
  const colors = top.map(i => _LOC_COLOR[i.loc || 'other']);
  const mono = { family: C.mono, size: 10 };
  mkChart('jv-geo-inst-chart', {
    type: 'bar',
    data: { labels, datasets: [{ data, backgroundColor: colors.map(c => `${c}B0`), borderColor: colors, borderWidth: 1, borderRadius: 2 }] },
    options: {
      responsive: true, maintainAspectRatio: false,
      indexAxis: 'y',
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: ctx => `${ctx.label}: ${fmtPctPoint(ctx.raw)}` } },
      },
      scales: {
        x: { grid: { color: 'rgba(0,0,0,.05)' }, ticks: { font: mono, callback: v => `${v}%` } },
        y: { grid: { display: false }, ticks: { font: { family: C.mono, size: 9 }, autoSkip: false } },
      },
    },
  });
  return true;
}

// Kept exported for backward compatibility; callers should prefer renderUniverse.
export function drawPerfChart(geo, pfs = {}) {
  const wrap = document.getElementById('jv-perf-chart-wrap');
  const has = _drawPerfChart(geo, pfs) || _drawInstChart(geo, null);
  if (wrap) wrap.hidden = !has;
}

// ── risk vs return map ─────────────────────────────────────────────────────────
// Pure: one scatter dataset per location (colour), held → larger dot + ring; instruments
// without a 1Y return or a risk score are not plotted (counted in `skipped`).
// Optional filter: when set to a loc key, only that location's instruments are shown.
export function geoMapData(geo, pfs = {}, filter = null) {
  const groups = { europe: [], india: [], us: [], other: [] };
  let skipped = 0;
  for (const i of allInstruments(geo)) {
    if (filter && i.loc !== filter) continue;
    if (!isNum(i.return_1y_pct) || !isNum(i.risk_score)) { skipped += 1; continue; }
    groups[i.loc || 'other'].push({ x: i.return_1y_pct, y: i.risk_score, id: i.id, held: _isHeld(i, pfs) });
  }
  const datasets = Object.entries(groups).filter(([, pts]) => pts.length).map(([k, pts]) => {
    const col = _LOC_COLOR[k];
    return {
      label: k === 'other' ? t('loc.other') : locationName(k),
      data: pts,
      backgroundColor: pts.map(p => (p.held ? col : `${col}8C`)),
      borderColor: pts.map(p => (p.held ? C.t3 : col)),
      borderWidth: pts.map(p => (p.held ? 2.5 : 0)),
      pointRadius: pts.map(p => (p.held ? 8 : 5)),
      pointHoverRadius: 9,
    };
  });
  return { datasets, skipped, plotted: datasets.reduce((s, d) => s + d.data.length, 0) };
}

export function drawGeoMap(geo, pfs = {}, filter = null) {
  const { datasets, skipped, plotted } = geoMapData(geo, pfs, filter);
  const wrap = document.getElementById('jv-geo-map')?.closest('.chart-wrap');
  const empty = document.getElementById('jv-geo-map-empty');
  const note = document.getElementById('jv-geo-map-note');
  if (note) { note.textContent = skipped && plotted ? t('geo.map.skipped', { n: skipped }) : ''; note.hidden = !(skipped && plotted); }
  if (!plotted) {
    destroyChart('jv-geo-map');
    if (wrap) wrap.hidden = true;
    if (empty) { empty.textContent = t('geo.map.empty'); empty.hidden = false; }
    return { plotted, skipped };
  }
  if (wrap) wrap.hidden = false;
  if (empty) empty.hidden = true;
  const mono = { family: C.mono, size: 10 };
  mkChart('jv-geo-map', {
    type: 'scatter',
    data: { datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { position: 'top', labels: { usePointStyle: true, boxWidth: 8, font: { size: 11 } } },
        tooltip: { callbacks: { label: ctx => t('geo.map.tip', {
          id: ctx.raw.id, location: ctx.dataset.label, ret: fmtPctPoint(ctx.raw.x), risk: ctx.raw.y }) } },
      },
      scales: {
        x: { title: { display: true, text: t('geo.map.x'), font: mono }, grid: { color: 'rgba(0,0,0,.05)' },
             ticks: { font: mono, callback: v => `${v}%` } },
        y: { title: { display: true, text: t('geo.map.y'), font: mono }, min: 0, max: 6, grid: { color: 'rgba(0,0,0,.05)' },
             ticks: { stepSize: 1, font: mono, callback: v => (v > 0 && v < 6 ? v : '') } },
      },
    },
  });
  return { plotted, skipped };
}

// Column header currency: the location's own currency (A5 when loaded, else the region's).
export function locCurrency(loc, pf) {
  return (pf && pf.currency) || REGION_CCY[LOC_REGION[loc]] || '';
}

// ── DOM (main.js orchestrates; the renders live here) ─────────────────────────
function _html(id, html) { const el = document.getElementById(id); if (el) { el.innerHTML = html; el.hidden = false; } }
function _text(id, text) { const el = document.getElementById(id); if (el) { el.textContent = text; el.hidden = !text; } }

// One column from cached data: currency, instrument list (G) and the portfolio block (its own A5).
// A failed G or A5 only replaces its own part with err.load.
export function renderColumn(loc, { geo = null, geoErr = null, pf = null, pfErr = null } = {}) {
  _text(`jv-loc-ccy-${loc}`, locCurrency(loc, pf));
  const insts = geo ? groupByLocation(geo)[loc] : null;
  if (insts) {
    _text(`jv-loc-meta-${loc}`, locHeaderMeta(insts));
    _html(`jv-loc-avg-${loc}`, locAvgHtml(insts));
    _html(`jv-loc-inst-${loc}`, locInstrumentsHtml(insts, pf, loc));
  } else if (geoErr) {
    _text(`jv-loc-meta-${loc}`, '');
    _text(`jv-loc-avg-${loc}`, '');
    _text(`jv-loc-inst-${loc}`, t('err.load', { message: geoErr }));
  }
  if (pfErr) _text(`jv-loc-pf-${loc}`, t('err.load', { message: pfErr }));
  else if (pf) _html(`jv-loc-pf-${loc}`, locPortfolioHtml(pf, loc));
}

// Map + table of every instrument (Other included); empty / failed G → the empty texts.
// Optional filter: when set to a loc key, scatter and table show only that location.
// The performance line chart always shows all locations for comparison.
export function renderUniverse(geo, pfs = {}, sort = { col: 'ret', asc: false }, filter = null) {
  const allRows = allInstruments(geo);
  const rows = filter ? allRows.filter(i => i.loc === filter) : allRows;
  drawGeoMap(geo, pfs, filter);
  const perfWrap = document.getElementById('jv-perf-chart-wrap');
  const hasPerf = _drawPerfChart(geo, pfs) || _drawInstChart(geo, filter);
  if (perfWrap) perfWrap.hidden = !hasPerf;
  const wrap = document.getElementById('jv-geo-table-wrap');
  _html('jv-geo-table', rows.length ? geoTableHtml(rows, sort, pfs) : '');
  if (wrap) wrap.hidden = !rows.length;
  _text('jv-geo-table-empty', rows.length ? '' : t('geo.table.empty'));
}
