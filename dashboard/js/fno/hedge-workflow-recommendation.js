// ── Hedge Workflow — Recommendation step (F39 Phase 3) ───────────────────────
// Hedge Advisor verdict (GET /api/v1/experience/fno/hedge-reasoning, 7-step cascade
// rendered as static cards — typewriter / skip-to-verdict dropped, animation only)
// plus a per-holding selection table (hedged? + strategy) fed by portfolio-hedge.
//
// Refresh strategy: on step entry only (no polling). The advisor is re-fetched only
// when its cache key `${instrumentId}|${nShares}` changes, or on "Re-run".

import { apiFetch } from './api.js';
import { setEl } from '../shared/utils.js';
import { state } from './state.js';
import { renderInstrumentTiles } from './hedge-instrument-tiles.js';
import { computeNShares, hedgeLabel, hedgeType, estRisk } from './hedge-calc.js';
import { hwMarkDirty, authHeaders, STRATEGY_LABELS } from './hedge-workflow-save.js';

let _recToken = 0;

function _hw() { return state.hedgeWorkflow; }

function _esc(v) {
  return String(v ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function _holding(id) {
  return (_hw().portfolioHoldings || []).find((h) => h.instrument_id === id) || null;
}

// nShares for the advisor request: the user's real holding, never invented.
function _nSharesFor(id) {
  const h = _holding(id);
  if (!h) return null;
  return computeNShares(h, _hw().instruments[id], _hw().totalValueEur);
}

function _cta() {
  return `<div class="kpi-sub">No holdings yet — build a portfolio first.</div>
    <button onclick="document.querySelector('.nav-item[data-page=\\'equity-scenarios\\']')?.click()"
      style="margin-top:8px;padding:6px 16px;border:none;border-radius:6px;background:var(--p03);color:#fff;font-family:var(--fm);font-size:12px;font-weight:600;cursor:pointer">
      Go to Portfolio Builder
    </button>`;
}

async function _fetchPortfolioHedge() {
  const hw = _hw();
  let url = `/api/v1/experience/fno/portfolio-hedge?coverage=${hw.coverage}`;
  if (hw.totalValueEur != null) url += `&total_value_eur=${hw.totalValueEur}`;
  return apiFetch(url, { headers: authHeaders() });
}

// Default strategy per holding (same rule as the old Portfolio Hedge page);
// never overwrites a choice the user already made this session.
function _ensureSelections() {
  const hw = _hw();
  const rows = hw.apiHedge?.holdings || [];
  for (const h of rows) {
    if (!(h.instrument_id in hw.selections)) {
      hw.selections[h.instrument_id] = (h.risk_score ?? 2) >= 3 ? 'put_buy' : 'call_sell';
    }
  }
  for (const h of hw.portfolioHoldings || []) {
    if (!(h.instrument_id in hw.selections)) {
      const inst = hw.instruments[h.instrument_id] || {};
      hw.selections[h.instrument_id] = (inst.risk_score ?? estRisk(inst.daily_return_pct)) >= 3 ? 'put_buy' : 'call_sell';
    }
  }
}

// ── Rendering ────────────────────────────────────────────────────────────────
function _renderInstrumentSelect() {
  renderInstrumentTiles('hw-rec-instrument-select', _hw());
}

function _renderStatus(msg, withRerun) {
  setEl(
    'hw-rec-status',
    `<span class="kpi-sub">${msg}</span>` +
      (withRerun
        ? ` <button onclick="hwRerunAdvisor()" style="margin-left:8px;padding:2px 10px;border:1px solid var(--p03);border-radius:6px;background:transparent;font-family:var(--fm);font-size:11px;cursor:pointer">Re-run</button>`
        : '')
  );
}

function _renderAdvisor() {
  const adv = _hw().advisor;
  const d = adv.data;
  if (!d) {
    setEl('hw-rec-cascade', '');
    setEl('hw-rec-verdict-card', `<div class="kpi-sub">No advisor verdict available.</div>`);
    setEl('hw-rec-detail', '');
    return;
  }
  const steps = d.steps || [];
  setEl(
    'hw-rec-cascade',
    steps
      .map(
        (s, i) => `<div class="kpi" style="margin-bottom:8px;">
          <div class="kpi-label">${i + 1}. ${_esc(s.title)} <span style="opacity:.6">(${_esc(s.agent)})</span></div>
          <div class="kpi-sub">${_esc(s.narrative)}</div>
          <div class="kpi-sub"><strong>${_esc(s.verdict)}</strong></div>
        </div>`
      )
      .join('')
  );
  const recLabel =
    d.recommendation === 'no_hedge' ? 'No hedge' : STRATEGY_LABELS[d.recommendation] || d.recommendation;
  setEl(
    'hw-rec-verdict-card',
    `<div class="kpi-label">Verdict</div>
     <div class="kpi-val">${_esc(recLabel)}</div>
     <div class="kpi-sub">Confidence: ${_esc(d.confidence)} &middot; Spot: ${d.spot_price != null ? Number(d.spot_price).toFixed(2) : '—'} &middot; Source: ${_esc(d.data_source)}</div>`
  );
  const hs = steps.find((s) => s.agent === 'HEDGE_ADVISOR') || steps[steps.length - 1];
  const hd = hs?.data || {};
  const leg = (name, o) =>
    o && o.strike_label && o.strike_label !== 'n/a'
      ? `<div class="kpi-sub">${name}: ${_esc(o.strike_label)} &middot; premium ${o.premium_pct != null ? Number(o.premium_pct).toFixed(2) : '—'}% (EUR ${o.premium_eur != null ? Number(o.premium_eur).toFixed(2) : '—'})</div>`
      : '';
  setEl(
    'hw-rec-detail',
    `<div class="kpi-sub">${_esc(hd.primary_rationale || '')}</div>
     ${hd.secondary_recommendation ? `<div class="kpi-sub">Secondary: ${_esc(STRATEGY_LABELS[hd.secondary_recommendation] || hd.secondary_recommendation)} — ${_esc(hd.secondary_rationale || '')}</div>` : ''}
     ${leg('Covered call', hd.call_sell)}${leg('Protective put', hd.put_buy)}
     ${_nSharesFor(_hw().instrumentId) == null ? `<div class="kpi-sub" style="opacity:.7">No equity holding for this instrument — EUR amounts are illustrative.</div>` : ''}`
  );
}

function _renderSelectionTable() {
  const hw = _hw();
  const holdings = hw.portfolioHoldings || [];
  const nextBtn = document.getElementById('hw-rec-next-btn');
  if (nextBtn) nextBtn.disabled = !holdings.length;
  if (!holdings.length) {
    setEl('hw-rec-selection-table', _cta());
    return;
  }
  const apiMap = {};
  for (const h of hw.apiHedge?.holdings || []) apiMap[h.instrument_id] = h;
  const body = holdings
    .map((h) => {
      const id = h.instrument_id;
      const a = apiMap[id];
      const type = a
        ? hedgeLabel(a.hedge_type)
        : hedgeLabel(hedgeType(id, hw.instruments[id]?.region, h.allocation_pct));
      const cost = a
        ? `${_esc(a.strike_label)} &middot; ${Number(a.cost_pct).toFixed(2)}%${a.put_cost_eur != null ? ` (EUR ${Number(a.put_cost_eur).toFixed(0)})` : ''}`
        : '—';
      const sel = hw.selections[id] || 'put_buy';
      const opts = Object.entries(STRATEGY_LABELS)
        .map(([k, v]) => `<option value="${k}" ${k === sel ? 'selected' : ''}>${v}</option>`)
        .join('');
      return `<tr>
        <td>${_esc(id)}</td>
        <td>${type}</td>
        <td><input type="checkbox" ${hw.hedgedIds.includes(id) ? 'checked' : ''} onchange="hwToggleHedged('${id}')"></td>
        <td><select onchange="hwSelectStrategy('${id}', this.value)" style="font-family:var(--fm);font-size:12px;">${opts}</select></td>
        <td>${cost}</td>
      </tr>`;
    })
    .join('');
  setEl(
    'hw-rec-selection-table',
    `<table style="width:100%;font-family:var(--fm);font-size:12px;border-collapse:collapse;">
       <thead><tr style="text-align:left;opacity:.7;">
         <th>Instrument</th><th>Hedge type</th><th>Hedged?</th><th>Strategy</th><th>Strike &amp; cost</th>
       </tr></thead>
       <tbody>${body}</tbody>
     </table>`
  );
}

// ── Advisor fetch (cache-keyed) ──────────────────────────────────────────────
async function _loadAdvisor(force) {
  const hw = _hw();
  const id = hw.instrumentId;
  if (!id) {
    hw.advisor = { key: null, data: null, error: null };
    _renderAdvisor();
    _renderStatus('Select an instrument to run the Hedge Advisor.', false);
    return;
  }
  const nShares = _nSharesFor(id);
  const key = `${id}|${nShares}`;
  if (!force && hw.advisor.key === key && hw.advisor.data) {
    _renderAdvisor();
    _renderStatus(`Hedge Advisor (${_esc(hw.advisor.data.data_source)})`, true);
    return;
  }
  const token = ++_recToken;
  _renderStatus('Running Hedge Advisor…', false);
  let url = `/api/v1/experience/fno/hedge-reasoning?instrument=${encodeURIComponent(id)}`;
  if (nShares != null) url += `&n_shares=${nShares}`;
  const data = await apiFetch(url);
  if (token !== _recToken || hw.instrumentId !== id) return; // stale response
  if (!data) {
    hw.advisor = { key, data: null, error: 'Hedge Advisor unavailable' };
    _renderAdvisor();
    _renderStatus('Hedge Advisor unavailable — defaults from portfolio-hedge are shown.', true);
    return;
  }
  // The advisor's verdict seeds the strategy for the active instrument once per
  // fetch; it never overrides a later user choice.
  if (data.recommendation === 'put_buy' || data.recommendation === 'call_sell') {
    hw.selections[id] = data.recommendation;
  }
  hw.advisor = { key, data, error: null };
  _renderAdvisor();
  _renderStatus(`Hedge Advisor (${_esc(data.data_source)})`, true);
  _renderSelectionTable();
}

// ── Step entry ───────────────────────────────────────────────────────────────
export async function loadRecommendationStep() {
  const hw = _hw();
  _renderInstrumentSelect();
  if (!(hw.portfolioHoldings || []).length) {
    _renderAdvisor();
    _renderStatus('', false);
    _renderSelectionTable();
    return;
  }
  _ensureSelections();
  _renderSelectionTable();
  _renderAdvisor();
  try {
    const [hedgeRes] = await Promise.allSettled([_fetchPortfolioHedge(), _loadAdvisor(false)]);
    if (hedgeRes.status === 'fulfilled' && hedgeRes.value) hw.apiHedge = hedgeRes.value;
  } catch (e) {
    console.warn('[hedge-workflow] recommendation load failed', e);
  }
  _ensureSelections();
  _renderSelectionTable();
}

// ── window.hwToggleHedged(id) / hwSelectStrategy(id, strategy) ──────────────
export function hwToggleHedged(id) {
  const hw = _hw();
  const i = hw.hedgedIds.indexOf(id);
  if (i >= 0) hw.hedgedIds.splice(i, 1);
  else hw.hedgedIds.push(id);
  hwMarkDirty();
  _renderSelectionTable();
}

export function hwSelectStrategy(id, strategy) {
  if (!STRATEGY_LABELS[strategy]) return;
  _hw().selections[id] = strategy;
  _renderSelectionTable();
}

// ── window.hwRerunAdvisor() ──────────────────────────────────────────────────
export async function hwRerunAdvisor() {
  await _loadAdvisor(true);
  _renderSelectionTable();
}
