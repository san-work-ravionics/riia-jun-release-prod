// ── Stress scenarios ──────────────────────────────────────────────────────────
import { t } from '../shared/i18n.js';
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
      <div class="scenario-move">${isFlat ? t('stress.flat') : s.move_label}</div>
      <div class="scenario-nifty">${niftyLbl}</div>
      <div class="scenario-pnl ${pnlClass(s.pnl)}">${fmtPnl(s.pnl)}</div>
    </div>`;
  }).join('');
  renderStdDevTable();
}

// ── Standard deviation range table (replaces historical events) ──────────────
// Renders 1σ / 2σ / 3σ price ranges with probabilities for each portfolio instrument.
export function renderStdDevTable() {
  const el = document.getElementById('stress-events-row');
  if (!el) return;

  const positions = state.positions || [];
  const mkt = state.marketData || {};

  // Unique instruments from positions (with current price + vol)
  const seen = new Set();
  const instruments = [];
  for (const p of positions) {
    if (seen.has(p.und)) continue;
    seen.add(p.und);
    const d = mkt[p.und];
    const price = d?.close ?? p.ltp ?? p.avg ?? null;
    const vol   = p.ann_vol_pct != null ? parseFloat(p.ann_vol_pct) / 100 : null;
    if (price == null || vol == null) continue;
    const cur   = d?.currency ?? p.currency ?? 'INR';
    const sym   = { EUR: '€', USD: '$', INR: '₹' }[cur] || '₹';
    instruments.push({ id: p.und, full: p.full || p.und, price, vol, sym });
  }

  if (!instruments.length) {
    el.innerHTML = '';
    return;
  }

  // σ bands: 1σ=68.27%, 2σ=95.45%, 3σ=99.73%
  const BANDS = [
    { sigma: 1, prob: '68.3%' },
    { sigma: 2, prob: '95.5%' },
    { sigma: 3, prob: '99.7%' },
  ];

  const fmtP = (v, sym) => sym + v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  const rows = instruments.map(inst => {
    const bandCells = BANDS.map(b => {
      const move = inst.vol * b.sigma;
      const lo = inst.price * (1 - move);
      const hi = inst.price * (1 + move);
      return `<td style="padding:6px 10px;font-size:11px;font-family:'IBM Plex Mono',monospace;color:var(--neg)">${fmtP(lo, inst.sym)}</td>
              <td style="padding:6px 10px;font-size:11px;font-family:'IBM Plex Mono',monospace;color:var(--pos)">${fmtP(hi, inst.sym)}</td>`;
    }).join('');
    return `<tr>
      <td style="padding:6px 10px;font-size:12px;font-weight:600">${inst.full}</td>
      <td style="padding:6px 10px;font-size:12px;font-family:'IBM Plex Mono',monospace">${fmtP(inst.price, inst.sym)}</td>
      <td style="padding:6px 10px;font-size:11px;color:var(--t3);font-family:'IBM Plex Mono',monospace">${(inst.vol * 100).toFixed(1)}%</td>
      ${bandCells}
    </tr>`;
  }).join('');

  el.innerHTML = `
    <div style="font-size:11px;font-weight:700;color:var(--t2);text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px">
      Standard Deviation Price Ranges
    </div>
    <div class="tbl-wrap">
      <table>
        <thead><tr>
          <th>Instrument</th>
          <th>Current Price</th>
          <th>Ann Vol</th>
          <th>−1σ Low</th><th>+1σ High</th>
          <th>−2σ Low</th><th>+2σ High</th>
          <th>−3σ Low</th><th>+3σ High</th>
        </tr></thead>
        <tfoot><tr>
          <td colspan="3" style="padding:5px 10px;font-size:10px;color:var(--t4);font-family:'IBM Plex Mono',monospace">1σ 68.3% · 2σ 95.5% · 3σ 99.7% probability price stays within range</td>
          <td colspan="6"></td>
        </tr></tfoot>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}
