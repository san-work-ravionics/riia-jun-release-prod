// ── Stress scenarios ──────────────────────────────────────────────────────────
import { state } from './state.js';
import { fmtPnl, pnlClass } from './utils.js';

export function computeFilteredStress() {
  const filtered = state.greeksData.filter(g =>
    (state.currentUnd === 'ALL' || g.und === state.currentUnd) &&
    (state.currentExpiry === 'ALL' || g.exp === state.currentExpiry)
  );
  const moves = [-0.04, -0.02, 0.0, 0.02, 0.04];
  const niftySpot = (state.marketData.NIFTY || {}).close || 0;
  return moves.map(move => {
    let totalPnl = 0;
    filtered.forEach(g => {
      const spot = (state.marketData[g.und] || {}).close || 0;
      totalPnl += g.delta * spot * move;
    });
    return {
      move_pct:    move * 100,
      move_label:  (move > 0 ? '+' : '') + (move * 100).toFixed(0) + '%',
      nifty_level: niftySpot ? Math.round(niftySpot * (1 + move)) : null,
      pnl:         Math.round(totalPnl),
    };
  });
}

export function renderStressScenarios() {
  document.getElementById('stress-row').innerHTML = computeFilteredStress().map(s => {
    const isFlat = s.move_pct === 0;
    const niftyLbl = s.nifty_level ? `~${s.nifty_level.toLocaleString('en-IN')}` : '—';
    return `<div class="scenario-card${isFlat ? ' flat' : ''}">
      <div class="scenario-move">${isFlat ? 'Flat' : s.move_label}</div>
      <div class="scenario-nifty">${niftyLbl}</div>
      <div class="scenario-pnl ${pnlClass(s.pnl)}">${fmtPnl(s.pnl)}</div>
    </div>`;
  }).join('');
}
