// Jarvis — What I Need: pure data shaping (no DOM, no fetch).  The page is the OVERALL view: every region has
// its own saved plan (its own inflation, risk and return assumptions, in its own currency) and its own
// instruments; here each region is measured against its own plan and the regions are then added together in EUR.
import { fmtMoney, fmtPctPoint, isNum, locationName } from './format.js?v=3';
import { t } from './copy.js?v=19';

export const LOC_KEYS = ['europe', 'india', 'us'];

// field = geography-overview return field for the period (percent points); days = trading days in it.
export const PERIODS = {
  daily:   { days: 1,  field: 'daily_return_pct' },
  weekly:  { days: 5,  field: 'return_1w_pct' },
  monthly: { days: 21, field: 'return_1m_pct' },
};
const TRADING_DAYS = 252;
const BUCKETS = ['idx', 'eq', 'com', 'alt'];
const REGION_ORDER = ['India', 'US', 'EU', 'Other'];      // as the RITA Overview

const _id = v => String(v).toUpperCase();

// ── the regions that have a saved plan ───────────────────────────────────────────

// plans / calcs / pfs: keyed by location.  plans[loc] = A7 response, calcs[loc] = calculate `base` scenario,
// pfs[loc] = A5 portfolio.  A region without a saved plan (or whose calculation failed) is not included.
export function buildRegionPlans(plans, calcs, pfs) {
  return LOC_KEYS
    .filter(l => plans[l] && plans[l].plan && plans[l].plan.saved && calcs[l] && calcs[l].result)
    .map(loc => {
      const p = plans[loc];
      const pf = (pfs && pfs[loc]) || null;
      return {
        loc, plan: p.plan, breakdowns: p.bucketBreakdown || [], base: calcs[loc], pf,
        ccy: p.plan.currency || (pf && pf.currency) || 'EUR',                  // the plan's amounts
        pfCcy: (pf && pf.perf && pf.perf.money && pf.perf.money.currency) || (pf && pf.currency) || p.plan.currency || 'EUR',
      };
    });
}

// EUR value of a region's portfolio today (null when unknown or no FX rate); fx(value, ccy) -> EUR | null
export function regionValueEur(rp, fx) {
  const v = rp.pf && rp.pf.perf && rp.pf.perf.money ? rp.pf.perf.money.value_now : null;
  return isNum(v) ? fx(v, rp.pfCcy) : null;
}

// ── held instruments (all regions) ───────────────────────────────────────────────

// One row per held instrument, each carrying ITS REGION'S bucket target (that region's plan).  targetRate / ytd
// are fractions.  An instrument held in two regions is listed once (first region wins).
export function heldInstruments(plans) {
  const out = [];
  const seen = new Set();
  for (const loc of LOC_KEYS) {
    const p = plans && plans[loc];
    if (!p || !p.plan || !p.plan.saved) continue;
    for (const b of p.bucketBreakdown || []) {
      for (const h of b.instruments || []) {
        const id = _id(h.instrumentId);
        if (seen.has(id)) continue;
        seen.add(id);
        out.push({
          id, loc, bucket: b.key, targetRate: b.targetRate, atRisk: b.atRisk === undefined ? null : b.atRisk,
          ytd: isNum(h.ytdReturn) ? h.ytdReturn : null, alloc: isNum(h.allocationPct) ? h.allocationPct : null,
        });
      }
    }
  }
  return out;
}

// ── regions with instruments ─────────────────────────────────────────────────────

export function regionModel(geoList, held) {
  const heldById = new Map(held.map(h => [h.id, h]));
  const byRegion = new Map(REGION_ORDER.map(r => [r, []]));
  const placed = new Set();
  const tile = (id, name, close, h) => ({
    id, name, close: isNum(close) ? close : null, held: !!h,
    target: h ? h.targetRate : null, achieved: h ? h.ytd : null, atRisk: h ? h.atRisk : null,
  });
  for (const g of geoList || []) {
    const id = _id(g.id);
    placed.add(id);
    byRegion.get(byRegion.has(g.region) ? g.region : 'Other').push(tile(id, g.name || id, g.close, heldById.get(id)));
  }
  for (const h of held) if (!placed.has(h.id)) byRegion.get('Other').push(tile(h.id, h.id, null, h));
  return REGION_ORDER
    .map(region => ({
      region,
      tiles: byRegion.get(region).sort((a, b) => (Number(b.held) - Number(a.held)) || a.name.localeCompare(b.name)),
    }))
    .filter(r => r.tiles.length);
}

// ── Daily / Weekly / Monthly: the 8 panels ───────────────────────────────────────

const _sign = v => (!isNum(v) ? '' : v >= 0 ? 'pos' : 'neg');

// held: heldInstruments(); geoList: allInstruments(geo); period: daily|weekly|monthly;
// regionWeight: { loc: EUR value of that region's portfolio } so a big region counts more than a small one
// (instruments are weighted by their allocation inside the region).  Returns 8 panels {id, label, value, sub, cls}.
export function periodPanels(held, geoList, period, regionWeight = {}) {
  const cfg = PERIODS[period] || PERIODS.daily;
  const geoById = new Map((geoList || []).map(g => [_id(g.id), g]));
  const mine = held.map(h => {
    const g = geoById.get(h.id);
    return {
      ...h,
      ret: g && isNum(g[cfg.field]) ? g[cfg.field] : null,                       // percent points
      target: isNum(h.targetRate) ? (h.targetRate * 100 * cfg.days) / TRADING_DAYS : null,
    };
  });
  const measured = mine.filter(h => isNum(h.ret) && isNum(h.target));
  const useAlloc = measured.length > 0 && measured.every(h => isNum(h.alloc) && h.alloc > 0);
  const useRegion = useAlloc && measured.every(h => isNum(regionWeight[h.loc]) && regionWeight[h.loc] > 0);
  const wt = h => (useAlloc ? h.alloc * (useRegion ? regionWeight[h.loc] : 1) : 1);
  const den = measured.reduce((s, h) => s + wt(h), 0);
  const avg = f => (den > 0 ? measured.reduce((s, h) => s + wt(h) * f(h), 0) / den : null);

  const ret = avg(h => h.ret);
  const target = avg(h => h.target);
  const gap = isNum(ret) && isNum(target) ? ret - target : null;
  const ranked = measured.slice().sort((a, b) => b.ret - a.ret);
  const best = ranked[0];
  const worst = ranked[ranked.length - 1];
  const ahead = measured.filter(h => h.ret >= h.target).length;
  const buckets = new Map();
  mine.forEach(h => { if (h.atRisk === true || h.atRisk === false) buckets.set(`${h.loc}:${h.bucket}`, h.atRisk); });
  const nRisk = [...buckets.values()].filter(Boolean).length;

  return [
    { id: 'ret',    label: t('wn.panel.ret'),    value: fmtPctPoint(ret, 2),    sub: t('wn.panel.sub.weighted'), cls: _sign(ret) },
    { id: 'target', label: t('wn.panel.target'), value: fmtPctPoint(target, 2), sub: t('wn.panel.sub.prorated'), cls: '' },
    { id: 'gap',    label: t('wn.panel.gap'),    value: fmtPctPoint(gap, 2),    sub: t('wn.panel.sub.gap'), cls: _sign(gap) },
    { id: 'status', label: t('wn.panel.status'),
      value: gap === null ? t('wn.panel.nodata') : gap >= 0 ? t('wn.panel.on_track') : t('wn.panel.behind'),
      sub: t('wn.panel.sub.measured', { n: measured.length, m: mine.length }), cls: _sign(gap) },
    { id: 'best',   label: t('wn.panel.best'),   value: best ? fmtPctPoint(best.ret) : '—',   sub: best ? best.id : '',   cls: best ? _sign(best.ret) : '' },
    { id: 'worst',  label: t('wn.panel.worst'),  value: worst ? fmtPctPoint(worst.ret) : '—', sub: worst ? worst.id : '', cls: worst ? _sign(worst.ret) : '' },
    { id: 'ahead',  label: t('wn.panel.ahead'),
      value: measured.length ? `${ahead} / ${measured.length}` : '—', sub: t('wn.panel.sub.holdings'),
      cls: measured.length ? (ahead * 2 >= measured.length ? 'pos' : 'neg') : '' },
    { id: 'risk',   label: t('wn.panel.risk'),
      value: buckets.size ? `${nRisk} / ${buckets.size}` : '—', sub: t('wn.panel.sub.ytd'),
      cls: buckets.size ? (nRisk === 0 ? 'pos' : 'neg') : '' },
  ];
}

// ── Agent commentary (deterministic, from the same numbers) ──────────────────────

// regions: buildRegionPlans(); fx(value, ccy) -> EUR | null.
export function commentaryText({ regions, held, fx }) {
  const lines = [];
  const names = regions.map(r => locationName(r.loc)).join(', ');
  const atRet = regions.map(r => fx(r.base.waterfall && r.base.waterfall.portfolioValue, r.ccy));
  const known = atRet.filter(isNum);
  lines.push(t('wn.comm.overall', {
    n: regions.length, regions: names, holdings: held.length,
    value: known.length ? fmtMoney(known.reduce((s, v) => s + v, 0), 'EUR') : '—',
  }));
  if (!held.length) {
    lines.push(t('wn.comm.no_holdings'));
    return lines.join('\n');
  }
  for (const r of regions) {
    const name = locationName(r.loc);
    const measured = r.breakdowns.filter(b => b.atRisk === true || b.atRisk === false);
    if (!measured.length) { lines.push(t('wn.comm.region_nodata', { region: name })); continue; }
    const risk = measured.filter(b => b.atRisk === true);
    lines.push(risk.length
      ? t('wn.comm.region_risk', { region: name, n: risk.length, m: measured.length, names: risk.map(b => t(`wn.label.${b.key}`)).join(', ') })
      : t('wn.comm.region_ok', { region: name, m: measured.length }));
  }
  const noFx = [...new Set(regions.filter(r => fx(1, r.ccy) === null).map(r => r.ccy))];
  if (noFx.length) lines.push(t('wn.comm.no_fx', { ccys: noFx.join(', ') }));
  return lines.join('\n');
}

// ── Plots: every region's own plan, added together in EUR, start age → retirement age ──

export function isMilestone(age, now, ret) {
  return age === now || age === ret || (isNum(now) && (age - now) % 5 === 0);
}

// Regions without an FX rate are left out (listed in `skipped`).  Ages are the ones every included plan covers.
export function combinedSeries(regions, fx) {
  const usable = regions.filter(r => fx(1, r.ccy) !== null
    && isNum(r.plan.inputs.now) && isNum(r.plan.inputs.ret) && r.base.result);
  const skipped = regions.filter(r => !usable.includes(r)).map(r => r.loc);
  if (!usable.length) return null;

  const rows = usable.map(r => {
    const res = r.base.result;
    return {
      r,
      growth: new Map((res.portfolioGrowth || []).map(g => [g.age, g])),
      pts: new Map(((res.withInvesting && res.withInvesting.points) || []).map(p => [p.age, p])),
    };
  });
  const from = Math.max(...usable.map(r => r.plan.inputs.now));
  const to = Math.min(...usable.map(r => r.plan.inputs.ret));
  const ages = [];
  for (let a = from; a <= to; a += 1) if (rows.every(x => x.growth.has(a) && x.pts.has(a))) ages.push(a);
  if (!ages.length) return null;

  const eur = (v, x) => { const e = fx(v, x.r.ccy); return isNum(e) ? e : 0; };
  const sum = f => ages.map(a => rows.reduce((s, x) => s + eur(f(x, a), x), 0));

  const buckets = {};
  for (const key of BUCKETS) {
    const instruments = [];
    const monthlyRegions = [];
    for (const x of rows) {
      const b = x.r.breakdowns.find(k => k.key === key);
      if (!b) continue;
      const insts = (b.instruments || []).filter(i => isNum(i.allocationPct) && i.allocationPct > 0);
      const total = insts.reduce((s, i) => s + i.allocationPct, 0);
      // each held instrument's expected path = its allocation share of this region's bucket plan value
      for (const i of insts) {
        instruments.push({
          id: _id(i.instrumentId), loc: x.r.loc,
          values: ages.map(a => eur(x.growth.get(a)[key] * (i.allocationPct / total), x)),
        });
      }
      if ((b.monthly || []).length) {
        monthlyRegions.push({
          loc: x.r.loc,
          months: b.monthly.map(m => m.month),
          target: b.monthly.map(m => (isNum(m.target) ? m.target * 100 : null)),
          actual: b.monthly.map(m => (isNum(m.actual) ? m.actual * 100 : null)),
        });
      }
    }
    buckets[key] = { ages, planned: sum((x, a) => x.growth.get(a)[key]), instruments, monthlyRegions };
  }

  const nowVals = usable.map(r => regionValueEur(r, fx)).filter(isNum);
  return {
    now: ages[0], ret: ages[ages.length - 1], regions: usable.map(r => r.loc), skipped,
    actualNow: nowVals.length ? nowVals.reduce((s, v) => s + v, 0) : null,
    overall: { ages, planned: sum((x, a) => x.pts.get(a).portfolio), savings: sum((x, a) => x.pts.get(a).savings) },
    invest: {
      ages,
      value: sum((x, a) => { const g = x.growth.get(a); return (g.idx || 0) + (g.eq || 0) + (g.com || 0) + (g.alt || 0); }),
      putIn: sum((x, a) => x.growth.get(a).put),
    },
    buckets,
  };
}
