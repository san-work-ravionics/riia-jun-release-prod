// ── Greeks + Risk sections ────────────────────────────────────────────────────
import { t } from '../shared/i18n.js';
import { state } from './state.js';
import { fmtPnl, pnlClass } from './utils.js';

export function renderGreeksCards() {
  const sel   = state.riskSelectedInstrument;
  const allUnds = [...new Set(state.greeksData.map(g => g.und))];
  const unds  = sel ? (allUnds.includes(sel) ? [sel] : []) : allUnds;
  const grid  = document.getElementById('greeks-all-grid');
  if (!unds.length) {
    grid.innerHTML = `<div style="padding:16px;color:var(--t4);font-size:13px;">No Greeks data — select a portfolio instrument above or check API response</div>`;
    return;
  }
  const cols = Math.min(unds.length * 4, 8);
  grid.style.gridTemplateColumns = `repeat(${cols}, 1fr)`;
  grid.innerHTML = unds.map(und => {
    const filt  = state.greeksData.filter(g => g.und === und);
    const delta = parseFloat(filt.reduce((s, g) => s + (g.delta || 0), 0).toFixed(4));
    const gamma = parseFloat(filt.reduce((s, g) => s + (g.gamma || 0), 0).toFixed(4));
    const theta = Math.round(filt.reduce((s, g) => s + (g.theta || 0), 0));
    const vega  = Math.round(filt.reduce((s, g) => s + (g.vega  || 0), 0));
    const ptMove = Math.abs(delta) * 100;
    const lbl = `<div style="font-family:var(--fm);font-size:9px;font-weight:600;color:var(--t4);letter-spacing:.06em;text-transform:uppercase;margin-bottom:4px;">${und}</div>`;
    return `
      <div class="greek-card">${lbl}<div class="greek-symbol">Δ</div><div class="greek-name">Net Delta</div>
        <div class="greek-val ${delta < 0 ? 'neg' : 'pos'}">${delta >= 0 ? '+' : ''}${delta}</div>
        <div class="greek-sub">${t('greeks.per_100pt')}${delta < 0 ? '−' : ''}₹${Math.abs(ptMove).toLocaleString('en-IN')}</div>
      </div>
      <div class="greek-card">${lbl}<div class="greek-symbol">Γ</div><div class="greek-name">${t('greeks.gamma')}</div>
        <div class="greek-val ${gamma < 0 ? 'neg' : 'pos'}">${gamma >= 0 ? '+' : ''}${gamma.toFixed(4)}</div>
        <div class="greek-sub">${gamma < 0 ? t('greeks.short_options') : t('greeks.long_options')} drive ${gamma < 0 ? t('greeks.negative_gamma') : t('greeks.positive_gamma')} gamma</div>
      </div>
      <div class="greek-card">${lbl}<div class="greek-symbol">Θ</div><div class="greek-name">${t('greeks.theta_day')}</div>
        <div class="greek-val ${theta >= 0 ? 'pos' : 'neg'}">${theta >= 0 ? '+₹' : '−₹'}${Math.abs(theta).toLocaleString('en-IN')}</div>
        <div class="greek-sub">${t('greeks.daily_decay')} ${theta >= 0 ? t('greeks.decay_earned') : t('greeks.decay_paid')}</div>
      </div>
      <div class="greek-card">${lbl}<div class="greek-symbol">V</div><div class="greek-name">${t('greeks.vega')}</div>
        <div class="greek-val ${vega >= 0 ? 'pos' : 'neg'}">${vega >= 0 ? '+₹' : '−₹'}${Math.abs(vega).toLocaleString('en-IN')}</div>
        <div class="greek-sub">${t('greeks.per_1pct_iv')}${und} ${vega >= 0 ? t('greeks.gains') : t('greeks.loses')} ₹${Math.abs(vega).toLocaleString('en-IN')}</div>
      </div>`;
  }).join('');
}

export function renderGreeksTable() {
  const sel = state.riskSelectedInstrument;
  const filtered = state.greeksData.filter(g =>
    (sel ? g.und === sel : true) &&
    (state.currentUnd === 'ALL' || g.und === state.currentUnd) &&
    (state.currentExpiry === 'ALL' || g.exp === state.currentExpiry)
  );
  const subEl = document.getElementById('greeks-table-sub');
  const noHedgeNote = filtered.length && filtered.every(g => g.theta === 0 && g.vega === 0 && g.gamma === 0)
    ? ' · Θ/V/Γ = 0 — add a hedge plan to see option Greeks' : '';
  subEl.textContent = (sel ? sel : (state.currentUnd === 'ALL' ? t('greeks.all_positions') : state.currentUnd + t('greeks.positions_suffix'))) + noHedgeNote;
  document.getElementById('greeks-tbody').innerHTML = filtered.map(g => {
    const dStr = g.delta >= 0 ? `+${g.delta}` : String(g.delta);
    const tStr = g.theta > 0 ? `+₹${g.theta}` : g.theta === 0 ? '₹0' : `−₹${Math.abs(g.theta)}`;
    const vStr = g.vega  > 0 ? `+₹${g.vega}`  : g.vega  === 0 ? '₹0' : `−₹${Math.abs(g.vega)}`;
    const instLabel = g.full ?? (g.und && g.hedge_type ? `${g.und} ${g.hedge_type}` : g.und ?? '—');
    const ivVal = g.ann_vol_pct != null ? parseFloat(g.ann_vol_pct).toFixed(1) + '%' : '—';
    return `<tr>
      <td>${instLabel}</td>
      <td><span style="font-family:var(--fm);font-size:10px;font-weight:500;padding:2px 7px;border-radius:3px;background:${g.und === 'NIFTY' ? 'var(--p02-bg)' : 'var(--p04-bg)'};color:${g.und === 'NIFTY' ? 'var(--p02)' : 'var(--p04)'};">${g.und ?? '—'}</span></td>
      <td><span class="exp-badge ${(g.exp ?? '').toLowerCase()}">${g.exp ?? '—'}</span></td>
      <td><span class="inst-badge ${(g.type ?? '').toLowerCase()}">${g.type ?? '—'}</span></td>
      <td><span class="side-badge ${(g.side ?? '').toLowerCase()}">${g.side ?? '—'}</span></td>
      <td class="${(g.delta ?? 0) >= 0 ? 'pos' : 'neg'} val">${dStr}</td>
      <td class="${(g.theta ?? 0) >= 0 ? 'pos' : 'neg'} val">${tStr}</td>
      <td class="${(g.vega  ?? 0) >= 0 ? 'pos' : 'neg'} val">${vStr}</td>
      <td class="val">${ivVal}</td>
    </tr>`;
  }).join('');
  const totDelta = filtered.reduce((s, g) => s + g.delta, 0);
  const totTheta = filtered.reduce((s, g) => s + g.theta, 0);
  const totVega  = filtered.reduce((s, g) => s + g.vega,  0);
  document.getElementById('greeks-footer').innerHTML = `
    <span class="lbl">${t('greeks.net_delta_lbl')}</span><span class="val ${pnlClass(totDelta)}">${totDelta >= 0 ? '+' : ''}${totDelta}</span>
    <span class="lbl">${t('greeks.net_theta_lbl')}</span><span class="val ${pnlClass(totTheta)}">${totTheta >= 0 ? '+₹' : '−₹'}${Math.abs(totTheta)}${t('greeks.per_day')}</span>
    <span class="lbl">${t('greeks.net_vega_lbl')}</span><span class="val ${pnlClass(totVega)}">${totVega >= 0 ? '+₹' : '−₹'}${Math.abs(totVega)}</span>`;
}

export function updateRiskSections() {
  const showNifty  = state.currentUnd !== 'BANKNIFTY';
  const showBnkn   = state.currentUnd !== 'NIFTY';
  const sideBySide = state.currentUnd === 'ALL';

  document.getElementById('payoff-nifty-wrap').style.display = showNifty ? '' : 'none';
  document.getElementById('payoff-bnkn-wrap').style.display  = showBnkn  ? '' : 'none';
  document.getElementById('payoff-charts-grid').style.gridTemplateColumns = sideBySide ? '1fr 1fr' : '1fr';

  // stress-card-sub is now set by renderStressScenarios() in stress.js
}
