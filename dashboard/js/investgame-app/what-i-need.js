// ── Invest Game App — What I Need (F43 Phase 1) ──────────────────────────────
// Every number comes from the backend (core/retirement_plan.py, a port of the mock rev 39):
//   POST /api/experience/invest-game/retirement-plan/calculate  → result (camelCase, plan currency, fractions)
//   GET  /api/experience/invest-game/retirement-plan[?location=] → saved plan or the location preset
//   PUT  /api/v1/workflow/invest-game/retirement-plan?location=  → save on the Save button (signed-in
//                                                                    users only; also appends a history row)
// Locations: Europe (EUR), India (INR, lakh/crore grouping), US (USD). One saved plan per user.
// This module only reads the form, renders the result and formats the copy (D7).
import { mkChart, C } from '../shared/charts.js';
import { api, apiFetch, apiBase } from './api.js';
import { isLocalDev, ensureDevToken } from '../shared/dev-auth.js';

const CALC_PATH = '/api/experience/invest-game/retirement-plan/calculate';
const PLAN_PATH = '/api/experience/invest-game/retirement-plan';
const SAVE_PATH = '/api/v1/workflow/invest-game/retirement-plan';
const PENDING_KEY = 'wn_pending_save';   // plan inputs kept across the Google sign-in round trip

const ASSETS = [
  { key: 'idx',  name: 'Index fund',  color: 'rgba(26,107,60,.75)' },
  { key: 'eq',   name: 'Equity',      color: 'rgba(0,86,184,.8)' },
  { key: 'com',  name: 'Commodities', color: 'rgba(180,83,9,.75)' },
  { key: 'alt',  name: 'Alternate',   color: 'rgba(107,47,160,.7)' },
];

const LOCS = {
  europe: { name: 'Europe', ccy: 'EUR', sym: '€', locale: 'en-US' },
  india:  { name: 'India',  ccy: 'INR', sym: '₹', locale: 'en-IN' },
  us:     { name: 'US',     ccy: 'USD', sym: '$', locale: 'en-US' },
};
let _loc = 'europe';
const L = () => LOCS[_loc];
const dec2 = x => x.toFixed(2).replace(/\.?0+$/, '');
const fmt  = v => (v < 0 ? '−' : '') + L().sym + Math.abs(Math.round(v)).toLocaleString(L().locale);
// Short form: India in lakh (L) / crore (Cr), others in k / M
const fmtK = v => v < 0 ? '−' + fmtK(-v)
  : _loc === 'india' ? L().sym + (v >= 1e7 ? dec2(v / 1e7) + 'Cr' : v >= 1e5 ? dec2(v / 1e5) + 'L' : Math.round(v / 1000) + 'k')
  : L().sym + (v >= 1e6 ? dec2(v / 1e6) + 'M' : Math.round(v / 1000) + 'k');
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
  return port.savingsOut === null ? `Sustainable beyond ${p.end}` : `Sustainable until ${port.savingsOut}`;
}
// Where the invested portfolio is fully sold from the exit age on
function portfolioOutcome(port, maxAge) {
  return port.portfolioOut === null ? `Portfolio never runs out (still growing at ${maxAge})` : `Portfolio runs out at ${port.portfolioOut}`;
}
// Event copy for the chart tooltip (backend returns kind + amount only)
function fmtEvent(e) {
  return e.kind === 'house' ? `house ${fmt(e.amount)}` : e.kind === 'saving' ? `one time +${fmt(e.amount)}` : `one time −${fmt(e.amount)}`;
}

// One chart: the savings with and without investment (a line stops at zero in the
// year it runs out — no minus values), and the portfolio, sold from the exit age when short.
function renderCompare(p, r) {
  const ages = r.withInvesting.points.map(x => x.age);
  const line = port => port.points.map(x =>
    port.savingsOut === null || x.age < port.savingsOut ? Math.round(x.savings) : x.age === port.savingsOut ? 0 : null);
  const marker = (age, text, color, position) => ({
    type: 'line', xMin: ages.indexOf(age), xMax: ages.indexOf(age), borderColor: color, borderWidth: 1, borderDash: [3, 3],
    label: { display: true, content: text, position, backgroundColor: color, padding: 3, font: { family: C.mono, size: 9 } },
  });
  const annotations = {};
  if (ages.includes(p.ret)) annotations.retire = marker(p.ret, `Retire ${p.ret}`, C.t4, 'start');
  if (r.withInvesting.savingsOut !== null) annotations.out1 = marker(r.withInvesting.savingsOut, `With: until ${r.withInvesting.savingsOut}`, C.build, 'center');
  if (ages.includes(p.exit)) annotations.exit = marker(p.exit, `Exit ${p.exit}`, C.t4, 'start');
  if (ages.includes(r.withInvesting.portfolioOut)) annotations.cOut = marker(r.withInvesting.portfolioOut, `Portfolio out ${r.withInvesting.portfolioOut}`, 'rgba(0,86,184,.7)', 'end');
  if (r.withoutInvesting.savingsOut !== null) annotations.out0 = marker(r.withoutInvesting.savingsOut, `Without: until ${r.withoutInvesting.savingsOut}`, C.t3, 'end');
  const pts = r.withInvesting.points;
  mkChart('wn-port', {
    type: 'line',
    data: {
      labels: ages,
      datasets: [
        { label: 'Portfolio', data: pts.map(x => Math.round(x.portfolio)), borderColor: 'rgba(0,86,184,.5)', backgroundColor: 'rgba(0,86,184,.06)', fill: 'origin', borderWidth: 1, pointRadius: 0 },
        { label: 'Savings, with investment', data: line(r.withInvesting), borderColor: C.build, borderWidth: 2, pointRadius: 0 },
        { label: 'Savings, without', data: line(r.withoutInvesting), borderColor: C.t3, borderDash: [5, 4], borderWidth: 1.5, pointRadius: 0 },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        title: { display: true, text: `Portfolio at ${p.ret} ${fmtK(r.value)}  ·  monthly available at ${p.ret} ${fmt(r.atRet.monthly)}`, align: 'start', color: C.t3, font: { family: C.mono, size: 10, weight: '600' }, padding: { top: 0, bottom: 2 } },
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
    '<tr><td>From savings</td>' + r.byAge.map(c => cell(c, fmt(c.fromSavings))).join('') + '</tr>',
    '<tr><td>Savings</td>' + r.byAge.map(c => cell(c, fmtK(c.savings))).join('') + '</tr>',
    '<tr><td>Portfolio</td>' + r.byAge.map(c => cell(c, fmtK(c.portfolio))).join('') + '</tr>',
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
  fb.innerHTML = `Monthly available at ${c0.age}: <b>${fmt(c0.monthly)}</b> of ${fmt(c0.need)} needed (<b>${pct(c0.share)}</b>) · ${outcome(p, r.withInvesting)} · ${portfolioOutcome(r.withInvesting, r.maxAge)}`;
  fb.className = 'wn-fb' + (c0.share >= 1 ? ' ok' : '');

  // Without vs with investment in one chart — same plan, house and one time events in both
  set('wn-c1-badge', `With: ${outcome(p, r.withInvesting)}`);
  set('wn-c0-badge', `Without: ${outcome(p, r.withoutInvesting)}`);
  renderCompare(p, r);

  // Year table — plain-sum need next to savings with and without investment
  const at = port => Object.fromEntries(port.points.map(x => [x.age, port.savingsOut === null || x.age < port.savingsOut ? x.savings : 0]));
  const p0 = at(r.withoutInvesting), p1 = at(r.withInvesting);
  document.getElementById('wn-year-body').innerHTML = r.years.map(y =>
    `<tr><td>${y.age}</td><td>${y.year}</td><td class="num">${fmt(y.monthly)}</td><td class="num">${fmt(y.cum)}</td>` +
    `<td class="num">${p0[y.age] > 0 ? fmt(p0[y.age]) : '—'}</td><td class="num">${p1[y.age] > 0 ? fmt(p1[y.age]) : '—'}</td></tr>`).join('');

  // Portfolio growth chart — what you put in, plus growth per asset
  set('wn-pot-title', `Your investment portfolio, age ${p.now} → ${p.end}`);
  const ages = r.portfolioGrowth.map(x => x.age);
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
        { label: 'You put in', data: r.portfolioGrowth.map(x => Math.round(x.put)), backgroundColor: 'rgba(184,178,166,.9)', stack: 'pot' },
        ...ASSETS.map(a => ({ label: `${a.name} growth`, data: r.portfolioGrowth.map(x => Math.round(x[a.key])), backgroundColor: a.color, stack: 'pot' })),
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
      scales: { x: { grid, ticks: { font: mono, maxTicksLimit: 10 } }, y: { grid, ticks: { callback: fmt, font: mono } } },
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

// Show a location: active pill, status badge and the currency in every '(EUR)' label
function setLocation(loc) {
  _loc = LOCS[loc] ? loc : 'europe';
  document.querySelectorAll('#wn-loc .pill').forEach(b => {
    const on = b.dataset.loc === _loc;
    b.classList.toggle('active', on);
    b.setAttribute('aria-pressed', String(on));
  });
  const sec = document.getElementById('sec-what-i-need');
  const ccy = s => s.replace(/\((EUR|INR|USD)\)/, `(${L().ccy})`);
  sec.querySelectorAll('label').forEach(l => { if (/\((EUR|INR|USD)\)/.test(l.textContent)) l.textContent = ccy(l.textContent); });
  sec.querySelectorAll('[aria-label]').forEach(el => el.setAttribute('aria-label', ccy(el.getAttribute('aria-label'))));
  if (!_flash) set('wn-status', statusText());
}
const statusText = () => `${L().name} · ${L().ccy}`;

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
// The page itself is public. Save while signed out (or with an expired token) keeps the plan
// in sessionStorage, goes to Google sign-in and finishes the save on return (index.html
// follows post_login_redirect). Localhost always has the dev token, so this is prod only.
let _lastSaved = null;
let _restored = false;
let _dirty = false;    // user edited the form before the restore GET returned → don't overwrite
function flash(cls, text, ms = 1600) {
  const status = document.getElementById('wn-status');
  clearTimeout(_flash);
  status.className = 'badge ' + cls;
  status.textContent = text;
  if (ms) _flash = setTimeout(() => { _flash = null; status.className = 'badge neu'; status.textContent = statusText(); }, ms);
}
let _devRetried = false;   // local dev: one fresh-token retry per save
async function signInToSave(body) {
  if (isLocalDev()) {
    // force a fresh token (the stored one was just rejected); retry the save once only
    const ok = !_devRetried && await ensureDevToken(true);
    _devRetried = true;
    if (ok) { await savePlan(); _devRetried = false; return; }
    flash('neu', 'Dev token error — check /auth/token', 2400); return;
  }
  sessionStorage.removeItem('auth_token');
  sessionStorage.setItem(PENDING_KEY, JSON.stringify({ location: _loc, inputs: JSON.parse(body) }));
  sessionStorage.setItem('post_login_redirect', window.location.href);
  flash('neu', 'Sign in to save…', 0);
  window.location.href = '/auth/google/login';
}

export function hasPendingSave() {
  return !!sessionStorage.getItem(PENDING_KEY);
}

let _saving = false;   // one Save at a time — a double click must not write two history rows
async function savePlan() {
  if (!_restored || _saving) return;
  _saving = true;
  try {
    if (!(await calculate())) return;    // invalid inputs: the badge already shows why
    const p = readInputs();
    const body = JSON.stringify(p);
    const token = sessionStorage.getItem('auth_token');
    if (!token) { signInToSave(body); return; }
    const key = _loc + ':' + body;
    if (key === _lastSaved) { flash('ok', 'Already saved'); return; }
    // fetch, not apiFetch: a 401 (expired session) must be told apart from other errors
    let res = null;
    try {
      const r = await fetch(apiBase() + SAVE_PATH + '?location=' + _loc, {
        method: 'PUT', body,
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      });
      if (r.status === 401) { signInToSave(body); return; }
      if (r.ok) res = await r.json();
    } catch (e) {
      // network error → "Could not save" below
    }
    if (res && res.saved) { _lastSaved = key; flash('ok', 'Saved'); }
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
    status.textContent = ((e && e.message) || 'Could not calculate — try again').replace(/€/g, L().sym);
    return false;
  }
  if (seq !== _seq || !r) return false;  // stale response — drop it
  render(p, r);
  flash('ok', 'Updated', 1200);
  return true;
}

// Location pill: load the user's saved plan for that location, else its preset, and recalculate
let _locSeq = 0;
async function switchLocation(loc) {
  if (!_restored || loc === _loc || !LOCS[loc]) return;
  const seq = ++_locSeq;
  const prev = _loc;
  setLocation(loc);
  try {
    const token = sessionStorage.getItem('auth_token');
    const plan = await apiFetch(PLAN_PATH + '?location=' + loc, token ? { headers: { 'Authorization': `Bearer ${token}` } } : {});
    if (seq !== _locSeq) return;         // a newer switch is in flight
    if (!plan || !plan.inputs) throw new Error('no plan');
    writeInputs(plan.inputs);
    if (plan.saved) _lastSaved = _loc + ':' + JSON.stringify(readInputs());
  } catch (e) {
    if (seq !== _locSeq) return;
    setLocation(prev);                   // form still holds the previous location's plan
    flash('neu', 'Could not load ' + LOCS[loc].name + ' — try again', 2400);
    return;
  }
  await calculate();
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
    document.querySelectorAll('#wn-loc .pill').forEach(btn => btn.addEventListener('click', () => switchLocation(btn.dataset.loc)));
    document.querySelectorAll('#wn-h2-mode .pill').forEach(btn => btn.addEventListener('click', () => {
      if (!_restored) _dirty = true;
      document.querySelectorAll('#wn-h2-mode .pill').forEach(b => {
        b.classList.toggle('active', b === btn);
        b.setAttribute('aria-pressed', String(b === btn));
      });
      calculate();
    }));
  }
  let resumeSave = false;
  if (!_loaded) {
    _loaded = true;
    // Restore the saved plan (or the default location's preset); on any error keep the HTML defaults.
    // A plan kept for sign-in (Save while signed out) wins and is saved once signed in.
    const pending = sessionStorage.getItem(PENDING_KEY);
    sessionStorage.removeItem(PENDING_KEY);
    try {
      const token = sessionStorage.getItem('auth_token');
      const plan = await apiFetch(PLAN_PATH, token ? { headers: { 'Authorization': `Bearer ${token}` } } : {});
      if (plan && plan.inputs && !_dirty) {
        setLocation(plan.location);
        writeInputs(plan.inputs);
        if (plan.saved) _lastSaved = _loc + ':' + JSON.stringify(readInputs());
      }
      if (pending && !_dirty) {
        const kept = JSON.parse(pending);   // { location, inputs }; older tabs kept the bare inputs
        if (kept.inputs) setLocation(kept.location);
        writeInputs(kept.inputs || kept);
        resumeSave = !!token;            // sign-in cancelled → plan stays on screen, not saved
      }
    } catch (e) {
      // keep HTML defaults
    } finally {
      _restored = true;
    }
  }
  if (resumeSave) await savePlan();      // recalculates, then saves
  else await calculate();
}
