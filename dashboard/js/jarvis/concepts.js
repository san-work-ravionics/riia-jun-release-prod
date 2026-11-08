// Jarvis — Concepts page: the data science and AI concepts behind the Jarvis flow, stage by stage
// (RITA Concepts card + "Agents & Linked Analytics" tabs).  One tab per stage: what the concept is and
// whether it is a model or a rule, then panels with the user's own numbers — from the saved plan (A4 goal),
// the saved portfolio of every region (A5) and the opened instrument (A6), plus the MCP call log.  It
// explains the flow, not the chat.  Only the active tab's charts are drawn (Chart.js can't size a hidden canvas).
import { api } from '../shared/api.js';
import { mkChart, destroyChart, chartOpts, C } from '../shared/charts.js';
import { esc } from './esc.js?v=3';
import { t } from './copy.js?v=19';
import { fmtRate, fmtMoney, fmtNum, fmtDate, fmtYears, isNum, locationName } from './format.js?v=3';
import { sleeveDatasets, priceDatasets } from './instrument.js?v=3';

export const STEPS = ['s1', 's2', 's3', 's4', 's5', 's6', 's7', 's8'];

// Stage 2: how raw market data becomes the features and returns every later stage reads.
const DATA_STAGES = [
  ['Daily prices', 'Delta refresh of OHLCV from the data provider into local files and the price cache; insert-only, run on demand, never from a request'],
  ['Returns', 'Daily, 5-day, 21-day and 1-year price returns per instrument'],
  ['Indicators', 'RSI-14 · MACD · Bollinger %B · ATR-14 · EMA 5/13/26'],
  ['Regions', 'Country → Europe, India or US; each region in its own currency'],
  ['FX rates', 'EUR→INR and EUR→USD daily, used to add regions together in EUR'],
];

// Stage 8: the namespaced MCP tools, by module (all read-only except the journey record).
const MODULE_TOOLS = [
  ['What I Need', 'whatineed.get_goal · whatineed.get_plan · whatineed.bucket_status'],
  ['Portfolio (RITA)', 'portfolio.get_holdings · portfolio.pnl · portfolio.select_for_goal · portfolio.model_runs · portfolio.sleeve_trace · portfolio.required_return · portfolio.optimal_allocation'],
  ['FnO', 'fno.sigma_levels · fno.position_value · fno.get_hedge_plan'],
  ['Market', 'market.overview · market.monitor · market.asta_trace · market.fx_rate · market.ask'],
  ['Journey', 'journey.get_current · journey.save'],
];

const _pct = v => `${(v * 100).toFixed(1)}%`;

function _sel(j) {
  return j && (j.selection || null);
}

const _LOC_COLOR = { europe: C.run, india: C.warn, us: C.mon };

// The user's saved portfolio rows (held / picked) across every region, each tagged with its region.
function _mine(data) {
  const pfs = (data && data.pfs) || {};
  const out = [];
  for (const loc of Object.keys(pfs)) {
    for (const r of (pfs[loc] && pfs[loc].instruments) || []) if (r.held || r.selected) out.push({ ...r, loc });
  }
  if (!out.length && data && data.pf) {
    for (const r of data.pf.instruments || []) if (r.held || r.selected) out.push({ ...r });
  }
  return out;
}

// Each region's own perf (return this year, target to date, plan goal) from its saved plan and portfolio.
function _regionPerf(data) {
  const pfs = (data && data.pfs) || {};
  const out = Object.keys(pfs).filter(l => pfs[l] && pfs[l].perf).map(l => ({ loc: l, perf: pfs[l].perf }));
  if (!out.length && data && data.pf && data.pf.perf) out.push({ loc: data.pf.location, perf: data.pf.perf });
  return out;
}

// Target path from the saved plan: (1+r)^(m/12) - 1 at month starts, Jan to Dec of this year.
function _planPath(goal) {
  if (!goal || !isNum(goal.goal_return)) return [];
  const y = new Date().getFullYear();
  return Array.from({ length: 13 }, (_, m) => ({
    date: m < 12 ? `${y}-${String(m + 1).padStart(2, '0')}-01` : `${y}-12-31`,
    target: Math.pow(1 + goal.goal_return, m / 12) - 1,
  }));
}

function _targetPath(goal, perf) {
  return perf && (perf.target_path || []).length ? perf.target_path : _planPath(goal);
}

// Stage 2, the user's side: each held instrument across every region with its latest close and data date.
function _dataRows(data) {
  const pfs = (data && data.pfs) || {};
  const rows = [];
  for (const loc of Object.keys(pfs)) {
    const pf = pfs[loc];
    for (const r of (pf && pf.instruments) || []) {
      if ((r.held || r.selected) && isNum(r.last_close)) {
        rows.push([r.instrument_id, locationName(loc), fmtNum(r.last_close), fmtDate(pf.as_of)]);
      }
    }
  }
  if (!rows.length && data && data.pf) {
    for (const r of data.pf.instruments || []) {
      if ((r.held || r.selected) && isNum(r.last_close)) {
        rows.push([r.instrument_id, locationName(data.pf.location), fmtNum(r.last_close), fmtDate(data.pf.as_of)]);
      }
    }
  }
  return rows;
}

function _window(w) {
  return w ? `${fmtDate(w.start)} – ${fmtDate(w.end)}` : '—';
}

function _slLimit(j) {
  const tr = (j && j.tracking) || [];
  const lim = tr.map(x => x.sl_drawdown_limit).find(isNum);
  if (isNum(lim)) return lim;
  const hs = (_sel(j) && _sel(j).holdings) || [];
  return hs.map(h => h.sl_drawdown_limit).find(isNum);
}

// ── static HTML ────────────────────────────────────────────────────────────────
export function tabBarHtml(active) {
  return STEPS.map((s, i) => `<button type="button" class="concept-tab${s === active ? ' active' : ''}" data-step="${s}">${i + 1} · ${esc(t(`cx.${s}.tab`))}</button>`).join('');
}

function _desc(step, j) {
  const sel = _sel(j);
  const slots = {
    fit: sel ? _window(sel.fit_window) : '2023 – 2024',
    test: sel ? _window(sel.test_window) : '2025 – today',
    limit: isNum(_slLimit(j)) ? fmtRate(Math.abs(_slLimit(j)), 0) : '10%',
    max: j && isNum(j.max_reselections) ? j.max_reselections : 2,
  };
  return t(`cx.${step}.desc`, slots);
}

function _wrap(step, half, title, body) {
  const label = half === 'a' ? t('cx.label.step') : t('cx.label.linked');
  return `<div class="chart-wrap"><div class="chart-col-label">${esc(label)}</div>
    <div class="chart-title">${esc(title)}</div>${body}</div>`;
}

function _canvas(id) {
  return `<div class="chart-box" style="height:240px"><canvas id="${id}"></canvas></div>`;
}

function _empty(text) {
  return `<div class="cx-empty">${esc(text || t('cx.empty'))}</div>`;
}

function _tile(label, value, cls = '') {
  return `<div class="kpi kpi-sm"><div class="kpi-label">${esc(label)}</div><div class="kpi-value ${cls}">${esc(value)}</div></div>`;
}

function _tableHtml(head, rows) {
  return `<div class="tbl-wrap" style="box-shadow:none;max-height:240px;overflow-y:auto"><table class="jv-table jv-table-sm"><thead><tr>${head.map(h => `<th>${esc(h)}</th>`).join('')}</tr></thead>
    <tbody>${rows.map(r => `<tr>${r.map((c, i) => `<td${i ? ' class="mono" style="font-size:11px"' : ''}>${esc(c)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
}

// Panel bodies: a canvas when the data is there, else a table / tiles / empty note.
export function panelHtml(step, data = {}) {
  const { state, pf, inst, mcp } = data;
  const j = state && state.journey;
  const goal = j || (state && state.goal);
  const mine = _mine(data);
  const perf = pf && pf.perf;
  const instId = inst && inst.instrument_id;
  const rita = inst && (inst.engines || []).find(e => e.engine === 'rita');
  let a = '';
  let b = '';
  let c = '';
  switch (step) {
    case 's1':
      a = goal && isNum(goal.goal_return)
        ? `<div class="kpi-row-2">${_tile(t('plan.goal.return'), fmtRate(goal.goal_return))}${_tile(t('plan.goal.horizon'), fmtYears(goal.horizon_years))}
           ${_tile(t('plan.goal.value'), fmtMoney(goal.goal_value, goal.currency))}${_tile(t('plan.goal.saved'), fmtDate(goal.plan_updated_at))}</div>`
        : _empty();
      b = _targetPath(goal, perf).length ? _canvas('jv-cx-s1b') : _empty();
      break;
    case 's2': {
      a = _tableHtml([t('cx.s2.col.stage'), t('cx.s2.col.what')], DATA_STAGES);
      const rows = _dataRows(data);
      b = rows.length ? _tableHtml([t('cx.s2.col.inst'), t('cx.s2.col.region'), t('cx.s2.col.close'), t('cx.s2.col.asof')], rows) : _empty();
      break;
    }
    case 's3':
      a = rita && ((rita.series || {}).sleeve_value || []).length ? _canvas('jv-cx-s3a') : _empty(inst ? t('cx.empty.model') : t('cx.empty.inst'));
      b = mine.some(h => isNum(h.invested_fraction)) ? _canvas('jv-cx-s3b') : _empty(mine.length ? t('cx.empty.model') : null);
      break;
    case 's4':
      a = mine.some(h => isNum(h.allocation_pct)) ? _canvas('jv-cx-s4a') : _empty();
      b = _regionPerf(data).some(r => isNum(r.perf.goal_return) || isNum(r.perf.ytd_return)) ? _canvas('jv-cx-s4b') : _empty();
      break;
    case 's5':
      a = mine.some(h => isNum(h.sl_distance) || isNum(h.ret)) ? _canvas('jv-cx-s5a') : _empty();
      b = rita && (rita.prices || []).length ? _canvas('jv-cx-s5b') : _empty(inst ? t('cx.empty.model') : t('cx.empty.inst'));
      break;
    case 's6': {
      a = perf && (perf.series || []).length ? _canvas('jv-cx-s6a') : _empty();
      const req = pf && pf.required;
      b = perf
        ? `<div class="kpi-row-2">${_tile(t('target.kpi.to_date'), fmtRate(perf.target_to_date))}
           ${_tile(t('target.kpi.actual'), fmtRate(perf.ytd_return), isNum(perf.ytd_return) ? (perf.ytd_return >= 0 ? 'pos' : 'neg') : '')}
           ${_tile(t('target.kpi.required'), fmtRate(req && req.required_return))}</div>`
        : _empty();
      break;
    }
    case 's7':
      a = pf && (pf.engines || []).some(e => isNum(e.return_since)) ? _canvas('jv-cx-s7a') : _empty(t('cx.empty.engines'));
      b = pf && (pf.engines || []).some(e => isNum(e.coverage)) ? _canvas('jv-cx-s7b') : _empty();
      break;
    case 's8': {
      a = _tableHtml([t('cx.s8.col.module'), t('cx.s8.col.tools')], MODULE_TOOLS);
      const wait = mcp ? t('cx.empty.mcp') : t('cx.loading');
      b = mcp && mcp.length ? _canvas('jv-cx-s8b') : _empty(wait);
      c = mcp && mcp.length
        ? _tableHtml([t('cx.s8.col.time'), t('cx.s8.col.tool'), t('cx.s8.col.status')],
          mcp.slice(0, 12).map(r => [String(r.timestamp || '').slice(0, 19), r.tool_name, r.status]))
        : _empty(wait);
      break;
    }
    default:
      return '';
  }
  const ttl = k => t(`cx.${step}.${k}`, { instrument: instId || '—' });
  const slOn = mine.some(h => isNum(h.sl_distance));
  const titleA = step === 's5' && !slOn ? t('cx.s5.c1alt') : ttl('c1');
  const meta = `<div class="cx-meta"><span><b>${esc(t('cx.flow.col.who'))}</b><span class="mono">${esc(t(`cx.${step}.who`))}</span></span><span><b>${esc(t('cx.flow.col.kind'))}</b>${esc(t(`cx.${step}.kind`))}</span></div>`;
  return `${meta}<p class="concept-desc">${esc(_desc(step, j))}</p>
    <div class="concept-chart-grid"${c ? ' style="grid-template-columns:repeat(3,minmax(0,1fr))"' : ''}>${_wrap(step, 'a', titleA, a)}${_wrap(step, 'b', ttl('c2'), b)}${c ? _wrap(step, 'c', ttl('c3'), c) : ''}</div>`;
}

export function statusText(state, pf, location) {
  const as_of = (pf && pf.as_of) || (state && (state.live_holdings || []).map(h => h.as_of).filter(Boolean).sort().pop());
  return t('cx.tabs.status', { location: locationName(location), as_of: fmtDate(as_of) });
}

// ── charts ─────────────────────────────────────────────────────────────────────
function _barOpts(tick, labels) {
  const o = chartOpts('', tick, labels);
  o.scales.x.ticks.maxTicksLimit = labels.length;
  o.plugins.legend.display = false;
  return o;
}

export const CHART_IDS = ['jv-cx-s1b', 'jv-cx-s3a', 'jv-cx-s3b', 'jv-cx-s4a', 'jv-cx-s4b',
                          'jv-cx-s5a', 'jv-cx-s5b', 'jv-cx-s6a', 'jv-cx-s7a', 'jv-cx-s7b', 'jv-cx-s8b'];

function _has(id) {
  return typeof document !== 'undefined' && !!document.getElementById(id);
}

export function drawStep(step, data = {}) {
  const { state, pf, inst, mcp } = data;
  const j = state && state.journey;
  const goal = j || (state && state.goal);
  const mine = _mine(data);
  const perf = pf && pf.perf;
  const rita = inst && (inst.engines || []).find(e => e.engine === 'rita');
  CHART_IDS.forEach(destroyChart);
  if (step === 's1' && _has('jv-cx-s1b')) {
    const path = _targetPath(goal, perf);
    const labels = path.map(p => fmtDate(p.date));
    mkChart('jv-cx-s1b', { type: 'line', data: { labels, datasets: [{ label: t('target.kpi.to_date'), data: path.map(p => p.target), borderColor: C.t3, borderDash: [5, 4], borderWidth: 1.6, pointRadius: labels.length < 3 ? 3 : 0 }] },
      options: chartOpts('', _pct, labels) });
  }
  if (step === 's8' && _has('jv-cx-s8b') && mcp && mcp.length) {
    const counts = {};
    for (const r of mcp) counts[r.tool_name] = (counts[r.tool_name] || 0) + 1;
    const top = Object.entries(counts).sort((x, y) => y[1] - x[1]).slice(0, 10);
    const labels = top.map(r => r[0]);
    mkChart('jv-cx-s8b', { type: 'bar', data: { labels, datasets: [{ data: top.map(r => r[1]), backgroundColor: C.mon, borderRadius: 3, maxBarThickness: 36 }] },
      options: _barOpts(v => (Number.isInteger(v) ? v : ''), labels) });
  }
  if (step === 's3') {
    if (_has('jv-cx-s3a')) {
      const { labels, datasets } = sleeveDatasets(rita);
      mkChart('jv-cx-s3a', { type: 'line', data: { labels, datasets }, options: chartOpts('', v => v.toFixed(2), labels) });
    }
    if (_has('jv-cx-s3b')) {
      const rows = mine.filter(h => isNum(h.invested_fraction));
      const labels = rows.map(h => h.instrument_id);
      mkChart('jv-cx-s3b', { type: 'bar', data: { labels, datasets: [{ data: rows.map(h => h.invested_fraction), backgroundColor: C.run, borderRadius: 3, maxBarThickness: 36 }] },
        options: _barOpts(v => `${Math.round(v * 100)}%`, labels) });
    }
  }
  if (step === 's4') {
    if (_has('jv-cx-s4a')) {
      const rows = mine.filter(h => isNum(h.allocation_pct));
      const labels = rows.map(h => h.instrument_id);
      mkChart('jv-cx-s4a', { type: 'bar', data: { labels, datasets: [{ data: rows.map(h => h.allocation_pct / 100), backgroundColor: rows.map(h => _LOC_COLOR[h.loc] || C.build), borderRadius: 3, maxBarThickness: 48 }] },
        options: _barOpts(_pct, labels) });
    }
    if (_has('jv-cx-s4b')) {
      const regs = _regionPerf(data);
      const labels = regs.map(r => locationName(r.loc));
      const o = _barOpts(_pct, labels);
      o.plugins.legend.display = true;
      mkChart('jv-cx-s4b', { type: 'bar', data: { labels, datasets: [
        { label: t('cx.s4.mine'), data: regs.map(r => r.perf.ytd_return), backgroundColor: C.run, borderRadius: 3, maxBarThickness: 40 },
        { label: t('cx.s4.todate'), data: regs.map(r => r.perf.target_to_date), backgroundColor: C.t3, borderRadius: 3, maxBarThickness: 40 },
        { label: t('cx.s4.plan'), data: regs.map(r => r.perf.goal_return), backgroundColor: C.danger, borderRadius: 3, maxBarThickness: 40 },
      ] }, options: o });
    }
  }
  if (step === 's5') {
    if (_has('jv-cx-s5a')) {
      const useSl = mine.some(h => isNum(h.sl_distance));
      const val = h => (useSl ? h.sl_distance : h.ret);
      const rows = mine.filter(h => isNum(val(h)));
      const labels = rows.map(h => h.instrument_id);
      mkChart('jv-cx-s5a', { type: 'bar', data: { labels, datasets: [{ data: rows.map(val), backgroundColor: rows.map(h => (useSl ? (h.sl_hit ? C.danger : C.build) : (val(h) >= 0 ? C.build : C.danger))), borderRadius: 3, maxBarThickness: 36 }] },
        options: _barOpts(_pct, labels) });
    }
    if (_has('jv-cx-s5b')) {
      const { labels, datasets } = priceDatasets(rita);
      const o = chartOpts('', v => v.toFixed(0), labels);
      o.plugins.legend.labels.filter = item => !['derisk', 'rerisk'].includes(item.text);
      mkChart('jv-cx-s5b', { type: 'line', data: { labels, datasets }, options: o });
    }
  }
  if (step === 's6' && _has('jv-cx-s6a')) {
    const dates = [...new Set([...perf.series.map(x => fmtDate(x.date)), ...(perf.target_path || []).map(x => fmtDate(x.date))])].sort();
    const act = Object.fromEntries(perf.series.map(x => [fmtDate(x.date), x.ret]));
    const tgt = Object.fromEntries((perf.target_path || []).map(x => [fmtDate(x.date), x.target]));
    mkChart('jv-cx-s6a', { type: 'line', data: { labels: dates, datasets: [
      { label: t('target.kpi.actual'), data: dates.map(d => act[d] ?? null), borderColor: C.run, borderWidth: 1.8, pointRadius: dates.length < 3 ? 3 : 0, spanGaps: true },
      { label: t('target.kpi.to_date'), data: dates.map(d => tgt[d] ?? null), borderColor: C.t3, borderDash: [5, 4], borderWidth: 1.4, pointRadius: dates.length < 3 ? 3 : 0, spanGaps: true },
    ] }, options: chartOpts('', _pct, dates) });
  }
  if (step === 's7') {
    const engines = pf.engines || [];
    if (_has('jv-cx-s7a')) {
      const rows = engines.filter(e => isNum(e.return_since));
      const labels = rows.map(e => e.label);
      const ttd = engines.map(e => e.target_to_date).find(isNum);
      const ds = [{ type: 'bar', label: t('engine.col.return'), data: rows.map(e => e.return_since), backgroundColor: rows.map(e => (e.on_pace ? C.build : C.warn)), borderRadius: 3, maxBarThickness: 48 }];
      if (isNum(ttd)) ds.push({ type: 'line', label: t('engine.col.target'), data: rows.map(() => ttd), borderColor: C.t3, borderDash: [5, 4], borderWidth: 1.4, pointRadius: 0 });
      const o = _barOpts(_pct, labels);
      o.plugins.legend.display = true;
      mkChart('jv-cx-s7a', { type: 'bar', data: { labels, datasets: ds }, options: o });
    }
    if (_has('jv-cx-s7b')) {
      const rows = engines.filter(e => isNum(e.coverage));
      const labels = rows.map(e => e.label);
      mkChart('jv-cx-s7b', { type: 'bar', data: { labels, datasets: [{ data: rows.map(e => e.coverage), backgroundColor: C.mon, borderRadius: 3, maxBarThickness: 48 }] },
        options: _barOpts(v => `${Math.round(v * 100)}%`, labels) });
    }
  }
}

// ── DOM ────────────────────────────────────────────────────────────────────────
let _active = 's1';
let _data = {};
let _mcp = null;        // MCP call log rows (null = not loaded yet)
let _mcpReq = false;

function _loadMcp() {
  if (_mcp !== null || _mcpReq) return;
  _mcpReq = true;
  api('/api/v1/mcp-calls?limit=200')
    .then(rows => { _mcp = Array.isArray(rows) ? rows : []; })
    .catch(() => { _mcp = []; })
    .finally(() => { _mcpReq = false; if (_active === 's8') showStep('s8'); });
}

function _el(id) { return document.getElementById(id); }

export function renderConcepts(data, location) {
  _data = data || {};
  const st = _el('jv-cx-status');
  if (st) st.textContent = statusText(_data.state, _data.pf, location);
  showStep(_active);
}

export function showStep(step) {
  _active = STEPS.includes(step) ? step : 's1';
  const tabs = _el('jv-cx-tabs');
  if (tabs) tabs.innerHTML = tabBarHtml(_active);
  const data = { ..._data, mcp: _mcp };
  const panel = _el('jv-cx-panel');
  if (panel) panel.innerHTML = panelHtml(_active, data);
  drawStep(_active, data);
  if (_active === 's8') _loadMcp();
}

// Delegated on the tab bar (data-step).
export function initConcepts() {
  _el('jv-cx-tabs')?.addEventListener('click', e => {
    const b = e.target.closest('button[data-step]');
    if (b) showStep(b.dataset.step);
  });
}
