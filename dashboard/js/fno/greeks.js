// ── Greeks + Risk sections ────────────────────────────────────────────────────
import { t } from '../shared/i18n.js';
import { state } from './state.js';

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
  // Symbol-only headers keep the 5-column table inside a ~1/3-width panel; full name + hint live in the title attr.
  const th = (sym, nameKey, hintKey) =>
    `<th class="num" title="${_esc(t(nameKey))} — ${_esc(t(hintKey))}">${sym}</th>`;
  const rows = unds.map(und => {
    const filt  = data.filter(g => g.und === und);
    const delta = _sum(filt, 'delta');
    const gamma = _sum(filt, 'gamma');
    const theta = _sum(filt, 'theta');
    const vega  = _sum(filt, 'vega');
    const clr = und === 'NIFTY' ? 'var(--p02)' : und === 'BANKNIFTY' ? 'var(--p04)' : 'var(--t3)';
    return `<tr class="rk-ug-row">
      <td class="rk-ug-name" style="color:${clr}" title="${_esc(und)}">${_esc(und)}</td>
      <td class="num ${_cls(delta, 2)}">${_fmtDelta(delta)}</td>
      <td class="num ${_cls(gamma, 4)}">${_fmtGamma(gamma)}</td>
      <td class="num ${_cls(theta)}">${_fmtRs(theta)}</td>
      <td class="num ${_cls(vega)}">${_fmtRs(vega)}</td>
    </tr>`;
  }).join('');
  grid.innerHTML = `<table class="rk-tbl rk-net-tbl"><thead><tr>
      <th title="Underlying">Und.</th>
      ${th('Δ', 'greeks.delta', 'greeks.hint_delta')}
      ${th('Γ', 'greeks.gamma', 'greeks.hint_gamma')}
      ${th('Θ', 'greeks.theta_day', 'greeks.hint_theta')}
      ${th('V', 'greeks.vega', 'greeks.hint_vega')}
    </tr></thead><tbody>${rows}</tbody></table>`;
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
