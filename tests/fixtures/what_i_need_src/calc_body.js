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
