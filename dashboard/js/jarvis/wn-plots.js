// Jarvis — What I Need: plan-vs-reality line charts.  One for the overall portfolio, one for the investment,
// then one card per investment type (planned path with each held instrument's expected path, and the bucket's
// cumulative target vs actual by month).  Ages run from the start age to the retirement age; milestones are
// marked every 5 years and at retirement.
import { mkChart, destroyChart, C } from '../shared/charts.js';
import { esc } from './esc.js?v=3';
import { t } from './copy.js?v=13';
import { fmtDate, fmtMoney, fmtNum, isNum } from './format.js?v=3';
import { isMilestone } from './wn-model.js?v=2';

const BUCKET_KEYS = ['idx', 'eq', 'com', 'alt'];
const PALETTE = [C.run, C.mon, C.warn, C.build, C.t4];
let _ids = [];

export function clearPlots() {
  _ids.forEach(destroyChart);
  _ids = [];
  const box = document.getElementById('jv-wn-plots');
  if (box) box.innerHTML = '';
}

const _ds = (label, data, color, extra = {}) => ({
  label, data, borderColor: color, backgroundColor: 'transparent', borderWidth: 2, tension: 0.2, spanGaps: true,
  pointRadius: 0, pointBackgroundColor: color, ...extra,
});

// markers on milestone ages only
function _milestoneRadius(ages, now, ret) {
  return ages.map(a => (isMilestone(a, now, ret) ? 5 : 0));
}

function _cfg(labels, datasets, yFmt) {
  return {
    type: 'line',
    data: { labels, datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { position: 'bottom', labels: { font: { family: C.mono, size: 10 }, boxWidth: 12 } },
        tooltip: { callbacks: { label: ctx => `${ctx.dataset.label}: ${isNum(ctx.raw) ? yFmt(ctx.raw) : '—'}` } },
      },
      scales: {
        x: { grid: { display: false }, ticks: { font: { family: C.mono, size: 9 }, maxRotation: 0, autoSkip: true } },
        y: { grid: { color: 'rgba(0,0,0,.05)' }, ticks: { font: { family: C.mono, size: 10 }, callback: v => yFmt(v) } },
      },
    },
  };
}

// RITA chart card: .chart-wrap + .chart-title + short .chart-box
function _card(title, sub, bodyHtml) {
  return `<div class="chart-wrap" style="margin-bottom:0"><div class="chart-title">${esc(title)} `
    + `<span style="font-weight:400;color:var(--t3);font-size:11px">${esc(sub)}</span></div>${bodyHtml}</div>`;
}

const _canvas = (id, h = 165) => `<div class="chart-box" style="height:${h}px"><canvas id="${id}"></canvas></div>`;

// chips: the planned value at each milestone age
function _milestones(ages, values, now, ret, ccy) {
  const chips = ages.map((a, i) => (isMilestone(a, now, ret) && isNum(values[i])
    ? `<span class="jv-hold-chip"><b class="mono">${esc(t('wn.plot.age', { age: a }))}</b> ${esc(fmtMoney(values[i], ccy))}</span>` : ''))
    .filter(Boolean).join('');
  return chips ? `<div class="jv-hold-chips" style="margin-top:8px">${chips}</div>` : '';
}

// actual today as a single marker at the start age
function _actualDataset(ages, now, actualNow) {
  return _ds(t('wn.plot.actual'), ages.map(a => (a === now && isNum(actualNow) ? actualNow : null)), C.build,
    { showLine: false, pointStyle: 'triangle', pointRadius: 8 });
}

function _draw(id, cfg) {
  _ids.push(id);
  mkChart(id, cfg);
}

export function renderPlots(series, { ccy, actualNow }) {
  clearPlots();
  const box = document.getElementById('jv-wn-plots');
  if (!box || !series) return;
  const { now, ret } = series;
  const money = v => fmtMoney(v, ccy);
  const sub = t('wn.plot.sub', { from: now, to: ret });
  const draws = [];
  let top = '';
  let types = '';

  // 1. overall portfolio
  const o = series.overall;
  if (o.ages.length) {
    top += _card(t('wn.plot.overall'), sub, _canvas('jv-wn-plot-overall') + _milestones(o.ages, o.planned, now, ret, ccy));
    draws.push(() => _draw('jv-wn-plot-overall', _cfg(o.ages, [
      _ds(t('wn.plot.planned'), o.planned, C.run, { pointRadius: _milestoneRadius(o.ages, now, ret) }),
      _ds(t('wn.plot.savings'), o.savings, C.t4, { borderDash: [5, 4] }),
      _actualDataset(o.ages, now, actualNow),
    ], money)));
  }

  // 2. the investment (all investment types together) against the money put in
  const iv = series.invest;
  if (iv.ages.length) {
    top += _card(t('wn.plot.invest'), sub, _canvas('jv-wn-plot-invest') + _milestones(iv.ages, iv.value, now, ret, ccy));
    draws.push(() => _draw('jv-wn-plot-invest', _cfg(iv.ages, [
      _ds(t('wn.plot.value'), iv.value, C.mon, { pointRadius: _milestoneRadius(iv.ages, now, ret) }),
      _ds(t('wn.plot.put_in'), iv.putIn, C.t4, { borderDash: [5, 4] }),
      _actualDataset(iv.ages, now, actualNow),
    ], money)));
  }

  // 3. one card per investment type: planned path + each instrument's expected path, then target vs actual by month
  for (const key of BUCKET_KEYS) {
    const b = series.buckets[key];
    if (!b || !b.ages.length || !b.planned.some(v => isNum(v) && v > 0)) continue;
    const idLeft = `jv-wn-plot-${key}`;
    const idRight = `jv-wn-plot-${key}-m`;
    const monthly = b.monthly.length
      ? `<div class="card-sub" style="margin:8px 0 4px">${esc(t('wn.plot.monthly_title'))}</div>${_canvas(idRight, 130)}`
      : `<p class="jv-muted" style="margin-top:8px">${esc(t('wn.plot.no_monthly'))}</p>`;
    types += _card(t(`wn.label.${key}`), sub, _canvas(idLeft) + monthly + _milestones(b.ages, b.planned, now, ret, ccy));
    draws.push(() => {
      const sets = [_ds(t('wn.plot.planned'), b.planned, C.run, { pointRadius: _milestoneRadius(b.ages, now, ret) })];
      b.instruments.forEach((inst, i) => sets.push(
        _ds(`${inst.id} ${t('wn.plot.expected')}`, inst.values, PALETTE[(i + 1) % PALETTE.length], { borderWidth: 1.5, borderDash: [3, 3] })));
      _draw(idLeft, _cfg(b.ages, sets, money));
      if (b.monthly.length) {
        const pct = v => `${fmtNum(v, 1)}%`;
        _draw(idRight, _cfg(b.monthly.map(m => fmtDate(m.month)), [
          _ds(t('wn.plot.target_cum'), b.monthly.map(m => m.target), C.run, { borderDash: [5, 4] }),
          _ds(t('wn.plot.actual_cum'), b.monthly.map(m => m.actual), C.build, { pointRadius: 3 }),
        ], pct));
      }
    });
  }

  box.innerHTML = (top ? `<div class="card-row-2">${top}</div>` : '') + (types ? `<div class="card-row-2">${types}</div>` : '');
  draws.forEach(d => d());
}
