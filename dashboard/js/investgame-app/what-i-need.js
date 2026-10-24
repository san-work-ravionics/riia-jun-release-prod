// ── Invest Game App — What I Need (F43 Phase 1) ──────────────────────────────
// Every number comes from the backend (core/retirement_plan.py, a port of the mock rev 39):
//   POST /api/experience/invest-game/retirement-plan/calculate  → result (camelCase, EUR, fractions)
//   GET  /api/experience/invest-game/retirement-plan            → saved plan or Europe preset
//   PUT  /api/v1/workflow/invest-game/retirement-plan           → save on the Save button (signed-in
//                                                                    users only; also appends a history row)
// This module only reads the form, renders the result and formats the copy (D7).
import { mkChart, C } from '../shared/charts.js';
import { api, apiFetch } from './api.js';

const CALC_PATH = '/api/experience/invest-game/retirement-plan/calculate';
const PLAN_PATH = '/api/experience/invest-game/retirement-plan';
const SAVE_PATH = '/api/v1/workflow/invest-game/retirement-plan';

const ASSETS = [
  { key: 'idx',  name: 'Index fund',  color: 'rgba(26,107,60,.75)' },
  { key: 'eq',   name: 'Equity',      color: 'rgba(0,86,184,.8)' },
  { key: 'com',  name: 'Commodities', color: 'rgba(180,83,9,.75)' },
  { key: 'alt',  name: 'Alternate',   color: 'rgba(107,47,160,.7)' },
];

const fmt  = v => (v < 0 ? '−€' : '€') + Math.abs(Math.round(v)).toLocaleString('en-US');
const fmtK = v => v < 0 ? '−' + fmtK(-v) : v >= 1e6 ? '€' + (v / 1e6).toFixed(2).replace(/\.?0+$/, '') + 'M' : '€' + Math.round(v / 1000) + 'k';
const num  = id => parseFloat(document.getElementById(id).value);
const set  = (id, text) => { const el = document.getElementById(id); if (el) el.textContent = text; };
const pct  = (v, d = 0) => (v * 100).toFixed(d) + '%';
const grid = { color: 'rgba(0,0,0,.035)' };
const mono = { family: C.mono, size: 10 };

function houseMode() {
  const active = document.querySelector('#wn-h2-mode .pill.active');
  return active ? active.dataset.mode : 'new';
}

function readInputs() {
  const p = {
    need: num('wn-need'), infl: num('wn-infl') / 100,
    now: num('wn-age-now'), ret: num('wn-age-ret'), end: num('wn-age-end'),
    tax: num('wn-i-tax') / 100, partial: num('wn-i-partial') / 100, exit: num('wn-i-exit'),
    hValue: num('wn-h-value'), hAppr: num('wn-h-appr') / 100, hSell: num('wn-h-sell'), hTax: num('wn-h-tax') / 100,
    h2Price: num('wn-h2-price'), h2Mode: houseMode(),
    sv: [1, 2, 3].map(i => ({ age: num(`wn-sv${i}-age`), amt: num(`wn-sv${i}-amt`) })),
    bx: [1, 2, 3].map(i => ({ age: num(`wn-bx${i}-age`), amt: num(`wn-bx${i}-amt`) })),
  };
  ASSETS.forEach(a => {
    p[a.key + 'Monthly'] = num(`wn-a-${a.key}-monthly`);
    p[a.key + 'Rate'] = num(`wn-a-${a.key}-rate`) / 100;
  });
  return p;
}

// How long it is sustainable: 'Sustainable until 71' or 'Sustainable beyond 85'
function outcome(p, port) {
  return port.runOut === null ? `Sustainable beyond ${p.end}` : `Sustainable until ${port.runOut}`;
}
// Where the invested corpus finishes once it is sold from the exit age on
function corpusOutcome(port, maxAge) {
  return port.corpusOut === null ? `Corpus never runs out (still growing at ${maxAge})` : `Corpus runs out at ${port.corpusOut}`;
}
// Event copy for the chart tooltip (backend returns kind + amount only)
function fmtEvent(e) {
  return e.kind === 'house' ? `house ${fmt(e.amount)}` : e.kind === 'saving' ? `one time +${fmt(e.amount)}` : `one time −${fmt(e.amount)}`;
}

// One chart: the pot of additional money with and without investment (a line stops at zero in the
// year it runs out — no minus values), and the invested corpus, sold from the exit age when short.
function renderCompare(p, r) {
  const ages = r.portfolio.points.map(x => x.age);
  const line = port => port.points.map(x =>
    port.runOut === null || x.age < port.runOut ? Math.round(x.pot) : x.age === port.runOut ? 0 : null);
  const marker = (age, text, color, position) => ({
    type: 'line', xMin: ages.indexOf(age), xMax: ages.indexOf(age), borderColor: color, borderWidth: 1, borderDash: [3, 3],
    label: { display: true, content: text, position, backgroundColor: color, padding: 3, font: { family: C.mono, size: 9 } },
  });
  const annotations = {};
  if (ages.includes(p.ret)) annotations.retire = marker(p.ret, `Retire ${p.ret}`, C.t4, 'start');
  if (r.portfolio.runOut !== null) annotations.out1 = marker(r.portfolio.runOut, `With: until ${r.portfolio.runOut}`, C.build, 'center');
  if (ages.includes(p.exit)) annotations.exit = marker(p.exit, `Exit ${p.exit}`, C.t4, 'start');
  if (ages.includes(r.portfolio.corpusOut)) annotations.cOut = marker(r.portfolio.corpusOut, `Corpus out ${r.portfolio.corpusOut}`, 'rgba(0,86,184,.7)', 'end');
  if (r.portfolio0.runOut !== null) annotations.out0 = marker(r.portfolio0.runOut, `Without: until ${r.portfolio0.runOut}`, C.t3, 'end');
  const pts = r.portfolio.points;
  mkChart('wn-port', {
    type: 'line',
    data: {
      labels: ages,
      datasets: [
        { label: 'Invested corpus', data: pts.map(x => Math.round(x.corpus)), borderColor: 'rgba(0,86,184,.5)', backgroundColor: 'rgba(0,86,184,.06)', fill: 'origin', borderWidth: 1, pointRadius: 0 },
        { label: 'Money pot, with investment', data: line(r.portfolio), borderColor: C.build, borderWidth: 2, pointRadius: 0 },
        { label: 'Money pot, without', data: line(r.portfolio0), borderColor: C.t3, borderDash: [5, 4], borderWidth: 1.5, pointRadius: 0 },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        title: { display: true, text: `Corpus at ${p.ret} ${fmtK(r.value)}  ·  monthly available at ${p.ret} ${fmt(r.atRet.monthly)}`, align: 'start', color: C.t3, font: { family: C.mono, size: 10, weight: '600' }, padding: { top: 0, bottom: 2 } },
        legend: { position: 'top', align: 'end', labels: { usePointStyle: true, pointStyle: 'line', boxWidth: 18, padding: 8, font: { size: 10 } } },
        tooltip: { callbacks: {
          title: i => 'Age ' + i[0].label,
          label: c => (c.parsed.y === null ? null : c.dataset.label + ': ' + fmt(c.parsed.y)),
          footer: i => { const x = pts[i[0].dataIndex]; return [x.income ? `monthly available ${fmt(x.income)}` : '', x.need ? `need ${fmt(x.need)}` : '', ...x.events.map(fmtEvent)].filter(Boolean).join(' · '); },
        } },
        annotation: { annotations },
      },
      scales: {
        x: { grid: { display: false }, ticks: { font: mono, maxTicksLimit: 11, maxRotation: 0 } },
        y: { grid, min: 0, ticks: { callback: fmtK, font: mono, maxTicksLimit: 5 } },
      },
    },
  });
}

function render(p, r) {
  // Row 1 — need
  set('wn-k-need-lbl', `Monthly need at ${p.ret}`);
  set('wn-k-need', fmt(r.years[0].monthly));
  set('wn-k-need-sub', `${fmt(p.need)} today, inflated ${p.ret - p.now} yrs`);
  // Monthly available by age: ages as columns; rows = total (with % of need), investing, pot, pot balance
  const cls = c => [c.off ? 'off' : '', c.age === p.ret ? 'ret' : ''].filter(Boolean).join(' ');
  const cell = (c, html, extra = '') => `<td class="${[cls(c), extra].filter(Boolean).join(' ')}">${c.off ? '—' : html}</td>`;
  document.getElementById('wn-age-head').innerHTML = '<tr><th>Age</th>' + r.byAge.map(c =>
    `<th class="${cls(c)}" title="${c.off ? 'outside plan' : c.age === p.ret ? 'retirement age' : c.age > p.ret ? 'retired' : 'working'}">${c.age}</th>`).join('') + '</tr>';
  document.getElementById('wn-age-body').innerHTML = [
    '<tr class="total"><td>Available</td>' + r.byAge.map(c => cell(c, `<span title="${c.age >= p.ret ? pct(c.share) + ' of the need' : 'working'}">${fmt(c.monthly)}</span>`, !c.off && c.age >= p.ret && c.share >= 1 ? 'ok' : '')).join('') + '</tr>',
    '<tr class="need"><td>Need</td>' + r.byAge.map(c => cell(c, c.age >= p.ret ? fmt(c.need) : '—')).join('') + '</tr>',
    '<tr><td>Investing</td>' + r.byAge.map(c => cell(c, fmt(c.income))).join('') + '</tr>',
    '<tr><td>From pot</td>' + r.byAge.map(c => cell(c, fmt(c.fromPot))).join('') + '</tr>',
    '<tr><td>In pot</td>' + r.byAge.map(c => cell(c, fmtK(c.pot))).join('') + '</tr>',
    '<tr><td>Corpus</td>' + r.byAge.map(c => cell(c, fmtK(c.corpus))).join('') + '</tr>',
  ].join('');

  // Row 2 — investments
  document.getElementById('wn-idx-start').value = p.now;
  document.getElementById('wn-i-partial-age').value = p.ret;
  set('wn-idx-badge', `Index · Equity · Commodities · Alternate · invest ${p.now} → ${p.ret}, ${pct(p.partial)} of profit out + rest re-invested from ${p.ret}, all profit out + sell when short from ${p.exit}`);
  r.assets.forEach(a => {
    set(`wn-k-${a.key}-badge`, `${pct(a.rate, 1)} / yr`);
    set(`wn-k-${a.key}-fv-lbl`, `Value at ${p.ret}`);
    set(`wn-k-${a.key}-fv`, fmt(a.value));
    set(`wn-k-${a.key}-put`, fmt(a.put));
    set(`wn-k-${a.key}-gain-lbl`, 'Gain');
    set(`wn-k-${a.key}-gain`, fmt(a.gain));
    set(`wn-k-${a.key}-tax-lbl`, `Profit / month at ${p.ret}`);
    set(`wn-k-${a.key}-tax`, fmt(a.profitM));
    set(`wn-k-${a.key}-net-lbl`, `Withdrawn ${pct(p.partial)} / month, after tax`);
    set(`wn-k-${a.key}-net`, fmt(a.withdrawnNet));
  });

  // Row 3 — mortgage
  const same = p.h2Mode === 'same';
  set('wn-h-badge', same ? `Continue same house · nothing released` : `Sell at ${p.hSell} · buy new house`);
  set('wn-k-hfv-lbl', `Value at ${p.hSell}`);
  set('wn-h2-title', `House after ${p.hSell}`);
  set('wn-k-htax-lbl', `Tax on gain (${pct(p.hTax)})`);
  set('wn-k-hfv', fmt(r.hValueAt));
  set('wn-k-hfv-sub', `${fmt(p.hValue)} at ${pct(p.hAppr, 1)} for ${p.hSell - p.now} yrs`);
  set('wn-k-hgain', fmt(r.hGain));
  set('wn-k-htax', fmt(r.hTaxAmt));
  set('wn-k-hnet', fmt(r.hNet));
  document.getElementById('wn-h2-price').disabled = same;
  document.getElementById('wn-h2-calc').disabled = same;
  set('wn-k-h2now', same ? '—' : fmt(p.h2Price));
  set('wn-k-h2fv-lbl', `New house at ${p.hSell}`);
  set('wn-k-h2fv', same ? '—' : fmt(r.h2At));
  set('wn-k-hsale', same ? '—' : fmt(r.hNet));
  set('wn-k-hrel', fmt(r.houseRelease));
  set('wn-k-hrel-sub', same ? 'continue same house: appreciation not counted'
    : r.houseRelease >= 0 ? 'sale − new house, lowers what you need' : 'new house costs more, raises what you need');

  // One time events: savings in, expenses out
  set('wn-bx-total', `Net ${r.savings >= r.bigExpenses ? '+' : ''}${fmt(r.savings - r.bigExpenses)}`);

  // Feedback under Mortgage: how close the monthly available is to the need
  const fb = document.getElementById('wn-h-fb');
  const c0 = r.atRet;
  fb.innerHTML = `Monthly available at ${c0.age}: <b>${fmt(c0.monthly)}</b> of ${fmt(c0.need)} needed (<b>${pct(c0.share)}</b>) · ${outcome(p, r.portfolio)} · ${corpusOutcome(r.portfolio, r.maxAge)}`;
  fb.className = 'wn-fb' + (c0.share >= 1 ? ' ok' : '');

  // Without vs with investment in one chart — same plan, house and one time events in both
  set('wn-c1-badge', `With: ${outcome(p, r.portfolio)}`);
  set('wn-c0-badge', `Without: ${outcome(p, r.portfolio0)}`);
  renderCompare(p, r);

  // Year table — plain-sum need next to the money pot with and without investment
  const at = port => Object.fromEntries(port.points.map(x => [x.age, port.runOut === null || x.age < port.runOut ? x.pot : 0]));
  const p0 = at(r.portfolio0), p1 = at(r.portfolio);
  document.getElementById('wn-year-body').innerHTML = r.years.map(y =>
    `<tr><td>${y.age}</td><td>${y.year}</td><td class="num">${fmt(y.monthly)}</td><td class="num">${fmt(y.cum)}</td>` +
    `<td class="num">${p0[y.age] > 0 ? fmt(p0[y.age]) : '—'}</td><td class="num">${p1[y.age] > 0 ? fmt(p1[y.age]) : '—'}</td></tr>`).join('');

  // Pot chart — what you put in, plus growth per asset
  set('wn-pot-title', `Your investment pot, age ${p.now} → ${p.end}`);
  const ages = r.pot.map(x => x.age);
  const marker = (age, text, color) => ({
    type: 'line', xMin: ages.indexOf(age), xMax: ages.indexOf(age), borderColor: color, borderWidth: 1.5, borderDash: [4, 4],
    label: { display: true, content: text, position: 'start', backgroundColor: color, font: { family: C.mono, size: 9 } },
  });
  const annotations = {};
  if (ages.includes(p.ret)) annotations.retire = marker(p.ret, `Retire ${p.ret}`, C.t3);
  mkChart('wn-pot', {
    type: 'bar',
    data: {
      labels: ages,
      datasets: [
        { label: 'You put in', data: r.pot.map(x => Math.round(x.put)), backgroundColor: 'rgba(184,178,166,.9)', stack: 'pot' },
        ...ASSETS.map(a => ({ label: `${a.name} growth`, data: r.pot.map(x => Math.round(x[a.key])), backgroundColor: a.color, stack: 'pot' })),
        { type: 'line', label: 'Still needed', data: ages.map(() => Math.round(r.target)), borderColor: C.warn, borderDash: [6, 4], borderWidth: 1.5, pointRadius: 0, stack: 'target' },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { position: 'top', labels: { usePointStyle: true, boxWidth: 10, font: { size: 11 } } },
        tooltip: { mode: 'index', intersect: false, callbacks: { title: i => 'Age ' + i[0].label, label: c => c.dataset.label + ': ' + fmt(c.parsed.y) } },
        annotation: { annotations },
      },
      scales: {
        x: { stacked: true, grid, ticks: { font: mono, maxTicksLimit: 12 } },
        y: { stacked: true, grid, ticks: { callback: fmtK, font: mono } },
      },
    },
  });
  mkChart('wn-spend', {
    type: 'bar',
    data: { labels: r.years.map(y => y.age), datasets: [{ label: 'Monthly need', data: r.years.map(y => Math.round(y.monthly)), backgroundColor: 'rgba(26,107,60,.75)', borderRadius: 3 }] },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: { title: i => 'Age ' + i[0].label, label: c => fmt(c.parsed.y) + ' / month' } } },
      scales: { x: { grid, ticks: { font: mono, maxTicksLimit: 10 } }, y: { grid, ticks: { callback: v => '€' + v.toLocaleString('en-US'), font: mono } } },
    },
  });
}

// Fill the form from saved / preset inputs (same shape as readInputs(); rates as fractions)
const PCT = new Set(['infl', 'tax', 'partial', 'hAppr', 'hTax', 'idxRate', 'eqRate', 'comRate', 'altRate']);
const FIELD_IDS = {
  need: 'wn-need', infl: 'wn-infl', now: 'wn-age-now', ret: 'wn-age-ret', end: 'wn-age-end',
  tax: 'wn-i-tax', partial: 'wn-i-partial', exit: 'wn-i-exit',
  hValue: 'wn-h-value', hAppr: 'wn-h-appr', hSell: 'wn-h-sell', hTax: 'wn-h-tax', h2Price: 'wn-h2-price',
};
ASSETS.forEach(a => { FIELD_IDS[a.key + 'Monthly'] = `wn-a-${a.key}-monthly`; FIELD_IDS[a.key + 'Rate'] = `wn-a-${a.key}-rate`; });

function writeInputs(inputs) {
  const put = (id, v) => { const el = document.getElementById(id); if (el) el.value = v === null || v === undefined ? '' : v; };
  Object.entries(FIELD_IDS).forEach(([k, id]) => {
    const v = inputs[k];
    put(id, v === null || v === undefined ? '' : PCT.has(k) ? +(v * 100).toFixed(6) : v);
  });
  ['sv', 'bx'].forEach(g => (inputs[g] || []).forEach((x, i) => {
    put(`wn-${g}${i + 1}-age`, x.age);
    put(`wn-${g}${i + 1}-amt`, x.amt);
  }));
  document.querySelectorAll('#wn-h2-mode .pill').forEach(b => {
    const on = b.dataset.mode === inputs.h2Mode;
    b.classList.toggle('active', on);
    b.setAttribute('aria-pressed', String(on));
  });
}

// Save is explicit (Save button in the Age panel): signed-in only. It recalculates first so
// the saved plan is the one on screen; the backend stores it and appends a history row.
// apiFetch, not api(): a 401 must not redirect to Google login and lose the form.
let _lastSaved = null;
let _restored = false;
let _dirty = false;    // user edited the form before the restore GET returned → don't overwrite
function flash(cls, text, ms = 1600) {
  const status = document.getElementById('wn-status');
  clearTimeout(_flash);
  status.className = 'badge ' + cls;
  status.textContent = text;
  if (ms) _flash = setTimeout(() => { status.className = 'badge neu'; status.textContent = 'Europe · EUR'; }, ms);
}
let _saving = false;   // one Save at a time — a double click must not write two history rows
async function savePlan() {
  if (!_restored || _saving) return;
  const token = sessionStorage.getItem('auth_token');
  if (!token) { flash('neu', 'Sign in to save', 2400); return; }
  _saving = true;
  try {
    if (!(await calculate())) return;    // invalid inputs: the badge already shows why
    const p = readInputs();
    const body = JSON.stringify(p);
    if (body === _lastSaved) { flash('ok', 'Already saved'); return; }
    const res = await apiFetch(SAVE_PATH, {
      method: 'PUT', body,
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
    });
    if (res && res.saved) { _lastSaved = body; flash('ok', 'Saved'); }
    else flash('neu', 'Could not save — try again', 2400);
  } finally {
    _saving = false;
  }
}

let _flash = null;
let _seq = 0;
// Returns true when the result was rendered.
async function calculate() {
  const p = readInputs();
  const status = document.getElementById('wn-status');
  const seq = ++_seq;
  let r;
  try {
    r = await api(CALC_PATH, 'POST', p);
  } catch (e) {
    if (seq !== _seq) return;            // a newer request is in flight
    clearTimeout(_flash);
    status.className = 'badge neu';      // never red (D7); last good render stays
    status.textContent = (e && e.message) || 'Could not calculate — try again';
    return false;
  }
  if (seq !== _seq || !r) return false;  // stale response — drop it
  render(p, r);
  flash('ok', 'Updated', 1200);
  return true;
}

let _bound = false;
let _loaded = false;
export async function loadWhatINeed() {
  if (!_bound) {
    _bound = true;
    ['wn-calc', 'wn-i-calc', 'wn-h-calc', 'wn-h2-calc', 'wn-bx-calc'].forEach(id => document.getElementById(id).addEventListener('click', () => calculate()));
    document.getElementById('wn-save').addEventListener('click', () => savePlan());
    // Any edit before the restore finishes wins over the restored plan
    document.getElementById('sec-what-i-need').addEventListener('input', () => { if (!_restored) _dirty = true; });
    // Enter in any field recalculates too
    document.getElementById('sec-what-i-need').addEventListener('keydown', e => {
      if (e.key === 'Enter' && e.target.tagName === 'INPUT') { e.preventDefault(); calculate(); }
    });
    document.querySelectorAll('#wn-h2-mode .pill').forEach(btn => btn.addEventListener('click', () => {
      if (!_restored) _dirty = true;
      document.querySelectorAll('#wn-h2-mode .pill').forEach(b => {
        b.classList.toggle('active', b === btn);
        b.setAttribute('aria-pressed', String(b === btn));
      });
      calculate();
    }));
  }
  if (!_loaded) {
    _loaded = true;
    // Restore the saved plan (or the Europe preset); on any error keep the HTML defaults.
    try {
      const token = sessionStorage.getItem('auth_token');
      const plan = await apiFetch(PLAN_PATH, token ? { headers: { 'Authorization': `Bearer ${token}` } } : {});
      if (plan && plan.inputs && !_dirty) {
        writeInputs(plan.inputs);
        if (plan.saved) _lastSaved = JSON.stringify(readInputs());
      }
    } catch (e) {
      // keep HTML defaults
    } finally {
      _restored = true;
    }
  }
  await calculate();
}
