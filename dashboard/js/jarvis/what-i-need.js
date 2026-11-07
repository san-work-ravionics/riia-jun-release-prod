// F43 Phase 5 — "What I Need" retirement calculator tab in Jarvis.
// Scenarios (pessimistic/base/optimistic), waterfall chart, discounted corpus toggle.
import { api } from '../shared/api.js';
import { mkChart, C } from '../shared/charts.js';
import { t } from './copy.js?v=4';
import { fmtMoney, fmtRate, fmtNum, isNum } from './format.js?v=3';

let _spread = null;
let _scenarios = null;
let _activeScenario = 'base';
let _chart = null;
let _seq = 0;

const $ = id => document.getElementById(id);

const AGES = [55, 60, 65, 70, 75, 80, 85];
const INPUT_IDS = [
  'jv-wn-need', 'jv-wn-infl', 'jv-wn-age-now', 'jv-wn-age-ret', 'jv-wn-age-end',
  'jv-wn-tax', 'jv-wn-partial', 'jv-wn-exit',
  'jv-wn-h-value', 'jv-wn-h-appr', 'jv-wn-h-sell', 'jv-wn-h-tax',
  'jv-wn-h2-price', 'jv-wn-h2-mode',
  'jv-wn-idx-monthly', 'jv-wn-idx-rate',
  'jv-wn-eq-monthly', 'jv-wn-eq-rate',
  'jv-wn-com-monthly', 'jv-wn-com-rate',
  'jv-wn-alt-monthly', 'jv-wn-alt-rate',
];

function _val(id) {
  const el = $(id);
  if (!el) return null;
  if (el.type === 'select-one') return el.value;
  const v = parseFloat(el.value);
  return Number.isFinite(v) ? v : null;
}

function _readInputs() {
  const svRows = [0, 1, 2].map(i => ({
    age: _val(`jv-wn-sv-${i}-age`),
    amt: _val(`jv-wn-sv-${i}-amt`),
  }));
  const bxRows = [0, 1, 2].map(i => ({
    age: _val(`jv-wn-bx-${i}-age`),
    amt: _val(`jv-wn-bx-${i}-amt`),
  }));
  return {
    need: _val('jv-wn-need'), infl: _val('jv-wn-infl'),
    now: _val('jv-wn-age-now'), ret: _val('jv-wn-age-ret'), end: _val('jv-wn-age-end'),
    tax: _val('jv-wn-tax'), partial: _val('jv-wn-partial'), exit: _val('jv-wn-exit'),
    hValue: _val('jv-wn-h-value'), hAppr: _val('jv-wn-h-appr'),
    hSell: _val('jv-wn-h-sell'), hTax: _val('jv-wn-h-tax'),
    h2Price: _val('jv-wn-h2-price'), h2Mode: _val('jv-wn-h2-mode') || 'same',
    sv: svRows, bx: bxRows,
    idxMonthly: _val('jv-wn-idx-monthly'), idxRate: _val('jv-wn-idx-rate'),
    eqMonthly: _val('jv-wn-eq-monthly'), eqRate: _val('jv-wn-eq-rate'),
    comMonthly: _val('jv-wn-com-monthly'), comRate: _val('jv-wn-com-rate'),
    altMonthly: _val('jv-wn-alt-monthly'), altRate: _val('jv-wn-alt-rate'),
  };
}

function _fillForm(inputs) {
  const map = {
    'jv-wn-need': inputs.need, 'jv-wn-infl': inputs.infl,
    'jv-wn-age-now': inputs.now, 'jv-wn-age-ret': inputs.ret, 'jv-wn-age-end': inputs.end,
    'jv-wn-tax': inputs.tax, 'jv-wn-partial': inputs.partial, 'jv-wn-exit': inputs.exit,
    'jv-wn-h-value': inputs.hValue, 'jv-wn-h-appr': inputs.hAppr,
    'jv-wn-h-sell': inputs.hSell, 'jv-wn-h-tax': inputs.hTax,
    'jv-wn-h2-price': inputs.h2Price,
    'jv-wn-idx-monthly': inputs.idxMonthly, 'jv-wn-idx-rate': inputs.idxRate,
    'jv-wn-eq-monthly': inputs.eqMonthly, 'jv-wn-eq-rate': inputs.eqRate,
    'jv-wn-com-monthly': inputs.comMonthly, 'jv-wn-com-rate': inputs.comRate,
    'jv-wn-alt-monthly': inputs.altMonthly, 'jv-wn-alt-rate': inputs.altRate,
  };
  for (const [id, v] of Object.entries(map)) {
    const el = $(id);
    if (el && v != null) el.value = v;
  }
  const mode = $(('jv-wn-h2-mode'));
  if (mode && inputs.h2Mode) mode.value = inputs.h2Mode;
  if (inputs.sv) inputs.sv.forEach((r, i) => {
    const a = $(`jv-wn-sv-${i}-age`); if (a && r.age != null) a.value = r.age;
    const m = $(`jv-wn-sv-${i}-amt`); if (m && r.amt != null) m.value = r.amt;
  });
  if (inputs.bx) inputs.bx.forEach((r, i) => {
    const a = $(`jv-wn-bx-${i}-age`); if (a && r.age != null) a.value = r.age;
    const m = $(`jv-wn-bx-${i}-amt`); if (m && r.amt != null) m.value = r.amt;
  });
}

function _setStatus(msg, isError) {
  const el = $('jv-wn-status');
  if (!el) return;
  el.textContent = msg || '';
  el.className = isError ? 'wn-status wn-err' : 'wn-status';
}

function _ccy(location) {
  const m = { europe: 'EUR', india: 'INR', us: 'USD' };
  return m[location] || 'EUR';
}

// ── waterfall chart ─────────────────────────────────────────────────────────

function renderWaterfall(scenarios, ccy) {
  const canvas = $('jv-wn-waterfall');
  if (!canvas) return;
  const sc = scenarios[_activeScenario];
  if (!sc) return;
  const wf = sc.waterfall;
  const labels = [
    t('wn.wf.need'), t('wn.wf.portfolio'), t('wn.wf.house'),
    t('wn.wf.savings'), t('wn.wf.remaining'),
  ];
  let running = wf.needAll;
  const bottoms = [];
  const heights = [];
  const colours = [];

  bottoms.push(0); heights.push(wf.needAll);
  colours.push(C.accent || '#6366f1');

  running -= wf.portfolioValue;
  bottoms.push(running); heights.push(wf.portfolioValue);
  colours.push(C.green || '#22c55e');

  running -= wf.houseRelease;
  bottoms.push(running); heights.push(wf.houseRelease);
  colours.push(C.blue || '#3b82f6');

  running -= wf.savings;
  bottoms.push(running); heights.push(wf.savings);
  colours.push(C.teal || '#14b8a6');

  bottoms.push(0); heights.push(Math.max(running, 0));
  colours.push(running > 0 ? (C.warn || '#f59e0b') : (C.green || '#22c55e'));

  if (_chart) _chart.destroy();
  _chart = mkChart(canvas, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        data: heights.map((h, i) => [bottoms[i], bottoms[i] + h]),
        backgroundColor: colours,
        borderRadius: 3,
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => fmtMoney(ctx.raw[1] - ctx.raw[0], ccy),
          },
        },
      },
      scales: {
        x: { grid: { display: false } },
        y: {
          ticks: { callback: v => fmtMoney(v, ccy) },
        },
      },
    },
  });
}

// ── summary panel ───────────────────────────────────────────────────────────

function renderSummary(scenarios, ccy) {
  const wrap = $('jv-wn-summary');
  if (!wrap) return;
  const rows = ['pessimistic', 'base', 'optimistic'].filter(k => scenarios[k]);
  if (!rows.length) { wrap.innerHTML = ''; return; }
  let html = '<table class="tbl"><thead><tr><th></th>';
  for (const k of rows) html += `<th>${t('wn.scenario.' + k)}</th>`;
  html += '</tr></thead><tbody>';
  const fields = [
    ['wn.sum.need', r => fmtMoney(r.result.needAll, ccy)],
    ['wn.sum.portfolio', r => fmtMoney(r.result.value, ccy)],
    ['wn.sum.target', r => fmtMoney(r.result.target, ccy)],
    ['wn.sum.sustainable', r => r.result.withInvesting.savingsOut != null ? String(r.result.withInvesting.savingsOut) : t('wn.beyond')],
    ['wn.sum.portfolioOut', r => r.result.withInvesting.portfolioOut != null ? String(r.result.withInvesting.portfolioOut) : t('wn.beyond')],
  ];
  const disc = $('jv-wn-discount-toggle');
  if (disc && disc.checked) {
    fields.push(['wn.sum.discounted', r => r.discountedTarget != null ? fmtMoney(r.discountedTarget, ccy) : '—']);
  }
  for (const [key, fn] of fields) {
    html += `<tr><td>${t(key)}</td>`;
    for (const k of rows) html += `<td>${fn(scenarios[k])}</td>`;
    html += '</tr>';
  }
  html += '</tbody></table>';
  wrap.innerHTML = html;
}

// ── age table ───────────────────────────────────────────────────────────────

function renderAgeTable(result, ccy) {
  const wrap = $('jv-wn-age-table');
  if (!wrap || !result) return;
  const cells = result.byAge || [];
  if (!cells.length) { wrap.innerHTML = ''; return; }
  let html = '<table class="tbl"><thead><tr><th>' + t('wn.age.header') + '</th>';
  for (const c of cells) html += `<th>${c.age}${c.age === (result.atRet && result.atRet.age) ? ' ★' : ''}</th>`;
  html += '</tr></thead><tbody>';
  html += '<tr><td>' + t('wn.age.monthly') + '</td>';
  for (const c of cells) html += `<td>${c.off ? '—' : fmtMoney(c.monthly, ccy)}</td>`;
  html += '</tr><tr><td>' + t('wn.age.need') + '</td>';
  for (const c of cells) html += `<td>${c.off ? '—' : fmtMoney(c.need, ccy)}</td>`;
  html += '</tr><tr><td>' + t('wn.age.share') + '</td>';
  for (const c of cells) html += `<td>${c.off ? '—' : fmtRate(c.share)}</td>`;
  html += '</tr></tbody></table>';
  wrap.innerHTML = html;
}

// ── scenario tabs ───────────────────────────────────────────────────────────

function _updateScenarioTabs() {
  for (const k of ['pessimistic', 'base', 'optimistic']) {
    $(`jv-wn-sc-${k}`)?.classList.toggle('is-active', k === _activeScenario);
  }
}

function _selectScenario(name, ccy) {
  _activeScenario = name;
  _updateScenarioTabs();
  if (_scenarios) {
    renderWaterfall(_scenarios, ccy);
    renderSummary(_scenarios, ccy);
    const sc = _scenarios[name];
    if (sc) renderAgeTable(sc.result, ccy);
  }
}

// ── load + calculate ────────────────────────────────────────────────────────

export async function loadWhatINeed(location) {
  const seq = ++_seq;
  const ccy = _ccy(location);
  _setStatus(t('wn.loading'), false);
  try {
    const data = await api(`/api/v1/experience/jarvis/retirement-plan?location=${encodeURIComponent(location)}`);
    if (seq !== _seq) return;
    _spread = data.scenarioSpread;
    if (data.plan && data.plan.inputs) _fillForm(data.plan.inputs);
    if (!data.plan.saved) _setStatus(t('wn.defaults', { location }), false);
    else _setStatus('', false);
  } catch (e) {
    if (seq !== _seq) return;
    _setStatus(t('wn.err.load', { message: e.message }), true);
  }
}

export async function calculateScenarios(location) {
  const seq = ++_seq;
  const ccy = _ccy(location);
  const inputs = _readInputs();
  const spread = _spread || { pessimistic: -0.02, optimistic: 0.02 };
  const discToggle = $('jv-wn-discount-toggle');
  const discRate = discToggle && discToggle.checked ? _val('jv-wn-discount-rate') : null;
  _setStatus(t('wn.calculating'), false);
  const btn = $('jv-wn-calc');
  if (btn) btn.disabled = true;
  try {
    const data = await api('/api/v1/experience/jarvis/retirement-plan/calculate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ inputs, scenarios: ['pessimistic', 'base', 'optimistic'], spread, discountRate: discRate }),
    });
    if (seq !== _seq) return;
    _scenarios = data.scenarios;
    renderWaterfall(_scenarios, ccy);
    renderSummary(_scenarios, ccy);
    const sc = _scenarios[_activeScenario];
    if (sc) renderAgeTable(sc.result, ccy);
    _setStatus('', false);
  } catch (e) {
    if (seq !== _seq) return;
    _setStatus(e.message || t('wn.err.calculate'), true);
  } finally {
    if (btn) btn.disabled = false;
  }
}

export async function saveWhatINeed(location) {
  const inputs = _readInputs();
  _setStatus(t('wn.saving'), false);
  try {
    await api(`/api/v1/workflow/invest-game/retirement-plan?location=${encodeURIComponent(location)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(inputs),
    });
    _setStatus(t('wn.saved'), false);
  } catch (e) {
    _setStatus(e.message || t('wn.err.save'), true);
  }
}

// ── init ────────────────────────────────────────────────────────────────────

export function initWhatINeed(getLocation) {
  $('jv-wn-calc')?.addEventListener('click', () => calculateScenarios(getLocation()));
  $('jv-wn-save')?.addEventListener('click', () => saveWhatINeed(getLocation()));
  for (const k of ['pessimistic', 'base', 'optimistic']) {
    $(`jv-wn-sc-${k}`)?.addEventListener('click', () => _selectScenario(k, _ccy(getLocation())));
  }
  const discToggle = $('jv-wn-discount-toggle');
  const discInput = $('jv-wn-discount-rate');
  if (discToggle) {
    discToggle.addEventListener('change', () => {
      if (discInput) discInput.disabled = !discToggle.checked;
      if (_scenarios) renderSummary(_scenarios, _ccy(getLocation()));
    });
  }
  _updateScenarioTabs();
}
