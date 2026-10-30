// Jarvis — F44 P4c: Daily / Weekly / Monthly period returns card shown in single-region drill-down.
// KPIs: Actual | Target | Gap | Status (period-scaled from goal_return and geo data).
// Period tabs drive the instrument returns chart and hedge assessment.
import { mkChart, destroyChart, C } from '../shared/charts.js';
import { esc } from './esc.js?v=3';
import { t } from './copy.js?v=3';
import { fmtPctPoint, fmtRate, isNum } from './format.js?v=3';
import { allInstruments } from './regions.js?v=3';

let _period = 'daily';
let _loc = null;
let _pf = null;
let _geo = null;

const DIVISOR = { daily: 252, weekly: 52, monthly: 12 };

function _sign(v) { return isNum(v) ? (v > 0 ? 'pos' : v < 0 ? 'neg' : '') : ''; }

// Held or selected instruments from pf, enriched with geo return fields.
function _portInsts(pf, geo, loc) {
  if (!pf || !pf.instruments) return [];
  const geoById = {};
  for (const i of (geo ? allInstruments(geo) : [])) {
    if (i.loc === loc) geoById[String(i.id).toUpperCase()] = i;
  }
  return pf.instruments
    .filter(r => r.held || r.selected)
    .map(r => {
      const g = geoById[String(r.instrument_id).toUpperCase()] || {};
      return { id: r.instrument_id, w: isNum(r.allocation_pct) ? r.allocation_pct : null,
               daily: g.daily_return_pct ?? null, y1: g.return_1y_pct ?? null };
    });
}

// Weighted average return (in %-point form) for the chosen period.
function _actual(insts, period) {
  let num = 0, den = 0;
  for (const r of insts) {
    if (!isNum(r.w)) continue;
    const v = period === 'monthly' ? (isNum(r.y1) ? r.y1 / 12 : null)
            : (isNum(r.daily) ? (period === 'weekly' ? r.daily * 5 : r.daily) : null);
    if (v === null) continue;
    num += v * r.w;
    den += r.w;
  }
  return den > 0 ? num / den : null;
}

// Target for the period, as %-points (goal_return is a fraction, so × 100 / divisor).
function _target(pf, period) {
  const g = pf && pf.perf && pf.perf.goal_return;
  return isNum(g) ? (g * 100) / DIVISOR[period] : null;
}

function _kpi(label, value, cls = '') {
  return `<div class="kpi kpi-sm"><div class="kpi-label">${esc(label)}</div><div class="kpi-value ${cls}">${esc(value)}</div></div>`;
}

function _renderKpis(actual, target) {
  const el = document.getElementById('jv-period-kpis');
  if (!el) return;
  const gap = isNum(actual) && isNum(target) ? actual - target : null;
  const status = gap === null ? '—' : gap >= 0 ? t('period.status.on_track') : t('period.status.behind');
  el.innerHTML = `<div class="jv-loc-kpis">
    ${_kpi(t('period.actual'), isNum(actual) ? fmtPctPoint(actual) : '—', _sign(actual))}
    ${_kpi(t('period.target'), isNum(target) ? fmtPctPoint(target) : '—')}
    ${_kpi(t('period.gap'), isNum(gap) ? fmtPctPoint(gap) : '—', _sign(gap))}
    ${_kpi(t('period.status'), status, gap !== null ? (gap >= 0 ? 'pos' : 'neg') : '')}
  </div>`;
}

function _renderChart(insts, period) {
  const wrap = document.getElementById('jv-period-chart-wrap');
  const titleEl = document.getElementById('jv-period-chart-title');
  if (titleEl) titleEl.textContent = t('period.chart.title');
  const relevant = insts.filter(r => period === 'monthly' ? isNum(r.y1) : isNum(r.daily)).slice(0, 12);
  if (!relevant.length) { destroyChart('jv-period-chart'); if (wrap) wrap.hidden = true; return; }
  const labels = relevant.map(r => r.id);
  const data = relevant.map(r => period === 'monthly' ? r.y1 / 12 : period === 'weekly' ? r.daily * 5 : r.daily);
  if (wrap) wrap.hidden = false;
  const mono = { family: C.mono, size: 10 };
  mkChart('jv-period-chart', {
    type: 'line',
    data: { labels, datasets: [{ data, borderColor: 'rgba(140,135,122,0.4)', backgroundColor: 'transparent',
      fill: false, tension: 0, borderWidth: 1.5, spanGaps: true,
      pointRadius: 5, pointHoverRadius: 7, pointBackgroundColor: C.run, pointBorderColor: C.run, pointBorderWidth: 0 }] },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => `${ctx.label}: ${fmtPctPoint(ctx.raw)}` } } },
      scales: {
        x: { grid: { display: false }, ticks: { font: { family: C.mono, size: 9 }, maxRotation: 45 } },
        y: { grid: { color: 'rgba(0,0,0,.05)' }, ticks: { font: mono, callback: v => `${v}%` } },
      },
    },
  });
}

function _renderHedge(pf, loc) {
  const el = document.getElementById('jv-period-hedge');
  if (!el) return;
  const p = pf && pf.perf;
  if (!p || !isNum(p.ytd_return) || !isNum(p.target_to_date)) { el.hidden = true; return; }
  const gap = p.ytd_return - p.target_to_date;
  const key = gap >= 0 ? 'on_track' : gap > -0.05 ? 'watch' : 'needed';
  const cls = key === 'on_track' ? 'pos' : key === 'watch' ? 'warn' : 'neg';
  const fno = loc === 'india' ? `<span class="jv-muted" style="display:block;margin-top:4px;font-size:11px">${esc(t('period.hedge.fno'))}</span>` : '';
  el.innerHTML = `<div style="display:flex;flex-wrap:wrap;align-items:center;gap:10px">
    <span class="card-sub">${esc(t('period.hedge.title'))}</span>
    <span class="kpi-value ${cls}" style="font-size:13px">${esc(t(`period.hedge.${key}`))}</span>
    <span class="jv-muted" style="font-size:11px">${esc(t('period.hedge.ytd', { ytd: fmtRate(p.ytd_return), ttd: fmtRate(p.target_to_date) }))}</span>
    ${fno}
  </div>`;
  el.hidden = false;
}

function _render() {
  const card = document.getElementById('jv-period-card');
  if (!_pf || !_loc) { if (card) card.hidden = true; return; }
  if (card) card.hidden = false;
  document.querySelectorAll('#jv-period-tabs button[data-period]').forEach(b => {
    b.classList.toggle('is-active', b.dataset.period === _period);
  });
  const insts = _portInsts(_pf, _geo, _loc);
  _renderKpis(_actual(insts, _period), _target(_pf, _period));
  _renderChart(insts, _period);
  _renderHedge(_pf, _loc);
}

export function initRegionPeriod() {
  document.getElementById('jv-period-tabs')?.addEventListener('click', e => {
    const b = e.target.closest('button[data-period]');
    if (b) { _period = b.dataset.period; _render(); }
  });
}

export function renderRegionPeriod(loc, pf, geo) {
  _loc = loc; _pf = pf; _geo = geo;
  _render();
}

export function clearRegionPeriod() {
  _loc = null; _pf = null; _geo = null;
  const card = document.getElementById('jv-period-card');
  if (card) card.hidden = true;
}
