// Jarvis — What I Need: pure data shaping (no DOM, no fetch). Everything the page shows is computed here
// from the A7 responses (one per location), the geography-overview instruments and the plan result.
import { fmtMoney, fmtPctPoint, isNum } from './format.js?v=3';
import { t } from './copy.js?v=13';

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

// ── held instruments (all locations) ────────────────────────────────────────────

// plans: { europe, india, us } = A7 responses (or null).  One row per held instrument; an instrument held
// in two locations is listed once (first location wins).  targetRate / ytd are fractions.
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

// geoList: allInstruments(geo) rows ({id, name, close, region, ...}).  Every instrument of every region is
// listed (as the RITA Overview does); held ones carry the bucket's yearly target and the achieved YTD return.
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

// held: heldInstruments(); geoList: allInstruments(geo); period: daily|weekly|monthly.
// Returns 8 panels {id, label, value, sub, cls} where cls is 'pos' (green) / 'neg' (red) / ''.
export function periodPanels(held, geoList, period) {
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
  const wt = h => (useAlloc ? h.alloc : 1);
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
  mine.forEach(h => { if (h.atRisk === true || h.atRisk === false) buckets.set(h.bucket, h.atRisk); });
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

// breakdowns: the selected location's bucketBreakdown; inp: plan inputs; atRet: result.atRet.
export function commentaryText({ held, breakdowns, inp, atRet, ccy }) {
  const lines = [];
  const mine = held;
  const years = isNum(inp && inp.ret) && isNum(inp && inp.now) ? inp.ret - inp.now : null;
  lines.push(t('wn.comm.intro', {
    n: mine.length, need: fmtMoney(atRet && atRet.monthly, ccy), ret: inp && inp.ret, years,
  }));
  if (!mine.length) {
    lines.push(t('wn.comm.no_holdings'));
    return lines.join('\n');
  }
  const measured = (breakdowns || []).filter(b => b.atRisk === true || b.atRisk === false);
  if (!measured.length) {
    lines.push(t('wn.comm.nodata'));
  } else {
    const risk = measured.filter(b => b.atRisk === true);
    lines.push(risk.length
      ? t('wn.comm.pace_risk', { n: risk.length, m: measured.length, names: risk.map(b => t(`wn.label.${b.key}`)).join(', ') })
      : t('wn.comm.pace_ok', { m: measured.length }));
  }
  return lines.join('\n');
}

// ── Plots: planned trajectories start age → retirement age ───────────────────────

export function isMilestone(age, now, ret) {
  return age === now || age === ret || (isNum(now) && (age - now) % 5 === 0);
}

// result: calculate response `base` (camelCase); breakdowns: bucketBreakdown of the selected location.
export function planSeries(result, inp, breakdowns) {
  const now = inp.now;
  const ret = inp.ret;
  const inRange = r => r.age >= now && r.age <= ret;
  const growth = ((result && result.portfolioGrowth) || []).filter(inRange);
  const pts = ((result && result.withInvesting && result.withInvesting.points) || []).filter(inRange);
  const ages = growth.map(r => r.age);

  const buckets = {};
  for (const key of BUCKETS) {
    const b = (breakdowns || []).find(x => x.key === key);
    const insts = (b && b.instruments) || [];
    const total = insts.reduce((s, i) => s + (isNum(i.allocationPct) && i.allocationPct > 0 ? i.allocationPct : 0), 0);
    buckets[key] = {
      ages,
      planned: growth.map(r => r[key]),
      // each held instrument's expected path = its allocation share of the bucket's planned value
      instruments: total > 0
        ? insts.filter(i => isNum(i.allocationPct) && i.allocationPct > 0).map(i => ({
          id: _id(i.instrumentId), ytd: isNum(i.ytdReturn) ? i.ytdReturn : null,
          values: growth.map(r => r[key] * (i.allocationPct / total)),
        }))
        : [],
      monthly: ((b && b.monthly) || []).map(m => ({
        month: m.month, target: isNum(m.target) ? m.target * 100 : null, actual: isNum(m.actual) ? m.actual * 100 : null,
      })),
    };
  }
  return {
    now, ret,
    overall: { ages: pts.map(p => p.age), planned: pts.map(p => p.portfolio), savings: pts.map(p => p.savings) },
    invest: {
      ages,
      value: growth.map(r => (r.idx || 0) + (r.eq || 0) + (r.com || 0) + (r.alt || 0)),
      putIn: growth.map(r => r.put),
    },
    buckets,
  };
}
