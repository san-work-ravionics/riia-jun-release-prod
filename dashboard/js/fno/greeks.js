// ── Greeks + Risk sections ────────────────────────────────────────────────────
import { t } from '../shared/i18n.js';
import { state } from './state.js';
import { pnlClass } from './utils.js';

// ── F41 helpers (null-safe, escaped) ─────────────────────────────────────────
const _esc = v => String(v ?? '').replace(/[&<>"']/g, c => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const _num = v => (typeof v === 'number' ? v : parseFloat(v));
const _has = v => v != null && v !== '' && Number.isFinite(_num(v));
const _sum = (arr, k) => arr.reduce((s, g) => s + (_has(g[k]) ? _num(g[k]) : 0), 0);
// A value that rounds to zero at its display precision is neutral: no sign, no colour (F41-QA-1)
const _rz = (v, d) => _has(v) && Number(_num(v).toFixed(d)) === 0;
const _cls = (v, d = 0) => (!_has(v) || _rz(v, d) ? 'neu' : _num(v) < 0 ? 'neg' : 'pos');
const _sign = n => (n < 0 ? '−' : '+');
const _inr = n => Math.abs(Math.round(n)).toLocaleString('en-IN');
const _fmtDelta = v => (!_has(v) ? '—' : _rz(v, 2) ? '0.00' : `${_num(v) < 0 ? '−' : '+'}${Math.abs(_num(v)).toFixed(2)}`);
const _fmtGamma = v => (!_has(v) ? '—' : _rz(v, 4) ? '0.0000' : `${_num(v) < 0 ? '−' : '+'}${Math.abs(_num(v)).toFixed(4)}`);
const _fmtRs = v => (!_has(v) ? '—' : _rz(v, 0) ? '₹0' : `${_sign(_num(v))}₹${_inr(_num(v))}`);

function _gCell(sym, nameKey, hintKey, cls, valStr) {
  return `<div class="rk-g"><div class="rk-g-name">${sym} ${_esc(t(nameKey))}</div>` +
    `<div class="rk-g-val ${cls}">${valStr}</div>` +
    `<div class="rk-g-hint">${_esc(t(hintKey))}</div></div>`;
}

export function renderGreeksCards() {
  const data  = Array.isArray(state.greeksData) ? state.greeksData : [];
  const sel   = state.riskSelectedInstrument;
  const allUnds = [...new Set(data.map(g => g.und).filter(u => u != null))];
  const unds  = sel ? (allUnds.includes(sel) ? [sel] : []) : allUnds;
  const grid  = document.getElementById('greeks-all-grid');
  if (!grid) return;
  if (!unds.length) {
    grid.innerHTML = `<div class="rk-empty">No Greeks data — select a portfolio instrument above or check API response</div>`;
    return;
  }
  const th = (sym, nameKey, hintKey) =>
    `<th class="num" title="${_esc(t(hintKey))}">${sym} ${_esc(t(nameKey))}</th>`;
  const rows = unds.map(und => {
    const filt  = data.filter(g => g.und === und);
    const delta = _sum(filt, 'delta');
    const gamma = _sum(filt, 'gamma');
    const theta = _sum(filt, 'theta');
    const vega  = _sum(filt, 'vega');
    const clr = und === 'NIFTY' ? 'var(--p02)' : und === 'BANKNIFTY' ? 'var(--p04)' : 'var(--t3)';
    return `<tr class="rk-ug-row">
      <td class="rk-ug-name" style="color:${clr}" title="${_esc(und)}">${_esc(und)}</td>
      <td class="num rk-g-val ${_cls(delta, 2)}">${_fmtDelta(delta)}</td>
      <td class="num rk-g-val ${_cls(gamma, 4)}">${_fmtGamma(gamma)}</td>
      <td class="num rk-g-val ${_cls(theta)}">${_fmtRs(theta)}</td>
      <td class="num rk-g-val ${_cls(vega)}">${_fmtRs(vega)}</td>
    </tr>`;
  }).join('');
  grid.innerHTML = `<table class="rk-tbl rk-net-tbl"><thead><tr>
      <th>Underlying</th>
      ${th('Δ', 'greeks.delta', 'greeks.hint_delta')}
      ${th('Γ', 'greeks.gamma', 'greeks.hint_gamma')}
      ${th('Θ', 'greeks.theta_day', 'greeks.hint_theta')}
      ${th('V', 'greeks.vega', 'greeks.hint_vega')}
    </tr></thead><tbody>${rows}</tbody></table>`;
}

export function renderGreeksTable() {
  const data = Array.isArray(state.greeksData) ? state.greeksData : [];
  const sel = state.riskSelectedInstrument;
  const filtered = data.filter(g =>
    (sel ? g.und === sel : true) &&
    (state.currentUnd === 'ALL' || g.und === state.currentUnd) &&
    (state.currentExpiry === 'ALL' || g.exp === state.currentExpiry)
  );
  const subEl = document.getElementById('greeks-table-sub');
  const noHedgeNote = filtered.length && filtered.every(g => g.theta === 0 && g.vega === 0 && g.gamma === 0)
    ? ' · Θ/V/Γ = 0 — add a hedge plan to see option Greeks' : '';
  if (subEl) subEl.textContent = (sel ? sel : (state.currentUnd === 'ALL' ? t('greeks.all_positions') : state.currentUnd + t('greeks.positions_suffix'))) + noHedgeNote;
  const listEl = document.getElementById('greeks-tbody');
  if (listEl) {
    listEl.innerHTML = filtered.length ? filtered.map(g => {
      const instLabel = g.full ?? (g.und && g.hedge_type ? `${g.und} ${g.hedge_type}` : g.und ?? '—');
      const ivVal = _has(g.ann_vol_pct) ? _num(g.ann_vol_pct).toFixed(1) + '%' : '—';
      const undBg = g.und === 'NIFTY' ? 'var(--p02-bg)' : 'var(--p04-bg)';
      const undFg = g.und === 'NIFTY' ? 'var(--p02)' : 'var(--p04)';
      const chip = (lbl, cls, val) => `<span class="rk-chip ${cls}"><i>${lbl}</i>${val}</span>`;
      return `<div class="rk-row">
        <div class="rk-row-top">
          <span class="rk-row-name" title="${_esc(instLabel)}">${_esc(instLabel)}</span>
          <span style="font-family:var(--fm);font-size:10px;font-weight:500;padding:2px 7px;border-radius:3px;background:${undBg};color:${undFg};">${_esc(g.und ?? '—')}</span>
          <span class="exp-badge ${_esc((g.exp ?? '').toLowerCase())}">${_esc(g.exp ?? '—')}</span>
          <span class="inst-badge ${_esc((g.type ?? '').toLowerCase())}">${_esc(g.type ?? '—')}</span>
          <span class="side-badge ${_esc((g.side ?? '').toLowerCase())}">${_esc(g.side ?? '—')}</span>
        </div>
        <div class="rk-chips">
          ${chip('Δ', _cls(g.delta, 2), _fmtDelta(g.delta))}
          ${chip('Γ', _cls(g.gamma, 4), _fmtGamma(g.gamma))}
          ${chip('Θ/day', _cls(g.theta), _fmtRs(g.theta))}
          ${chip('Vega', _cls(g.vega), _fmtRs(g.vega))}
          ${chip('IV', 'neu', ivVal)}
        </div>
      </div>`;
    }).join('') : `<div class="rk-empty">No positions</div>`;
  }
  const totDelta = _sum(filtered, 'delta');
  const totTheta = _sum(filtered, 'theta');
  const totVega  = _sum(filtered, 'vega');
  const footerEl = document.getElementById('greeks-footer');
  if (footerEl) footerEl.innerHTML = `
    <span class="lbl">${t('greeks.net_delta_lbl')}</span><span class="val ${pnlClass(totDelta)}">${_fmtDelta(totDelta)}</span>
    <span class="lbl">${t('greeks.net_theta_lbl')}</span><span class="val ${pnlClass(totTheta)}">${_fmtRs(totTheta)}${t('greeks.per_day')}</span>
    <span class="lbl">${t('greeks.net_vega_lbl')}</span><span class="val ${pnlClass(totVega)}">${_fmtRs(totVega)}</span>`;
}

export function updateRiskSections() {
  const showNifty  = state.currentUnd !== 'BANKNIFTY';
  const showBnkn   = state.currentUnd !== 'NIFTY';
  const sideBySide = state.currentUnd === 'ALL';

  const niftyWrap = document.getElementById('payoff-nifty-wrap');
  const bnknWrap  = document.getElementById('payoff-bnkn-wrap');
  const chartGrid = document.getElementById('payoff-charts-grid');
  if (niftyWrap) niftyWrap.style.display = showNifty ? '' : 'none';
  if (bnknWrap)  bnknWrap.style.display  = showBnkn  ? '' : 'none';
  if (chartGrid) chartGrid.style.gridTemplateColumns = sideBySide ? '1fr 1fr' : '1fr';

  // stress-card-sub is now set by renderStressScenarios() in stress.js
}
