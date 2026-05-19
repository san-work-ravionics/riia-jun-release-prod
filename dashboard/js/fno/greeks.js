// ── Greeks + Risk sections ────────────────────────────────────────────────────
import { state } from './state.js';
import { fmtPnl, pnlClass } from './utils.js';

export function renderGreeksCards() {
  const unds = [];
  if (state.currentUnd !== 'BANKNIFTY') unds.push('NIFTY');
  if (state.currentUnd !== 'NIFTY')     unds.push('BANKNIFTY');
  const grid = document.getElementById('greeks-all-grid');
  grid.style.gridTemplateColumns = `repeat(${unds.length * 4}, 1fr)`;
  grid.innerHTML = unds.map(und => {
    const filt  = state.greeksData.filter(g => g.und === und && (state.currentExpiry === 'ALL' || g.exp === state.currentExpiry));
    const delta = filt.reduce((s, g) => s + (g.delta || 0), 0);
    const gamma = parseFloat(filt.reduce((s, g) => s + (g.gamma || 0), 0).toFixed(4));
    const theta = Math.round(filt.reduce((s, g) => s + (g.theta || 0), 0));
    const vega  = Math.round(filt.reduce((s, g) => s + (g.vega  || 0), 0));
    const ptMove = Math.abs(delta) * 100;
    const lbl = `<div style="font-family:var(--fm);font-size:9px;font-weight:600;color:var(--t4);letter-spacing:.06em;text-transform:uppercase;margin-bottom:4px;">${und}</div>`;
    return `
      <div class="greek-card">${lbl}<div class="greek-symbol">Δ</div><div class="greek-name">Net Delta</div>
        <div class="greek-val ${delta < 0 ? 'neg' : 'pos'}">${delta >= 0 ? '+' : ''}${delta}</div>
        <div class="greek-sub">Per 100pt move: ~${delta < 0 ? '−' : ''}₹${Math.abs(ptMove).toLocaleString('en-IN')}</div>
      </div>
      <div class="greek-card">${lbl}<div class="greek-symbol">Γ</div><div class="greek-name">Gamma</div>
        <div class="greek-val ${gamma < 0 ? 'neg' : 'pos'}">${gamma >= 0 ? '+' : ''}${gamma.toFixed(4)}</div>
        <div class="greek-sub">${gamma < 0 ? 'Short options' : 'Long options'} drive ${gamma < 0 ? 'negative' : 'positive'} gamma</div>
      </div>
      <div class="greek-card">${lbl}<div class="greek-symbol">Θ</div><div class="greek-name">Theta / day</div>
        <div class="greek-val ${theta >= 0 ? 'pos' : 'neg'}">${theta >= 0 ? '+₹' : '−₹'}${Math.abs(theta).toLocaleString('en-IN')}</div>
        <div class="greek-sub">Daily time decay ${theta >= 0 ? 'earned' : 'paid'}</div>
      </div>
      <div class="greek-card">${lbl}<div class="greek-symbol">V</div><div class="greek-name">Vega</div>
        <div class="greek-val ${vega >= 0 ? 'pos' : 'neg'}">${vega >= 0 ? '+₹' : '−₹'}${Math.abs(vega).toLocaleString('en-IN')}</div>
        <div class="greek-sub">Per 1% IV rise, ${und} ${vega >= 0 ? 'gains' : 'loses'} ₹${Math.abs(vega).toLocaleString('en-IN')}</div>
      </div>`;
  }).join('');
}

export function renderGreeksTable() {
  const filtered = state.greeksData.filter(g => (state.currentUnd === 'ALL' || g.und === state.currentUnd) && (state.currentExpiry === 'ALL' || g.exp === state.currentExpiry));
  document.getElementById('greeks-table-sub').textContent = state.currentUnd === 'ALL' ? 'All positions' : state.currentUnd + ' positions';
  document.getElementById('greeks-tbody').innerHTML = filtered.map(g => {
    const dStr = g.delta >= 0 ? `+${g.delta}` : String(g.delta);
    const tStr = g.theta > 0 ? `+₹${g.theta}` : g.theta === 0 ? '₹0' : `−₹${Math.abs(g.theta)}`;
    const vStr = g.vega  > 0 ? `+₹${g.vega}`  : g.vega  === 0 ? '₹0' : `−₹${Math.abs(g.vega)}`;
    return `<tr>
      <td>${g.full}</td>
      <td><span style="font-family:var(--fm);font-size:10px;font-weight:500;padding:2px 7px;border-radius:3px;background:${g.und === 'NIFTY' ? 'var(--p02-bg)' : 'var(--p04-bg)'};color:${g.und === 'NIFTY' ? 'var(--p02)' : 'var(--p04)'};">${g.und}</span></td>
      <td><span class="exp-badge ${g.exp.toLowerCase()}">${g.exp}</span></td>
      <td><span class="inst-badge ${g.type.toLowerCase()}">${g.type}</span></td>
      <td><span class="side-badge ${g.side.toLowerCase()}">${g.side}</span></td>
      <td class="${g.delta >= 0 ? 'pos' : 'neg'} val">${dStr}</td>
      <td class="${g.theta >= 0 ? 'pos' : 'neg'} val">${tStr}</td>
      <td class="${g.vega  >= 0 ? 'pos' : 'neg'} val">${vStr}</td>
      <td class="val">${g.iv}</td>
    </tr>`;
  }).join('');
  const totDelta = filtered.reduce((s, g) => s + g.delta, 0);
  const totTheta = filtered.reduce((s, g) => s + g.theta, 0);
  const totVega  = filtered.reduce((s, g) => s + g.vega,  0);
  document.getElementById('greeks-footer').innerHTML = `
    <span class="lbl">Net Delta:</span><span class="val ${pnlClass(totDelta)}">${totDelta >= 0 ? '+' : ''}${totDelta}</span>
    <span class="lbl">Net Theta:</span><span class="val ${pnlClass(totTheta)}">${totTheta >= 0 ? '+₹' : '−₹'}${Math.abs(totTheta)}/day</span>
    <span class="lbl">Net Vega:</span><span class="val ${pnlClass(totVega)}">${totVega >= 0 ? '+₹' : '−₹'}${Math.abs(totVega)}</span>`;
}

export function updateRiskSections() {
  const showNifty  = state.currentUnd !== 'BANKNIFTY';
  const showBnkn   = state.currentUnd !== 'NIFTY';
  const sideBySide = state.currentUnd === 'ALL';

  document.getElementById('payoff-nifty-wrap').style.display = showNifty ? '' : 'none';
  document.getElementById('payoff-bnkn-wrap').style.display  = showBnkn  ? '' : 'none';
  document.getElementById('payoff-charts-grid').style.gridTemplateColumns = sideBySide ? '1fr 1fr' : '1fr';

  const nSpot = (state.marketData.NIFTY || {}).close;
  const bSpot = (state.marketData.BANKNIFTY || {}).close;
  const subParts = [];
  if (showNifty && nSpot) subParts.push(`NIFTY ~${nSpot.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`);
  if (showBnkn  && bSpot) subParts.push(`BANKNIFTY ~${bSpot.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`);
  document.getElementById('stress-card-sub').textContent =
    `Estimated portfolio P&L for index moves · ${subParts.join(' · ')}`;
}
