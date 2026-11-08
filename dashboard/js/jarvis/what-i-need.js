// Jarvis — What I Need (F43 / F45): the OVERALL view.  Every region has its own saved plan (own inflation, risk and
// return assumptions, own currency) and its own instruments; each region is measured against its own plan and the
// regions are added together in EUR.  Layout, top to bottom (as the RITA Overview):
//   1. regions, each with its instruments — yearly target and achieved instead of a bullish/bearish signal
//   2. agent commentary
//   3. Daily / Weekly / Monthly tabs, 8 panels with green / red indicators
//   4. plan-vs-reality line charts (overall, investment, one per investment type), all regions in EUR
//   5. each region's plan and bucket details (collapsed)
// Data shaping is in wn-model.js, charts in wn-plots.js.
import { api } from '../shared/api.js';
import { loadGeography, loadEurRates, toEur, allInstruments } from './regions.js?v=5';
import { t } from './copy.js?v=18';
import { fmtMoney, fmtRate, fmtDate, fmtNum, isNum, locationName } from './format.js?v=3';
import { esc } from './esc.js?v=3';
import { loadPortfolio } from './portfolio.js?v=3';
import {
  LOC_KEYS, buildRegionPlans, regionValueEur, heldInstruments, regionModel, periodPanels, commentaryText, combinedSeries,
} from './wn-model.js?v=3';
import { renderPlots, clearPlots } from './wn-plots.js?v=3';

let _seq = 0;
const $ = id => document.getElementById(id);
const S = { period: 'daily', regions: [], held: [], geoList: [], rates: null };

const _fx = (v, ccy) => toEur(v, ccy, S.rates);

function _setStatus(msg, isError) {
  const el = $('jv-wn-status');
  if (!el) return;
  el.textContent = msg || '';
  el.className = isError ? 'wn-status wn-err' : 'wn-status';
}

// ── 1. regions and instruments ───────────────────────────────────────────────────

const _REGION_KEY = { EU: 'wn.region.eu', India: 'wn.region.india', US: 'wn.region.us', Other: 'wn.region.other' };

function _tileHtml(i) {
  const price = `<div class="kpi-value" style="font-size:13px">${isNum(i.close) ? fmtNum(i.close, 2) : '—'}</div>`;
  const name = `<div class="kpi-label" style="font-size:10px;font-weight:600;line-height:1.3;min-height:2.6em">${esc(i.name)}</div>`;
  if (!i.held) {
    return `<div class="kpi jv-wn-tile-off" style="padding:5px 6px">${name}${price}
      <div class="kpi-delta" style="font-size:10px">${esc(t('wn.region.not_held'))}</div></div>`;
  }
  const cls = !isNum(i.achieved) ? '' : i.atRisk === true ? 'neg' : i.atRisk === false ? 'pos' : '';
  return `<div class="kpi jv-wn-tile-held" style="padding:5px 6px">${name}${price}
    <div class="kpi-delta" style="font-size:10px">${esc(t('wn.region.target'))} <b>${isNum(i.target) ? fmtRate(i.target) : '—'}</b></div>
    <div class="kpi-delta ${cls}" style="font-size:10px">${esc(t('wn.region.achieved'))} <b>${isNum(i.achieved) ? fmtRate(i.achieved) : '—'}</b></div>
  </div>`;
}

function _renderRegions() {
  const box = $('jv-wn-regions');
  if (!box) return;
  const regions = regionModel(S.geoList, S.held);
  if (!regions.length) { box.innerHTML = ''; return; }
  box.innerHTML = regions.map(r => `<div class="card">
    <div class="card-hdr"><span class="card-title">${esc(t(_REGION_KEY[r.region] || 'wn.region.other'))}</span></div>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(80px,1fr));gap:6px;padding:4px 0">${r.tiles.map(_tileHtml).join('')}</div>
  </div>`).join('');
}

// ── 2. agent commentary (typewriter, as the RITA agent commentary) ───────────────

let _typeTimer = null;
let _typed = '';

function _typewrite(el, text) {
  if (!el) return;
  if (text === _typed && el.textContent === text) return;     // re-typed only when the text changes
  clearInterval(_typeTimer);
  _typed = text;
  el.textContent = '';
  let n = 0;
  _typeTimer = setInterval(() => {
    n += 1;
    el.textContent = text.slice(0, n);
    if (n >= text.length) clearInterval(_typeTimer);
  }, 10);
}

function _renderCommentary() {
  _typewrite($('jv-wn-commentary'), commentaryText({ regions: S.regions, held: S.held, fx: _fx }));
}

// ── 3. Daily / Weekly / Monthly panels ───────────────────────────────────────────

function _renderPeriod() {
  document.querySelectorAll('#jv-wn-period-tabs button[data-period]').forEach(b => {
    b.classList.toggle('active', b.dataset.period === S.period);
  });
  const box = $('jv-wn-panels');
  if (!box) return;
  const weights = {};
  S.regions.forEach(r => { const v = regionValueEur(r, _fx); if (isNum(v)) weights[r.loc] = v; });
  box.innerHTML = periodPanels(S.held, S.geoList, S.period, weights).map(p => `<div class="kpi">
    <div class="kpi-label">${esc(p.label)}</div>
    <div class="kpi-value ${p.cls || 'neu'}" style="font-size:16px">${esc(p.value)}</div>
    <div class="kpi-delta">${esc(p.sub || '')}</div>
  </div>`).join('');
}

// ── 4. plots (every region's own plan, added together in EUR) ────────────────────

function _renderPlots() {
  const series = combinedSeries(S.regions, _fx);
  if (!series) { clearPlots(); return; }
  renderPlots(series);
}

// ── 5. details: one block per region, in that region's own currency ──────────────

const _ASSETS = [
  { key: 'idx', copyKey: 'wn.label.idx' },
  { key: 'eq',  copyKey: 'wn.label.eq'  },
  { key: 'com', copyKey: 'wn.label.com' },
  { key: 'alt', copyKey: 'wn.label.alt' },
];

function _monthlyHtml(breakdowns, LABEL) {
  return breakdowns.filter(b => (b.monthly || []).length).map(b => {
    const rows = b.monthly.map(m => {
      const chip = m.atRisk === true ? `<span class="jv-badge warn">${t('wn.bucket.at_risk')}</span>`
        : m.atRisk === false ? `<span class="jv-badge ok">${t('wn.bucket.on_pace')}</span>`
        : `<span class="jv-muted">${t('wn.bucket.no_data')}</span>`;
      return `<tr><td>${esc(fmtDate(m.month))}</td>
        <td class="num">${isNum(m.target) ? fmtRate(m.target) : '—'}</td>
        <td class="num ${m.actual < 0 ? 'neg' : m.actual > 0 ? 'pos' : ''}">${isNum(m.actual) ? fmtRate(m.actual) : '—'}</td>
        <td>${chip}</td></tr>`;
    }).join('');
    return `<div class="sec-label">${esc(LABEL[b.key] || b.key)} — ${t('wn.bucket.monthly.title')}</div>
      <table class="jv-table jv-table-sm"><thead><tr><th>${t('wn.bucket.monthly.col.month')}</th>
      <th class="num">${t('wn.bucket.monthly.col.target')}</th><th class="num">${t('wn.bucket.monthly.col.actual')}</th>
      <th>${t('wn.bucket.monthly.col.status')}</th></tr></thead><tbody>${rows}</tbody></table>`;
  }).join('');
}

function _bucketsHtml(breakdowns, ccy) {
  if (!breakdowns || !breakdowns.length) return '';
  const LABEL = { idx: t('wn.label.idx'), eq: t('wn.label.eq'), com: t('wn.label.com'), alt: t('wn.label.alt') };
  const rows = breakdowns.map(b => {
    const chips = (b.instruments || []).map(i => `<span class="jv-hold-chip"><b class="mono">${esc(i.instrumentId)}</b>${isNum(i.allocationPct) ? ' ' + fmtNum(i.allocationPct, 0) + '%' : ''}</span>`).join('');
    const statusChip = b.atRisk === true
      ? `<span class="jv-badge warn">${t('wn.bucket.at_risk')}</span> <a class="jv-wn-hedge-cta" href="/dashboard/fno.html">${t('wn.bucket.review_hedge')}</a>`
      : b.atRisk === false
        ? `<span class="jv-badge ok">${t('wn.bucket.on_pace')}</span>`
        : `<span class="jv-muted">${t('wn.bucket.no_data')}</span>`;
    return `<tr>
      <td><b>${LABEL[b.key] || b.key}</b><div class="jv-hold-chips">${chips}</div></td>
      <td class="num">${isNum(b.monthlyTarget) ? fmtMoney(b.monthlyTarget, ccy) + '/mo' : '—'}</td>
      <td class="num">${isNum(b.targetToDate) ? fmtRate(b.targetToDate) : '—'}</td>
      <td class="num">${isNum(b.ytdReturn) ? fmtRate(b.ytdReturn) : '—'}</td>
      <td class="num ${b.gap < 0 ? 'neg' : b.gap > 0 ? 'pos' : ''}">${isNum(b.gap) ? fmtRate(b.gap) : '—'}</td>
      <td>${statusChip}</td>
    </tr>`;
  }).join('');
  return `<table class="jv-table"><thead><tr>
      <th>${t('wn.bucket.col.bucket')}</th><th class="num">${t('wn.bucket.col.monthly')}</th>
      <th class="num">${t('wn.bucket.col.target_ytd')}</th><th class="num">${t('wn.bucket.col.actual_ytd')}</th>
      <th class="num">${t('wn.bucket.col.gap')}</th><th>${t('wn.bucket.col.instruments')}</th>
    </tr></thead><tbody>${rows}</tbody></table>${_monthlyHtml(breakdowns, LABEL)}`;
}

function _kpi(labelKey, value, cls = '') {
  return `<div class="kpi kpi-sm"><div class="kpi-label">${esc(t(labelKey))}</div><div class="kpi-value ${cls}">${esc(value)}</div></div>`;
}

function _regionDetailsHtml(rp) {
  const inp = rp.plan.inputs;
  const r = rp.base.result;
  const wf = rp.base.waterfall;
  const ccy = rp.ccy;
  const atRet = r && r.atRet;
  const pts = (r && r.withInvesting && r.withInvesting.points) || [];
  const nowPoint = pts.find(p => p.age === inp.now);
  const plannedNow = nowPoint ? nowPoint.portfolio : null;
  const actualNow = rp.pf && rp.pf.perf && rp.pf.perf.money ? rp.pf.perf.money.value_now : null;
  const gap = isNum(actualNow) && isNum(plannedNow) ? actualNow - plannedNow : null;
  const assetMap = {};
  ((r && r.assets) || []).forEach(a => { assetMap[a.key] = a; });

  const assetRows = _ASSETS.map(({ key, copyKey }) => {
    const monthly = inp[key + 'Monthly'];
    const rate = inp[key + 'Rate'];
    const info = assetMap[key];
    return `<tr><td>${t(copyKey)}</td>
      <td class="num">${monthly != null ? fmtMoney(monthly, ccy) + '/mo' : '—'}</td>
      <td class="num">${rate != null ? fmtRate(rate) : '—'}</td>
      <td class="num">${info ? fmtMoney(info.value, ccy) : '—'}</td></tr>`;
  }).join('');

  return `<div class="jv-wn-region-block">
    <div class="sec-label">${esc(t('wn.details.region', { region: locationName(rp.loc), ccy }))}
      <a href="investgame-app.html" style="margin-left:10px;font-weight:400">${esc(t('wn.trk.edit'))}</a></div>
    <div class="kpi-row-4">
      ${_kpi('wn.trk.kpi.need', atRet ? fmtMoney(atRet.monthly, ccy) : '—')}
      ${_kpi('wn.trk.kpi.ret', inp.ret != null ? `Age ${inp.ret}` : '—')}
      ${_kpi('wn.trk.kpi.years', inp.ret != null && inp.now != null ? String(inp.ret - inp.now) : '—')}
      ${_kpi('wn.trk.kpi.port_ret', fmtMoney(wf && wf.portfolioValue, ccy))}
    </div>
    <div class="kpi-row-3">
      ${_kpi('wn.trk.kpi.planned', plannedNow != null ? fmtMoney(plannedNow, ccy) : '—')}
      ${_kpi('wn.trk.kpi.actual', actualNow != null ? fmtMoney(actualNow, ccy) : '—')}
      ${_kpi('wn.trk.kpi.track_gap', gap != null ? fmtMoney(gap, ccy) : '—', gap != null ? (gap >= 0 ? 'pos' : 'neg') : '')}
    </div>
    ${_bucketsHtml(rp.breakdowns, ccy)}
    <table class="jv-table" style="margin-top:12px"><thead><tr>
      <th>${t('wn.trk.col.asset')}</th><th class="num">${t('wn.trk.col.monthly')}</th>
      <th class="num">${t('wn.trk.col.rate')}</th><th class="num">${t('wn.trk.col.atret')}</th>
    </tr></thead><tbody>${assetRows}</tbody></table>
    <p class="jv-muted">${rp.plan.updatedAt ? esc(t('wn.trk.saved', { date: fmtDate(rp.plan.updatedAt) })) : ''}</p>
  </div>`;
}

function _renderDetails() {
  const box = $('jv-wn-details-body');
  if (box) box.innerHTML = S.regions.map(_regionDetailsHtml).join('');
}

// ── load ─────────────────────────────────────────────────────────────────────────

function _renderAll() {
  _renderRegions();
  _renderCommentary();
  _renderPeriod();
  _renderPlots();
  _renderDetails();
}

export async function loadWhatINeed() {
  // Overall view: not tied to the sidebar location.  Each region has its own saved plan; all of them are loaded.
  const seq = ++_seq;
  _setStatus(t('wn.loading'), false);
  const noPlan = $('jv-wn-no-plan');
  const content = $('jv-wn-content');

  try {
    const [planList, geo, rates] = await Promise.all([
      Promise.all(LOC_KEYS.map(l => api(`/api/v1/experience/jarvis/retirement-plan?location=${encodeURIComponent(l)}`).catch(() => null))),
      loadGeography().catch(() => null),       // region / name / price / period returns; the page degrades without it
      loadEurRates().catch(() => null),        // to add the regions together in EUR
    ]);
    if (seq !== _seq) return;

    const plans = {};
    LOC_KEYS.forEach((l, i) => { plans[l] = planList[i]; });
    const saved = LOC_KEYS.filter(l => plans[l] && plans[l].plan && plans[l].plan.saved);

    if (!saved.length) {
      _setStatus('', false);
      clearPlots();
      if (noPlan) noPlan.hidden = false;
      if (content) content.hidden = true;
      return;
    }

    // each saved plan is calculated on its own, and each region's portfolio is read, in parallel
    const [calcList, pfList] = await Promise.all([
      Promise.all(saved.map(l => api('/api/v1/experience/jarvis/retirement-plan/calculate', 'POST', {
        inputs: plans[l].plan.inputs, scenarios: ['base'],
        spread: plans[l].scenarioSpread || { pessimistic: -0.02, optimistic: 0.02 }, discount_rate: null,
      }).then(d => d.scenarios.base).catch(() => null))),
      Promise.all(saved.map(l => loadPortfolio(l).catch(() => null))),
    ]);
    if (seq !== _seq) return;

    const calcs = {};
    const pfs = {};
    saved.forEach((l, i) => { calcs[l] = calcList[i]; pfs[l] = pfList[i]; });

    S.rates = rates;
    S.regions = buildRegionPlans(plans, calcs, pfs);
    S.held = heldInstruments(plans);
    S.geoList = allInstruments(geo);
    if (!S.regions.length) throw new Error(t('wn.err.load', { message: '' }));
    if (noPlan) noPlan.hidden = true;
    if (content) content.hidden = false;
    _renderAll();
    _setStatus('', false);
  } catch (e) {
    if (seq !== _seq) return;
    _setStatus(e.message || t('wn.err.load', { message: '' }), true);
  }
}

export function initWhatINeed() {
  $('jv-wn-refresh')?.addEventListener('click', () => loadWhatINeed());
  $('jv-wn-period-tabs')?.addEventListener('click', e => {
    const b = e.target.closest('button[data-period]');
    if (!b || !S.regions.length) return;
    S.period = b.dataset.period;
    _renderPeriod();
  });
}
