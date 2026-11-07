import { api } from '../shared/api.js';
import { locCurrency } from './regions.js?v=3';
import { t } from './copy.js?v=6';
import { fmtMoney, fmtRate, fmtDate, fmtNum, isNum } from './format.js?v=3';
import { esc } from './esc.js?v=3';
import { loadPortfolio } from './portfolio.js?v=3';

let _getLoc = () => 'europe';
let _seq = 0;
const $ = id => document.getElementById(id);

function _setStatus(msg, isError) {
  const el = $('jv-wn-status');
  if (!el) return;
  el.textContent = msg || '';
  el.className = isError ? 'wn-status wn-err' : 'wn-status';
}

const _ASSETS = [
  { key: 'idx', copyKey: 'wn.label.idx' },
  { key: 'eq',  copyKey: 'wn.label.eq'  },
  { key: 'com', copyKey: 'wn.label.com' },
  { key: 'alt', copyKey: 'wn.label.alt' },
];

function _renderBuckets(breakdowns, ccy) {
  const wrap = $('jv-wn-bucket-wrap');
  if (!wrap) return;
  if (!breakdowns || !breakdowns.length) {
    wrap.hidden = true;
    return;
  }
  wrap.hidden = false;

  const LABEL = { idx: t('wn.label.idx'), eq: t('wn.label.eq'), com: t('wn.label.com'), alt: t('wn.label.alt') };
  const rows = breakdowns.map(b => {
    const chips = (b.instruments || []).map(i => `<span class="jv-hold-chip"><b class="mono">${esc(i.instrumentId)}</b>${isNum(i.allocationPct) ? ' ' + fmtNum(i.allocationPct, 0) + '%' : ''}</span>`).join('');
    const statusChip = b.atRisk === true
      ? `<span class="jv-badge warn">${t('wn.bucket.at_risk')}</span>`
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

function _render(plan, base, pf, ccy, bucketBreakdown) {
  const inp = plan.inputs;
  const r = base.result;
  const wf = base.waterfall;
  const set = (id, v) => { const e = $(id); if (e) e.textContent = v; };

  // Plan KPIs
  const atRet = r && r.atRet;
  set('jv-wn-kpi-need', atRet ? fmtMoney(atRet.monthly, ccy) : '—');
  set('jv-wn-kpi-ret', inp.ret != null ? `Age ${inp.ret}` : '—');
  set('jv-wn-kpi-years', inp.ret != null && inp.now != null ? String(inp.ret - inp.now) : '—');
  set('jv-wn-kpi-port-ret', fmtMoney(wf && wf.portfolioValue, ccy));

  // Tracking KPIs — planned value at current age from the base projection
  const pts = (r && r.withInvesting && r.withInvesting.points) || [];
  const nowPoint = pts.find(p => p.age === inp.now);
  const plannedNow = nowPoint ? nowPoint.portfolio : null;
  const actualNow = pf && pf.perf && pf.perf.money ? pf.perf.money.value_now : null;
  const trackGap = actualNow != null && plannedNow != null ? actualNow - plannedNow : null;

  set('jv-wn-kpi-planned', plannedNow != null ? fmtMoney(plannedNow, ccy) : '—');
  set('jv-wn-kpi-actual', actualNow != null ? fmtMoney(actualNow, ccy) : '—');
  const kGap = $('jv-wn-kpi-track-gap');
  if (kGap) {
    kGap.textContent = trackGap != null ? fmtMoney(trackGap, ccy) : '—';
    kGap.className = 'kpi-value' + (trackGap != null ? (trackGap >= 0 ? ' pos' : ' neg') : '');
  }

  // Investment plan table
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

  // Plan meta
  const meta = $('jv-wn-plan-meta');
  if (meta) {
    meta.textContent = plan.updatedAt ? t('wn.trk.saved', { date: fmtDate(plan.updatedAt) }) : '';
    meta.hidden = !plan.updatedAt;
  }

  // Bucket milestone breakdown
  _renderBuckets(bucketBreakdown || [], ccy);
}

export async function loadWhatINeed(location) {
  const seq = ++_seq;
  _setStatus(t('wn.loading'), false);
  const noPlan = $('jv-wn-no-plan');
  const content = $('jv-wn-content');

  try {
    const [planData, pf] = await Promise.all([
      api(`/api/v1/experience/jarvis/retirement-plan?location=${encodeURIComponent(location)}`),
      loadPortfolio(location).catch(() => null),
    ]);
    if (seq !== _seq) return;

    if (!planData.plan || !planData.plan.saved) {
      _setStatus('', false);
      if (noPlan) noPlan.hidden = false;
      if (content) content.hidden = true;
      return;
    }

    const spread = planData.scenarioSpread || { pessimistic: -0.02, optimistic: 0.02 };
    const calcData = await api(
      '/api/v1/experience/jarvis/retirement-plan/calculate',
      'POST',
      { inputs: planData.plan.inputs, scenarios: ['base'], spread, discount_rate: null },
    );
    if (seq !== _seq) return;

    const ccy = locCurrency(location, pf) || 'EUR';
    if (noPlan) noPlan.hidden = true;
    if (content) content.hidden = false;
    _render(planData.plan, calcData.scenarios.base, pf, ccy, planData.bucketBreakdown);
    _setStatus('', false);
  } catch (e) {
    if (seq !== _seq) return;
    _setStatus(e.message || t('wn.err.load', { message: '' }), true);
  }
}

export function initWhatINeed(getLocation) {
  _getLoc = getLocation;
}
