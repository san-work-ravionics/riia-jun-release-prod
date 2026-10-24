// ── Invest Game App — What I Need (F43 Phase 0 mock) ─────────────────────────
// Calculated in the browser for UI review only. Phase 1 replaces calc() with
// POST /api/experience/invest-game/retirement-plan (backend is the source of truth).
import { mkChart, C } from '../shared/charts.js';

const START_YEAR = new Date().getFullYear();
const AGE_PANELS = [55, 60, 65, 70, 75, 80, 85];
const MAX_AGE = 120;   // corpus run-out is followed past plan-until up to this age

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

function validate(p) {
  if (Object.values(p).some(v => typeof v === 'number' && !isFinite(v))) return 'Fill in every field';
  const events = [...p.sv, ...p.bx];
  if (events.some(x => !isFinite(x.age) || !isFinite(x.amt))) return 'Fill in every one time event (use 0 for none)';
  if (events.some(x => x.amt < 0)) return 'One time amounts must be 0 or more (the sign is fixed)';
  if (events.some(x => x.amt > 0 && x.age < p.now)) return 'One time event age must be from current age on';
  if (!(p.ret > p.now)) return 'Retirement must be after current age';
  if (!(p.end > p.ret)) return 'Plan until must be after retirement';
  if (!(p.hSell > p.now)) return 'House value-until age must be after current age';
  if (p.need <= 0 || p.tax < 0 || p.tax >= 1) return 'Check monthly need and tax %';
  if (p.partial < 0 || p.partial > 1) return 'Partial profit must be 0–100%';
  if (!(p.exit >= p.ret)) return 'Exit age must be from retirement age on';
  if (ASSETS.some(a => p[a.key + 'Monthly'] < 0)) return 'Monthly investments must be 0 or more';
  if (p.hValue < 0 || p.h2Price < 0 || p.hTax < 0 || p.hTax >= 1) return 'Check house values and tax %';
  return null;
}

// Future value of 1/month for k months at annual rate r (monthly compounding)
function fvFactor(r, k) {
  const m = Math.pow(1 + r, 1 / 12) - 1;
  return m === 0 ? k : (Math.pow(1 + m, k) - 1) / m;
}

// Month by month from current age to plan-until (the flow):
//  1. before retirement every monthly investment goes in and stays 100% invested; it stops at retirement;
//  2. from retirement, each month the partial profit % of that month's profit is withdrawn and, after
//     tax, is the monthly available; the rest of the profit is re-invested, split over the assets by the
//     selected monthly amounts (the corpus is not sold before the exit age);
//  3. one time events (+ in, − out) and the house release (sale − new house) go into a separate pot
//     of additional money at the start of their year;
//  4. the monthly need (from retirement) is paid from the monthly available first, then from that pot.
//  5. from the exit age nothing is re-invested (all of the profit is withdrawn) and, whenever the pot is below zero (the money falls short of the need), invested
//     money is sold to bring the pot back to zero — spread over the assets by balance, tax on the gain
//     part of what is sold — until the corpus is used up (corpusOut). The run carries on past plan-until
//     (need still rising, nothing recorded) only to find the exact corpusOut age, up to MAX_AGE.
// It is sustainable while the pot stays at or above zero. With `invest` false (no investment) the
// same monthly amounts are saved straight into the pot at 0% and nothing is withdrawn.
function simulate(p, assets, houseRelease, invest = true) {
  const mRate = assets.map(a => Math.pow(1 + a.rate, 1 / 12) - 1);
  const bal = assets.map(() => 0), basis = assets.map(() => 0);
  let pot = 0, runOut = null, corpusOut = null;
  const points = [];
  const sum = arr => arr.reduce((s, v) => s + v, 0);
  // Share of the corpus that is gain, and what €1 sold brings after tax
  const netPerEuro = () => { const b = sum(bal); return b > 0 ? 1 - p.tax * Math.max(0, b - sum(basis)) / b : 0; };
  const sellCorpus = age => {
    const b = sum(bal);
    if (!invest || age < p.exit || pot >= 0 || b <= 0) return 0;
    const net = netPerEuro(), gross = Math.min(b, -pot / net), keep = 1 - gross / b;
    bal.forEach((_, i) => { bal[i] *= keep; basis[i] *= keep; });
    pot += gross * net;
    if (corpusOut === null && sum(bal) < 1) corpusOut = age;
    return gross * net;
  };
  // share of the profit withdrawn: partial % from retirement, all of it from the exit age
  const share = age => (age >= p.exit ? 1 : age >= p.ret ? p.partial : 0);
  // re-invested profit is split by the selected monthly amounts (own asset if they are all 0)
  const total = sum(assets.map(a => a.monthly));
  const split = assets.map(a => (total > 0 ? a.monthly / total : null));
  const incomeNow = age => (invest ? sum(bal.map((b, i) => b * mRate[i])) * share(age) * (1 - p.tax) : 0);
  for (let age = p.now; age <= MAX_AGE; age++) {
    const past = age > p.end;
    if (past && (!invest || corpusOut !== null)) break;
    const events = [];
    if (age === p.hSell && p.h2Mode !== 'same') { pot += houseRelease; events.push(`house ${fmt(houseRelease)}`); }
    const svIn = p.sv.reduce((s, x) => s + (x.amt > 0 && x.age === age ? x.amt : 0), 0);
    if (svIn > 0) { pot += svIn; events.push(`one time +${fmt(svIn)}`); }
    const bxOut = p.bx.reduce((s, x) => s + (x.amt > 0 && x.age === age ? x.amt : 0), 0);
    if (bxOut > 0) { pot -= bxOut; events.push(`one time −${fmt(bxOut)}`); }
    sellCorpus(age);
    if (runOut === null && !past && pot < -0.5) runOut = age;
    const income = incomeNow(age);
    const need = age >= p.ret ? p.need * Math.pow(1 + p.infl, age - p.now) : 0;
    if (!past) points.push({ age, pot, corpus: sum(bal), putIn: sum(basis), bal: [...bal], basis: [...basis], income, need, events });
    // corpus sold during the year to cover the monthly need (not the debt cleared at the start of the year)
    let soldYear = 0;
    for (let m = 0; m < 12; m++) {
      if (age < p.ret) {
        assets.forEach((a, i) => {
          if (invest) { bal[i] = bal[i] * (1 + mRate[i]) + a.monthly; basis[i] += a.monthly; }
          else pot += a.monthly;
        });
        continue;
      }
      let withdrawn = 0;
      if (invest) {
        const profits = bal.map((b, i) => b * mRate[i]), profit = sum(profits);
        withdrawn = profit * share(age);
        const kept = profit - withdrawn;
        bal.forEach((_, i) => { bal[i] += split[i] === null ? profits[i] * (1 - share(age)) : kept * split[i]; });
      }
      pot += withdrawn * (1 - p.tax) - need;
      soldYear += sellCorpus(age);
      if (runOut === null && age < p.end && pot < -0.5) runOut = age;
    }
    if (!past) points[points.length - 1].sold = soldYear;
  }
  return { points, runOut, corpusOut };
}

function calc(p) {
  // Need: plain sum of inflated spend, retirement → plan-until (start of each year)
  const years = [];
  let total = 0;
  for (let a = p.ret; a < p.end; a++) {
    const monthly = p.need * Math.pow(1 + p.infl, a - p.now);
    total += monthly * 12;
    years.push({ age: a, year: START_YEAR + a - p.now, monthly, cum: total });
  }

  // House: current house grows to the sell age, tax on the gain. Continuing in the same
  // house releases nothing; buying a new one releases net sale − new price at that age.
  const hYears = p.hSell - p.now;
  const hValueAt = p.hValue * Math.pow(1 + p.hAppr, hYears);
  const hGain = Math.max(0, hValueAt - p.hValue);
  const hTaxAmt = hGain * p.hTax;
  const hNet = hValueAt - hTaxAmt;
  const h2At = p.h2Price * Math.pow(1 + p.hAppr, hYears);
  const houseRelease = p.h2Mode === 'same' ? 0 : hNet - h2At;
  // One time events, taken at the amount entered for that age: + in, − out
  const bigExpenses = p.bx.reduce((s, x) => s + x.amt, 0);
  const savings = p.sv.reduce((s, x) => s + x.amt, 0);
  const target = Math.max(0, total + bigExpenses - savings - houseRelease);

  // Investments at retirement, per asset: corpus built from monthly amounts; the first month after
  // retirement earns `profitM`, of which the partial % is withdrawn → `withdrawnNet` after tax.
  const payMonths = (p.ret - p.now) * 12;
  const assets = ASSETS.map(a => {
    const monthly = p[a.key + 'Monthly'], rate = p[a.key + 'Rate'];
    const put = monthly * payMonths;
    const value = monthly * fvFactor(rate, payMonths);
    const profitM = value * (Math.pow(1 + rate, 1 / 12) - 1);
    return { ...a, monthly, rate, put, value, gain: Math.max(0, value - put), profitM,
      withdrawnNet: profitM * p.partial * (1 - p.tax) };
  });
  const sum = k => assets.reduce((s, a) => s + a[k], 0);
  const monthly = sum('monthly'), put = sum('put'), value = sum('value');

  const portfolio = simulate(p, assets, houseRelease);
  const portfolio0 = simulate(p, assets, houseRelease, false);
  // Investment pot chart, current age → plan-until: put in stops at retirement, growth keeps the
  // part of the profit that is not withdrawn
  const pot = portfolio.points.map(x => {
    const row = { age: x.age, put: x.putIn };
    assets.forEach((a, i) => { row[a.key] = x.bal[i] - x.basis[i]; });
    return row;
  });
  const needAll = total + bigExpenses;
  const needRet = years[0].monthly;
  // Monthly available at an age = investing (that month's withdrawal after tax; 0 before retirement)
  // + pot (the pot of additional money at that age — one time events and house release so far, after
  // living on the need until then — spread to plan-until, rising with inflation like the need; a pot
  // below zero is a debt that comes off). Later events count from their own age on. At plan-until the
  // pot is spread over 12 months.
  const at = age => {
    const x = portfolio.points.find(y => y.age === age);
    let months = 0;
    for (let a = age; a < Math.max(p.end, age + 1); a++) months += 12 * Math.pow(1 + p.infl, a - age);
    const fromPot = x.pot / months;
    const need = p.need * Math.pow(1 + p.infl, age - p.now);
    // investing = profit withdrawal after tax + (from the exit age) corpus sold to cover the need
    const income = x.income + x.sold / 12;
    const monthly = Math.max(0, income + fromPot);
    return { age, monthly, income, fromPot, pot: x.pot, corpus: x.corpus, need, share: monthly / need };
  };
  const byAge = AGE_PANELS.map(age => (age >= p.now && age <= p.end ? at(age) : { age, off: true }));
  const atRet = at(p.ret);
  return { years, total, assets, monthly, put, value, pot, portfolio, portfolio0,
    hValueAt, hGain, hTaxAmt, hNet, h2At, houseRelease, bigExpenses, savings, target, needAll,
    needRet, byAge, atRet };
}

// How long it is sustainable: 'Sustainable until 71' or 'Sustainable beyond 85'
function outcome(p, port) {
  return port.runOut === null ? `Sustainable beyond ${p.end}` : `Sustainable until ${port.runOut}`;
}
// Where the invested corpus finishes once it is sold from the exit age on
function corpusOutcome(p, port) {
  return port.corpusOut === null ? `Corpus never runs out (still growing at ${MAX_AGE})` : `Corpus runs out at ${port.corpusOut}`;
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
          footer: i => { const x = pts[i[0].dataIndex]; return [x.income ? `monthly available ${fmt(x.income)}` : '', x.need ? `need ${fmt(x.need)}` : '', ...x.events].filter(Boolean).join(' · '); },
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
  fb.innerHTML = `Monthly available at ${c0.age}: <b>${fmt(c0.monthly)}</b> of ${fmt(c0.need)} needed (<b>${pct(c0.share)}</b>) · ${outcome(p, r.portfolio)} · ${corpusOutcome(p, r.portfolio)}`;
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

let _flash = null;
function calculate() {
  const p = readInputs();
  const err = validate(p);
  const status = document.getElementById('wn-status');
  clearTimeout(_flash);
  if (err) {
    status.className = 'badge neu';
    status.textContent = err;
    return;
  }
  render(p, calc(p));
  status.className = 'badge ok';
  status.textContent = 'Updated';
  _flash = setTimeout(() => { status.className = 'badge neu'; status.textContent = 'Europe · EUR'; }, 1200);
}

let _bound = false;
export function loadWhatINeed() {
  if (!_bound) {
    _bound = true;
    ['wn-calc', 'wn-i-calc', 'wn-h-calc', 'wn-h2-calc', 'wn-bx-calc'].forEach(id => document.getElementById(id).addEventListener('click', calculate));
    // Enter in any field recalculates too
    document.getElementById('sec-what-i-need').addEventListener('keydown', e => {
      if (e.key === 'Enter' && e.target.tagName === 'INPUT') { e.preventDefault(); calculate(); }
    });
    document.querySelectorAll('#wn-h2-mode .pill').forEach(btn => btn.addEventListener('click', () => {
      document.querySelectorAll('#wn-h2-mode .pill').forEach(b => {
        b.classList.toggle('active', b === btn);
        b.setAttribute('aria-pressed', String(b === btn));
      });
      calculate();
    }));
  }
  calculate();
}
