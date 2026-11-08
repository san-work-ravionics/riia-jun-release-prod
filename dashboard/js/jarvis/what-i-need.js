// Jarvis — What I Need (F43 / F45).  Layout, top to bottom (F45 UI direction, as the RITA Overview):
//   1. regions, each with its instruments — yearly target and achieved instead of a bullish/bearish signal
//   2. agent commentary
//   3. Daily / Weekly / Monthly tabs, 8 panels with green / red indicators
//   4. plan-vs-reality line charts (overall, investment, one per investment type)
//   5. plan and bucket details (collapsed)
// Data shaping is in wn-model.js, charts in wn-plots.js.
import { api } from '../shared/api.js';
import { locCurrency, loadGeography, allInstruments } from './regions.js?v=3';
import { t } from './copy.js?v=13';
import { fmtMoney, fmtRate, fmtDate, fmtNum, isNum } from './format.js?v=3';
import { esc } from './esc.js?v=3';
import { loadPortfolio } from './portfolio.js?v=3';
import { LOC_KEYS, heldInstruments, regionModel, periodPanels, commentaryText, planSeries } from './wn-model.js?v=2';
import { renderPlots, clearPlots } from './wn-plots.js?v=2';

let _seq = 0;
const $ = id => document.getElementById(id);
const S = { period: 'daily', held: [], geoList: [], active: null, base: null, pf: null, ccy: 'EUR' };

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
  const breakdowns = (S.active && S.active.bucketBreakdown) || [];
  const text = commentaryText({
    held: S.held, breakdowns, inp: S.active.plan.inputs, atRet: S.base && S.base.result && S.base.result.atRet, ccy: S.ccy,
  });
  _typewrite($('jv-wn-commentary'), text);
}

// ── 3. Daily / Weekly / Monthly panels ───────────────────────────────────────────

function _renderPeriod() {
  document.querySelectorAll('#jv-wn-period-tabs button[data-period]').forEach(b => {
    b.classList.toggle('active', b.dataset.period === S.period);
  });
  const box = $('jv-wn-panels');
  if (!box) return;
  box.innerHTML = periodPanels(S.held, S.geoList, S.period).map(p => `<div class="kpi">
    <div class="kpi-label">${esc(p.label)}</div>
    <div class="kpi-value ${p.cls || 'neu'}" style="font-size:16px">${esc(p.value)}</div>
    <div class="kpi-delta">${esc(p.sub || '')}</div>
  </div>`).join('');
}

// ── 4. plots ─────────────────────────────────────────────────────────────────────

function _renderPlots() {
  const result = S.base && S.base.result;
  if (!result) { clearPlots(); return; }
  const series = planSeries(result, S.active.plan.inputs, S.active.bucketBreakdown || []);
  const actualNow = S.pf && S.pf.perf && S.pf.perf.money ? S.pf.perf.money.value_now : null;
  renderPlots(series, { ccy: S.ccy, actualNow });
}

// ── 5. details (the earlier KPI strip, tracking, bucket table and plan table) ────

const _ASSETS = [
  { key: 'idx', copyKey: 'wn.label.idx' },
  { key: 'eq',  copyKey: 'wn.label.eq'  },
  { key: 'com', copyKey: 'wn.label.com' },
  { key: 'alt', copyKey: 'wn.label.alt' },
];

function _renderMonthly(breakdowns, LABEL) {
  const box = $('jv-wn-bucket-monthly');
  if (!box) return;
  const sections = breakdowns.filter(b => (b.monthly || []).length).map(b => {
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
  });
  box.innerHTML = sections.join('');
}

function _renderBuckets(breakdowns, ccy) {
  const wrap = $('jv-wn-bucket-wrap');
  if (!wrap) return;
  if (!breakdowns || !breakdowns.length) { wrap.hidden = true; return; }
  wrap.hidden = false;

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

  _renderMonthly(breakdowns, LABEL);

  const nRisk = breakdowns.filter(b => b.atRisk === true).length;
  const sum = $('jv-wn-bucket-summary');
  if (sum) {
    const nOk = breakdowns.filter(b => b.atRisk === false).length;
    const state = nRisk ? 'risk' : nOk ? 'ok' : 'nodata';
    sum.className = 'jv-wn-bucket-summary ' + state;
    sum.textContent = state === 'risk' ? t('wn.bucket.summary_risk').replace('{n}', nRisk)
      : state === 'ok' ? t('wn.bucket.summary_ok') : t('wn.bucket.summary_nodata');
  }

  const tbl = $('jv-wn-bucket-tbl');
  if (tbl) {
    tbl.innerHTML = `<table class="jv-table"><thead><tr>
      <th>${t('wn.bucket.col.bucket')}</th>
      <th class="num">${t('wn.bucket.col.monthly')}</th>
      <th class="num">${t('wn.bucket.col.target_ytd')}</th>
      <th class="num">${t('wn.bucket.col.actual_ytd')}</th>
      <th class="num">${t('wn.bucket.col.gap')}</th>
      <th>${t('wn.bucket.col.instruments')}</th>
    </tr></thead><tbody>${rows}</tbody></table>`;
  }
}

function _renderDetails() {
  const plan = S.active.plan;
  const inp = plan.inputs;
  const r = S.base.result;
  const wf = S.base.waterfall;
  const ccy = S.ccy;
  const set = (id, v) => { const e = $(id); if (e) e.textContent = v; };

  const atRet = r && r.atRet;
  set('jv-wn-kpi-need', atRet ? fmtMoney(atRet.monthly, ccy) : '—');
  set('jv-wn-kpi-ret', inp.ret != null ? `Age ${inp.ret}` : '—');
  set('jv-wn-kpi-years', inp.ret != null && inp.now != null ? String(inp.ret - inp.now) : '—');
  set('jv-wn-kpi-port-ret', fmtMoney(wf && wf.portfolioValue, ccy));

  const pts = (r && r.withInvesting && r.withInvesting.points) || [];
  const nowPoint = pts.find(p => p.age === inp.now);
  const plannedNow = nowPoint ? nowPoint.portfolio : null;
  const actualNow = S.pf && S.pf.perf && S.pf.perf.money ? S.pf.perf.money.value_now : null;
  const trackGap = actualNow != null && plannedNow != null ? actualNow - plannedNow : null;
  set('jv-wn-kpi-planned', plannedNow != null ? fmtMoney(plannedNow, ccy) : '—');
  set('jv-wn-kpi-actual', actualNow != null ? fmtMoney(actualNow, ccy) : '—');
  const kGap = $('jv-wn-kpi-track-gap');
  if (kGap) {
    kGap.textContent = trackGap != null ? fmtMoney(trackGap, ccy) : '—';
    kGap.className = 'kpi-value' + (trackGap != null ? (trackGap >= 0 ? ' pos' : ' neg') : '');
  }

  const assetMap = {};
  ((r && r.assets) || []).forEach(a => { assetMap[a.key] = a; });
  const wrap = $('jv-wn-asset-table');
  if (wrap) {
    const rows = _ASSETS.map(({ key, copyKey }) => {
      const monthly = inp[key + 'Monthly'];
      const rate = inp[key + 'Rate'];
      const info = assetMap[key];
      return `<tr>
        <td>${t(copyKey)}</td>
        <td class="num">${monthly != null ? fmtMoney(monthly, ccy) + '/mo' : '—'}</td>
        <td class="num">${rate != null ? fmtRate(rate) : '—'}</td>
        <td class="num">${info ? fmtMoney(info.value, ccy) : '—'}</td>
      </tr>`;
    }).join('');
    wrap.innerHTML = `<table class="jv-table"><thead><tr>
      <th>${t('wn.trk.col.asset')}</th>
      <th class="num">${t('wn.trk.col.monthly')}</th>
      <th class="num">${t('wn.trk.col.rate')}</th>
      <th class="num">${t('wn.trk.col.atret')}</th>
    </tr></thead><tbody>${rows}</tbody></table>`;
  }

  const meta = $('jv-wn-plan-meta');
  if (meta) {
    meta.textContent = plan.updatedAt ? t('wn.trk.saved', { date: fmtDate(plan.updatedAt) }) : '';
    meta.hidden = !plan.updatedAt;
  }
  _renderBuckets(S.active.bucketBreakdown || [], ccy);
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
  // Overall view: not tied to the sidebar location.  The user has ONE saved plan (tagged with the location it was
  // saved under), so find it among the locations; the regions section then shows every region.
  const seq = ++_seq;
  _setStatus(t('wn.loading'), false);
  const noPlan = $('jv-wn-no-plan');
  const content = $('jv-wn-content');

  try {
    const [planList, geo] = await Promise.all([
      Promise.all(LOC_KEYS.map(l => api(`/api/v1/experience/jarvis/retirement-plan?location=${encodeURIComponent(l)}`).catch(() => null))),
      loadGeography().catch(() => null),    // region / name / price / period returns; the page degrades without it
    ]);
    if (seq !== _seq) return;

    const plans = {};
    LOC_KEYS.forEach((l, i) => { plans[l] = planList[i]; });
    const location = LOC_KEYS.find(l => plans[l] && plans[l].plan && plans[l].plan.saved);

    if (!location) {
      _setStatus('', false);
      clearPlots();
      if (noPlan) noPlan.hidden = false;
      if (content) content.hidden = true;
      return;
    }
    const active = plans[location];

    const spread = active.scenarioSpread || { pessimistic: -0.02, optimistic: 0.02 };
    const [calcData, pf] = await Promise.all([
      api('/api/v1/experience/jarvis/retirement-plan/calculate', 'POST',
        { inputs: active.plan.inputs, scenarios: ['base'], spread, discount_rate: null }),
      loadPortfolio(location).catch(() => null),
    ]);
    if (seq !== _seq) return;

    Object.assign(S, {
      held: heldInstruments(plans), geoList: allInstruments(geo), active, pf,
      base: calcData.scenarios.base, ccy: locCurrency(location, pf) || 'EUR',
    });
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
    if (!b || !S.active) return;
    S.period = b.dataset.period;
    _renderPeriod();
  });
}
