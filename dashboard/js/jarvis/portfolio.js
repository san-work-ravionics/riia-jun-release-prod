// Jarvis — portfolio tab (A5): source label, KPIs, P&L chart (money only), return vs the target path,
// "needed for the rest of the year", the instrument grid (delegated click on data-inst) and the
// engine table + chart. Every figure is a field of the A5 payload.
import { api } from '../shared/api.js';
import { mkChart, destroyChart, chartOpts, C } from '../shared/charts.js';
import { portfolioCurrency } from '../shared/portfolio-currency.js';
import { esc } from './esc.js?v=3';
import { t } from './copy.js?v=3';
import { fmtRate, fmtPp, fmtMoney, fmtNum, fmtDate, isNum, locationName } from './format.js?v=3';
import { actionText } from './chat.js?v=3';

export function loadPortfolio(location) {
  return api(`/api/v1/experience/jarvis/portfolio?location=${encodeURIComponent(location)}`);
}

const _pctTick = v => `${(v * 100).toFixed(1)}%`;

// ── pure renders ───────────────────────────────────────────────────────────────
export function sourceText(pf, location) {
  const loc = locationName(location);
  const p = pf.perf;
  switch (pf.pnl_source) {
    case 'saved':
    case 'mixed':
      return p && p.money && p.money.legacy_note ? t('pf.source.legacy') : t('pf.source.location', { location: loc });
    case 'model_sleeves': return t('pf.source.model_sleeves', { location: loc });
    case 'model_sleeves_preview': return t('pf.source.preview', { date: fmtDate(p && p.year_start) });
    default: return t('pf.source.none', { location: loc });
  }
}

function _kpi(label, value, cls = '', size = ' kpi-sm') {
  return `<div class="kpi${size}"><div class="kpi-label">${esc(label)}</div><div class="kpi-value ${cls}">${esc(value)}</div></div>`;
}

const _sign = v => (isNum(v) ? (v > 0 ? 'pos' : v < 0 ? 'neg' : '') : '');

export function kpisHtml(pf) {
  const p = pf.perf;
  if (!p) return '';
  const m = p.money;
  const parts = [];
  if (m) {
    parts.push(_kpi(t('pf.kpi.value'), fmtMoney(m.value_now, pf.currency), '', ''));
    parts.push(_kpi(t('pf.kpi.pnl'), fmtMoney(m.pnl, pf.currency), _sign(m.pnl), ''));
    parts.push(_kpi(t('pf.kpi.return_since', { date: fmtDate(p.entry_date) }), fmtRate(m.return_since_entry), _sign(m.return_since_entry), ''));
  }
  parts.push(_kpi(t('pf.kpi.this_year'), fmtRate(p.ytd_return), _sign(p.ytd_return), ''));
  return parts.join('');
}

export function targetKpisHtml(pf) {
  const p = pf.perf || {};
  const req = pf.required;
  return [
    _kpi(t('target.kpi.year'), fmtRate(p.goal_return)),
    _kpi(t('target.kpi.to_date'), fmtRate(p.target_to_date)),
    _kpi(t('target.kpi.actual'), fmtRate(p.ytd_return), _sign(p.ytd_return)),
    _kpi(t('target.kpi.required'), fmtRate(req && req.required_return)),
  ].join('');
}

export function requiredText(pf, location) {
  const p = pf.perf;
  if (!p || !isNum(p.goal_return)) return t('target.status.none', { location: locationName(location) });
  const status = (pf.required && pf.required.status) || (['reselect_proposed', 'back_to_plan'].includes(pf.journey_state) ? pf.journey_state : null);
  return status ? t(`target.status.${status}`) : '';
}

function _inText(r) {
  if (r.held && r.selected) return t('grid.in.both');
  if (r.held) return t('grid.in.held');
  if (r.selected) return t('grid.in.selected');
  return '—';
}

// Largest weight first; the first row is selected by default.
export function sortInstruments(rows) {
  return (rows || []).slice().sort((a, b) => (isNum(b.allocation_pct) ? b.allocation_pct : -1) - (isNum(a.allocation_pct) ? a.allocation_pct : -1));
}

export function gridRowsHtml(rows, currency, selectedId) {
  return sortInstruments(rows).map(r => {
    const sl = isNum(r.sl_distance) ? `${fmtRate(r.sl_distance)}` : '—';
    return `<tr data-inst="${esc(r.instrument_id)}" class="${r.instrument_id === selectedId ? 'is-selected' : ''}">
      <td class="mono">${esc(r.instrument_id)}</td>
      <td>${esc(_inText(r))}</td>
      <td class="num">${esc(isNum(r.allocation_pct) ? `${r.allocation_pct}%` : '—')}</td>
      <td class="num">${esc(isNum(r.shares) ? String(r.shares) : '—')}</td>
      <td class="num">${esc(fmtNum(r.last_close))}</td>
      <td class="num ${_sign(r.pnl)}">${esc(fmtMoney(r.pnl, currency))}</td>
      <td class="num ${_sign(r.ret)}">${esc(fmtRate(r.ret))}</td>
      <td>${esc(r.model_action ? actionText(r.model_action) : '—')}</td>
      <td class="num">${esc(sl)}${r.sl_hit ? ` <span class="jv-badge warn">${esc(t('plan.selection.col.sl'))}</span>` : ''}</td></tr>`;
  }).join('');
}

export function engineStatusText(status, { instrument, reason } = {}) {
  if (!status || status === 'ok' || status === 'none') return '';
  return t(`engine.status.${status}`, { instrument, reason }) || t('engine.status.unavailable');
}

export function engineTableHtml(engines, location) {
  const rows = (engines || []).map(e => {
    const st = engineStatusText(e.status, { instrument: locationName(location) });
    const ok = e.status === 'ok';
    const pace = isNum(e.return_since) && e.on_pace !== null && e.on_pace !== undefined
      ? `<span class="${e.on_pace ? 'ok' : 'warn'}">${esc(t(e.on_pace ? 'engine.pace.on' : 'engine.pace.off'))}</span>` : '—';
    return `<tr><td>${esc(e.label)}${st ? `<div class="jv-muted">${esc(st)}</div>` : ''}</td>
      <td class="num">${esc(ok && isNum(e.coverage) ? fmtRate(e.coverage, 0) : '—')}</td>
      <td class="num ${_sign(e.return_since)}">${esc(fmtRate(e.return_since))}</td>
      <td class="num">${esc(fmtRate(e.target_to_date))}</td>
      <td class="num ${_sign(e.gap)}">${esc(fmtPp(e.gap))}</td>
      <td>${pace}</td></tr>`;
  }).join('');
  return `<table class="jv-table"><thead><tr><th>${esc(t('engine.col.engine'))}</th><th class="num">${esc(t('engine.col.covers'))}</th>
    <th class="num">${esc(t('engine.col.return'))}</th><th class="num">${esc(t('engine.col.target'))}</th>
    <th class="num">${esc(t('engine.col.gap'))}</th><th>${esc(t('engine.col.pace'))}</th></tr></thead><tbody>${rows}</tbody></table>`;
}

// ── P4c: one location column (compact KPIs + saved holdings or the Jarvis pick) ──
// DR-A3 field map: Value = perf.money.value_now · P&L = perf.money.pnl · This year = perf.ytd_return ·
// Target = perf.goal_return. Every amount is this location's own A5 figure in its own currency (D1).
function _kpiD(label, value, cls = '', delta = '', size = ' kpi-sm') {
  const d = delta ? `<div class="kpi-delta">${esc(delta)}</div>` : '';
  return `<div class="kpi${size}"><div class="kpi-label">${esc(label)}</div><div class="kpi-value ${cls}">${esc(value)}</div>${d}</div>`;
}

export function locKpisHtml(pf) {
  const p = (pf && pf.perf) || {};
  const m = p.money;
  const ccy = pf && pf.currency;
  const entryDelta = p.entry_date ? fmtDate(p.entry_date) : '';
  return [
    _kpiD(t('pf.kpi.value'), m ? fmtMoney(m.value_now, ccy) : '—', '', entryDelta),
    _kpiD(t('pf.kpi.pnl'), m ? fmtMoney(m.pnl, ccy) : '—', m ? _sign(m.pnl) : '', m && isNum(m.return_since_entry) ? fmtRate(m.return_since_entry) : ''),
    _kpiD(t('pf.kpi.this_year'), fmtRate(p.ytd_return), _sign(p.ytd_return), isNum(p.target_to_date) ? `${t('target.kpi.to_date')} ${fmtRate(p.target_to_date)}` : ''),
    _kpiD(t('loc.kpi.target'), fmtRate(p.goal_return), '', t('pf.kpi.annual')),
  ].join('');
}

function _chip(id, text) {
  return `<span class="jv-hold-chip"><b class="mono">${esc(id)}</b> ${esc(text)}</span>`;
}

function _upper(v) { return String(v ?? '').toUpperCase(); }

export function locPortfolioHtml(pf, loc) {
  if (!pf) return '';
  const p = pf.perf || {};
  const m = p.money;
  const kpis = `<div class="jv-loc-kpis">${locKpisHtml(pf)}</div>`;
  if (m) {
    const pct = Object.fromEntries((p.holdings || []).map(h => [_upper(h.instrument_id), h.allocation_pct]));
    const chips = (m.holdings || []).map(h => {
      const a = pct[_upper(h.instrument_id)];
      return _chip(h.instrument_id, t('loc.hold.chip', { pct: isNum(a) ? fmtNum(a, 0) : null, units: isNum(h.shares) ? String(h.shares) : null }));
    }).join('');
    const legacy = !!m.legacy_note;
    const cashLabel = legacy ? t('loc.hold.cash_eur') : t('loc.hold.cash');
    const cash = fmtMoney(m.cash, legacy ? portfolioCurrency(null) : pf.currency);
    const title = m.name ? `${t('loc.pf.title')} · ${m.name}` : t('loc.pf.title');
    return `<div class="jv-loc-pf-title">${esc(title)}</div>${kpis}
      <div class="jv-hold-chips">${chips}</div>
      <div class="jv-loc-cash"><span class="jv-muted">${esc(cashLabel)}</span> <b class="mono">${esc(cash)}</b></div>`;
  }
  const pick = (pf.instruments || []).filter(r => r.selected);
  if (pick.length) {
    const chips = sortInstruments(pick).map(r => _chip(r.instrument_id, isNum(r.allocation_pct) ? `${fmtNum(r.allocation_pct, 0)}%` : '—')).join('');
    return `<div class="jv-loc-pf-title">${esc(t('loc.pick.title'))}</div>${kpis}
      <div class="jv-hold-chips">${chips}</div><p class="jv-muted">${esc(t('loc.pick.note'))}</p>`;
  }
  return `${kpis}<p class="jv-muted">${esc(t('pf.source.none', { location: locationName(loc) }))}</p>`;
}

export function detailTitle(location, currency) {
  return t('pf.s3.title', { location: locationName(location), currency: currency || '—' });
}

export function detailDivider(location) {
  return t('pf.divider.detail', { LOCATION: locationName(location).toUpperCase() });
}

// ── charts ─────────────────────────────────────────────────────────────────────
function _drawPnl(pf) {
  const m = pf.perf && pf.perf.money;
  const empty = document.getElementById('jv-pnl-empty');
  const wrap = document.getElementById('jv-pnl-chart')?.closest('.chart-wrap');
  const series = (m && m.series) || [];
  if (!m || series.length < 2) {
    destroyChart('jv-pnl-chart');
    if (wrap) wrap.hidden = true;
    if (empty) { empty.textContent = m ? t('pnl.empty') : t('pnl.sleeves_note'); empty.hidden = false; }
    return;
  }
  if (wrap) wrap.hidden = false;
  if (empty) empty.hidden = true;
  const labels = series.map(p => fmtDate(p.date));
  mkChart('jv-pnl-chart', {
    type: 'line',
    data: { labels, datasets: [{ label: t('pf.kpi.pnl'), data: series.map(p => p.pnl), borderColor: C.run, backgroundColor: 'rgba(0,86,184,.08)', fill: true, pointRadius: 0, borderWidth: 1.6, tension: 0.15 }] },
    options: chartOpts('', v => fmtMoney(v, pf.currency), labels),
  });
}

function _drawTarget(pf) {
  const p = pf.perf;
  const wrap = document.getElementById('jv-target-chart')?.closest('.chart-wrap');
  if (!p || !(p.series || []).length) {
    destroyChart('jv-target-chart');
    if (wrap) wrap.hidden = true;
    return;
  }
  if (wrap) wrap.hidden = false;
  const dates = [...new Set([...(p.series || []).map(x => fmtDate(x.date)), ...(p.target_path || []).map(x => fmtDate(x.date))])].sort();
  const act = Object.fromEntries((p.series || []).map(x => [fmtDate(x.date), x.ret]));
  const tgt = Object.fromEntries((p.target_path || []).map(x => [fmtDate(x.date), x.target]));
  mkChart('jv-target-chart', {
    type: 'line',
    data: {
      labels: dates,
      datasets: [
        { label: t('target.kpi.actual'), data: dates.map(d => act[d] ?? null), borderColor: C.run, pointRadius: dates.length < 3 ? 3 : 0, borderWidth: 1.8, spanGaps: true },
        { label: t('target.kpi.to_date'), data: dates.map(d => tgt[d] ?? null), borderColor: C.t3, borderDash: [5, 4], pointRadius: dates.length < 3 ? 3 : 0, borderWidth: 1.4, spanGaps: true },
      ],
    },
    options: chartOpts('', _pctTick, dates),
  });
}

function _drawEngines(pf) {
  const rows = (pf.engines || []).filter(e => isNum(e.return_since));
  const wrap = document.getElementById('jv-engine-chart')?.closest('.chart-wrap');
  if (!rows.length) {
    destroyChart('jv-engine-chart');
    if (wrap) wrap.hidden = true;
    return;
  }
  if (wrap) wrap.hidden = false;
  const labels = rows.map(e => e.label);
  const ttd = (pf.engines || []).map(e => e.target_to_date).find(isNum);
  const datasets = [{ type: 'bar', label: t('engine.col.return'), data: rows.map(e => e.return_since),
                      backgroundColor: rows.map(e => (e.on_pace ? C.build : C.warn)), borderRadius: 3, maxBarThickness: 48 }];
  if (isNum(ttd)) {
    datasets.push({ type: 'line', label: t('engine.col.target'), data: rows.map(() => ttd), borderColor: C.t3,
                    borderDash: [5, 4], pointRadius: 0, borderWidth: 1.4 });
  }
  const opts = chartOpts('', _pctTick, labels);
  opts.scales.x.ticks.maxTicksLimit = labels.length;                 // chartOpts thins date axes; show every bar
  mkChart('jv-engine-chart', { type: 'bar', data: { labels, datasets }, options: opts });
}

// ── DOM ────────────────────────────────────────────────────────────────────────
function _html(id, html) {
  const el = document.getElementById(id);
  if (el) el.innerHTML = html;
}

function _text(id, text) {
  const el = document.getElementById(id);
  if (el) { el.textContent = text; el.hidden = !text; }
}

export function renderDetailHeader(location, currency) {
  const title = document.getElementById('jv-pf-detail-title');
  if (title) title.textContent = detailTitle(location, currency);
  const div = document.getElementById('jv-pf-detail-divider');
  if (div) div.textContent = detailDivider(location);
}

export function renderPortfolio(pf, location) {
  renderDetailHeader(location, pf.currency);
  _text('jv-pf-source', sourceText(pf, location));
  _html('jv-pf-kpis', kpisHtml(pf));
  _html('jv-target-kpis', targetKpisHtml(pf));
  _text('jv-target-required', requiredText(pf, location));
  _drawPnl(pf);
  _drawTarget(pf);
  const rows = sortInstruments(pf.instruments);
  const first = rows.length ? rows[0].instrument_id : null;
  _html('jv-grid-body', gridRowsHtml(rows, pf.currency, first));
  const empty = document.getElementById('jv-grid-empty');
  if (empty) { empty.textContent = rows.length ? '' : t('grid.empty', { location: locationName(location) }); empty.hidden = !!rows.length; }
  _html('jv-engine-table', engineTableHtml(pf.engines, location));
  const preview = (pf.engines || []).some(e => e.note === 'preview');
  _text('jv-engine-note', preview ? sourceText({ pnl_source: 'model_sleeves_preview', perf: pf.perf }, location) : '');
  _drawEngines(pf);
  return first;
}

export function markSelected(instrumentId) {
  document.querySelectorAll('#jv-grid-body tr[data-inst]').forEach(tr => {
    tr.classList.toggle('is-selected', tr.dataset.inst === instrumentId);
  });
}

// Delegated: one listener on the tbody; the row's data-inst is read from the dataset.
export function initGrid(onSelect) {
  document.getElementById('jv-grid-body')?.addEventListener('click', e => {
    const tr = e.target.closest('tr[data-inst]');
    if (!tr) return;
    markSelected(tr.dataset.inst);
    onSelect(tr.dataset.inst);
  });
}
