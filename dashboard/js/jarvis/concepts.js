// Jarvis — Concepts page: how the flow works (RITA Concepts card + "Agents & Linked Analytics" tabs).
// One tab per flow step: a summary of how Jarvis arrives at it, then two panels with the user's own
// numbers for the selected location — from A4 state, A5 portfolio and A6 instrument, nothing new
// fetched. Only the active tab's charts are drawn (Chart.js can't size a hidden canvas).
import { mkChart, destroyChart, chartOpts, C } from '../shared/charts.js';
import { esc } from './esc.js?v=2';
import { t } from './copy.js?v=2';
import { fmtRate, fmtMoney, fmtDate, fmtYears, isNum, locationName } from './format.js?v=2';
import { sleeveDatasets, priceDatasets } from './instrument.js?v=2';

export const STEPS = ['s1', 's2', 's3', 's4', 's5', 's6', 's7', 's8'];

// What you say → which MCP tools run (jarvis_chat_service.py intent handlers; every turn also reads
// journey.get_current).
const INTENT_TOOLS = [
  ['use my goal', 'whatineed.get_goal · journey.save'],
  ['build my portfolio', 'portfolio.select_for_goal · journey.save'],
  ['why these instruments', 'portfolio.model_runs · portfolio.sleeve_trace'],
  ['show the closest mix', 'journey.get_current'],
  ['track it', 'portfolio.sleeve_trace · journey.save'],
  ['how am I doing', 'portfolio.pnl · portfolio.required_return · journey.save'],
  ['what if a stop loss hits', 'portfolio.sleeve_trace · portfolio.required_return'],
  ['yes / no (a proposal)', 'portfolio.sleeve_trace · journey.save'],
  ['how do I protect it', 'fno.get_hedge_plan'],
];

const MODULE_TOOLS = [
  ['What I Need', 'whatineed.get_goal'],
  ['Portfolio (RITA)', 'portfolio.select_for_goal · portfolio.model_runs · portfolio.sleeve_trace · portfolio.pnl · portfolio.required_return'],
  ['FnO', 'fno.sigma_levels · fno.get_hedge_plan'],
  ['Market', 'market.asta_trace'],
  ['Journey', 'journey.get_current · journey.save'],
];

const STATES = ['no_goal', 'goal_loaded', 'selected', 'cant_reach', 'tracking', 'reselect_proposed', 'back_to_plan'];

const _pct = v => `${(v * 100).toFixed(1)}%`;

function _sel(j) {
  return j && (j.selection || null);
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
export function flowTableHtml() {
  const rows = STEPS.map((s, i) => `<tr><td><strong>${i + 1} · ${esc(t(`cx.${s}.tab`))}</strong></td>
    <td class="mono" style="font-size:11px">${esc(t(`cx.${s}.who`))}</td><td>${esc(t(`cx.${s}.kind`))}</td></tr>`).join('');
  return `<table class="jv-table"><thead><tr><th>${esc(t('cx.flow.col.step'))}</th><th>${esc(t('cx.flow.col.who'))}</th>
    <th>${esc(t('cx.flow.col.kind'))}</th></tr></thead><tbody>${rows}</tbody></table>`;
}

export function stepBarHtml(state) {
  const order = { no_goal: 0, goal_loaded: 1, selected: 4, cant_reach: 4, tracking: 5, reselect_proposed: 6, back_to_plan: 6 };
  const reached = state in order ? order[state] : -1;
  return STEPS.map((s, i) => {
    const cls = i < reached ? 'done' : i === reached ? 'active' : '';
    return `<div class="step-seg ${cls}">${i + 1} ${esc(t(`cx.${s}.tab`))}</div>`;
  }).join('');
}

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
  const { state, pf, inst } = data;
  const j = state && state.journey;
  const goal = j || (state && state.goal);
  const sel = _sel(j);
  const live = (state && state.live_holdings) || [];
  const perf = pf && pf.perf;
  const instId = inst && inst.instrument_id;
  const rita = inst && (inst.engines || []).find(e => e.engine === 'rita');
  let a = '';
  let b = '';
  switch (step) {
    case 's1':
      a = goal && isNum(goal.goal_return)
        ? `<div class="kpi-row-2">${_tile(t('plan.goal.return'), fmtRate(goal.goal_return))}${_tile(t('plan.goal.horizon'), fmtYears(goal.horizon_years))}
           ${_tile(t('plan.goal.value'), fmtMoney(goal.goal_value, goal.currency))}${_tile(t('plan.goal.saved'), fmtDate(goal.plan_updated_at))}</div>`
        : _empty();
      b = perf && (perf.target_path || []).length ? _canvas('jv-cx-s1b') : _empty();
      break;
    case 's2': {
      a = _tableHtml([t('cx.s2.col.intent'), t('cx.s2.col.tools')], INTENT_TOOLS);
      const has = ((state && state.messages) || []).some(m => m.role === 'assistant' && m.intent);
      b = has ? _canvas('jv-cx-s2b') : _empty();
      break;
    }
    case 's3':
      a = rita && ((rita.series || {}).sleeve_value || []).length ? _canvas('jv-cx-s3a') : _empty(inst ? null : t('cx.empty.inst'));
      b = live.some(h => isNum(h.invested_fraction)) ? _canvas('jv-cx-s3b') : _empty();
      break;
    case 's4':
      a = sel && (sel.ladder || []).length ? _canvas('jv-cx-s4a') : _empty();
      b = sel && (isNum(sel.fit_return) || isNum(sel.test_return)) ? _canvas('jv-cx-s4b') : _empty();
      break;
    case 's5':
      a = live.some(h => isNum(h.sl_distance)) ? _canvas('jv-cx-s5a') : _empty();
      b = rita && (rita.prices || []).length ? _canvas('jv-cx-s5b') : _empty(inst ? null : t('cx.empty.inst'));
      break;
    case 's6': {
      a = perf && (perf.series || []).length ? _canvas('jv-cx-s6a') : _empty();
      const req = pf && pf.required;
      const used = j && isNum(j.reselect_count) ? `${j.reselect_count} / ${j.max_reselections}` : '—';
      b = perf
        ? `<div class="kpi-row-2">${_tile(t('target.kpi.to_date'), fmtRate(perf.target_to_date))}
           ${_tile(t('target.kpi.actual'), fmtRate(perf.ytd_return), isNum(perf.ytd_return) ? (perf.ytd_return >= 0 ? 'pos' : 'neg') : '')}
           ${_tile(t('target.kpi.required'), fmtRate(req && req.required_return))}${_tile(t('cx.s6.used'), used)}</div>`
        : _empty();
      break;
    }
    case 's7':
      a = pf && (pf.engines || []).some(e => isNum(e.return_since)) ? _canvas('jv-cx-s7a') : _empty();
      b = pf && (pf.engines || []).some(e => isNum(e.coverage)) ? _canvas('jv-cx-s7b') : _empty();
      break;
    case 's8': {
      a = _tableHtml([t('cx.s8.col.module'), t('cx.s8.col.tools')], MODULE_TOOLS);
      const cur = j ? j.state : 'no_goal';
      b = `<div class="cx-states">${STATES.map(s => `<span class="cx-state${s === cur ? ' is-current' : ''}">${esc(t(`state.${s}`))}</span>`).join('<span class="cx-arrow">→</span>')}</div>`;
      break;
    }
    default:
      return '';
  }
  const ttl = k => t(`cx.${step}.${k}`, { instrument: instId || '—' });
  return `<p class="concept-desc">${esc(_desc(step, j))}</p>
    <div class="concept-chart-grid">${_wrap(step, 'a', ttl('c1'), a)}${_wrap(step, 'b', ttl('c2'), b)}</div>`;
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

export const CHART_IDS = ['jv-cx-s1b', 'jv-cx-s2b', 'jv-cx-s3a', 'jv-cx-s3b', 'jv-cx-s4a', 'jv-cx-s4b',
                          'jv-cx-s5a', 'jv-cx-s5b', 'jv-cx-s6a', 'jv-cx-s7a', 'jv-cx-s7b'];

function _has(id) {
  return typeof document !== 'undefined' && !!document.getElementById(id);
}

export function drawStep(step, data = {}) {
  const { state, pf, inst } = data;
  const j = state && state.journey;
  const sel = _sel(j);
  const live = (state && state.live_holdings) || [];
  const perf = pf && pf.perf;
  const rita = inst && (inst.engines || []).find(e => e.engine === 'rita');
  CHART_IDS.forEach(destroyChart);
  if (step === 's1' && _has('jv-cx-s1b')) {
    const labels = perf.target_path.map(p => fmtDate(p.date));
    mkChart('jv-cx-s1b', { type: 'line', data: { labels, datasets: [{ label: t('target.kpi.to_date'), data: perf.target_path.map(p => p.target), borderColor: C.t3, borderDash: [5, 4], borderWidth: 1.6, pointRadius: labels.length < 3 ? 3 : 0 }] },
      options: chartOpts('', _pct, labels) });
  }
  if (step === 's2' && _has('jv-cx-s2b')) {
    const counts = {};
    for (const m of state.messages || []) if (m.role === 'assistant' && m.intent) counts[m.intent] = (counts[m.intent] || 0) + 1;
    const labels = Object.keys(counts);
    mkChart('jv-cx-s2b', { type: 'bar', data: { labels, datasets: [{ data: labels.map(k => counts[k]), backgroundColor: '#BE185D', borderRadius: 3, maxBarThickness: 36 }] },
      options: _barOpts(v => (Number.isInteger(v) ? v : ''), labels) });
  }
  if (step === 's3') {
    if (_has('jv-cx-s3a')) {
      const { labels, datasets } = sleeveDatasets(rita);
      mkChart('jv-cx-s3a', { type: 'line', data: { labels, datasets }, options: chartOpts('', v => v.toFixed(2), labels) });
    }
    if (_has('jv-cx-s3b')) {
      const rows = live.filter(h => isNum(h.invested_fraction));
      const labels = rows.map(h => h.instrument_id);
      mkChart('jv-cx-s3b', { type: 'bar', data: { labels, datasets: [{ data: rows.map(h => h.invested_fraction), backgroundColor: C.run, borderRadius: 3, maxBarThickness: 36 }] },
        options: _barOpts(v => `${Math.round(v * 100)}%`, labels) });
    }
  }
  if (step === 's4') {
    if (_has('jv-cx-s4a')) {
      const lad = sel.ladder;
      const labels = lad.map(r => `τ ${r.tolerance}`);
      const o = _barOpts(_pct, labels);
      o.plugins.legend = { display: true, labels: { generateLabels: () => [
        { text: t('cx.s4.feasible'), fillStyle: C.build, strokeStyle: C.build }, { text: t('cx.s4.infeasible'), fillStyle: C.t4, strokeStyle: C.t4 }] } };
      mkChart('jv-cx-s4a', { type: 'bar', data: { labels, datasets: [{ data: lad.map(r => r.fit_vol), backgroundColor: lad.map(r => (r.feasible ? C.build : C.t4)), borderRadius: 3, maxBarThickness: 48 }] }, options: o });
    }
    if (_has('jv-cx-s4b')) {
      const labels = [t('cx.s4.fit'), t('cx.s4.test')];
      const goal = isNum(sel.target_return) ? sel.target_return : j.goal_return;
      const o = _barOpts(_pct, labels);
      o.plugins.legend.display = true;
      mkChart('jv-cx-s4b', { type: 'bar', data: { labels, datasets: [
        { type: 'bar', label: t('plan.selection.title'), data: [sel.fit_return, sel.test_return], backgroundColor: [C.run, sel.meets_goal ? C.build : C.warn], borderRadius: 3, maxBarThickness: 64 },
        { type: 'line', label: t('cx.s4.goal'), data: labels.map(() => goal), borderColor: C.danger, borderDash: [5, 4], borderWidth: 1.4, pointRadius: 0 },
      ] }, options: o });
    }
  }
  if (step === 's5') {
    if (_has('jv-cx-s5a')) {
      const rows = live.filter(h => isNum(h.sl_distance));
      const labels = rows.map(h => h.instrument_id);
      mkChart('jv-cx-s5a', { type: 'bar', data: { labels, datasets: [{ data: rows.map(h => h.sl_distance), backgroundColor: rows.map(h => (h.sl_hit ? C.danger : C.build)), borderRadius: 3, maxBarThickness: 36 }] },
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

function _el(id) { return document.getElementById(id); }

export function renderConcepts(data, location) {
  _data = data || {};
  const j = _data.state && _data.state.journey;
  const bar = _el('jv-cx-steps');
  if (bar) bar.innerHTML = stepBarHtml(j ? j.state : 'no_goal');
  const tbl = _el('jv-cx-flow');
  if (tbl) tbl.innerHTML = flowTableHtml();
  const st = _el('jv-cx-status');
  if (st) st.textContent = statusText(_data.state, _data.pf, location);
  showStep(_active);
}

export function showStep(step) {
  _active = STEPS.includes(step) ? step : 's1';
  const tabs = _el('jv-cx-tabs');
  if (tabs) tabs.innerHTML = tabBarHtml(_active);
  const panel = _el('jv-cx-panel');
  if (panel) panel.innerHTML = panelHtml(_active, _data);
  drawStep(_active, _data);
}

// Delegated on the tab bar (data-step).
export function initConcepts() {
  _el('jv-cx-tabs')?.addEventListener('click', e => {
    const b = e.target.closest('button[data-step]');
    if (b) showStep(b.dataset.step);
  });
}
