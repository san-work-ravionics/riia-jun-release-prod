// ── Stress scenarios ──────────────────────────────────────────────────────────
import { t } from '../shared/i18n.js';
import { state } from './state.js';
import { fmtPnl, pnlClass } from './utils.js';

export function computeFilteredStress() {
  const sel = state.riskSelectedInstrument;
  const filtered = state.greeksData.filter(g =>
    (sel ? g.und === sel : true) &&
    (state.currentUnd === 'ALL' || g.und === state.currentUnd) &&
    (state.currentExpiry === 'ALL' || g.exp === state.currentExpiry)
  );
  const moves = [-0.04, -0.02, 0.0, 0.02, 0.04];
  const refInst = sel || 'NIFTY';
  const refSpot = ((state.marketData[refInst] || state.marketData.NIFTY || {}).close) || 0;
  return moves.map(move => {
    let totalPnl = 0;
    filtered.forEach(g => {
      const spot = (state.marketData[g.und] || {}).close || 0;
      totalPnl += g.delta * spot * move;
    });
    return {
      move_pct:    move * 100,
      move_label:  (move > 0 ? '+' : '') + (move * 100).toFixed(0) + '%',
      nifty_level: refSpot ? Math.round(refSpot * (1 + move)) : null,
      ref_label:   refInst,
      pnl:         Math.round(totalPnl),
    };
  });
}

export function renderStressScenarios() {
  const sel = state.riskSelectedInstrument;
  const scenarios = computeFilteredStress();
  const subEl = document.getElementById('stress-card-sub');
  if (subEl) {
    const refInst = sel || 'NIFTY';
    const refSpot = (state.marketData[refInst] || state.marketData.NIFTY || {}).close;
    const spotStr = refSpot ? ` ~${refSpot.toLocaleString('en-IN', { maximumFractionDigits: 0 })}` : '';
    subEl.textContent = `${t('greeks.stress_sub')}${refInst}${spotStr}${sel ? '' : ' · all instruments'}`;
  }
  document.getElementById('stress-row').innerHTML = scenarios.map(s => {
    const isFlat = s.move_pct === 0;
    const instLbl = s.nifty_level ? `${s.ref_label} ~${s.nifty_level.toLocaleString('en-IN')}` : '—';
    return `<div class="scenario-card${isFlat ? ' flat' : ''}">
      <div class="scenario-move">${isFlat ? t('stress.flat') : s.move_label}</div>
      <div class="scenario-nifty">${instLbl}</div>
      <div class="scenario-pnl ${pnlClass(s.pnl)}">${fmtPnl(s.pnl)}</div>
    </div>`;
  }).join('');
  renderStdDevTable();
}

// ── Standard deviation range table — top of Risk page, acts as instrument selector ──
export function renderStdDevTable() {
  const el = document.getElementById('risk-stddev-card');
  if (!el) return;

  const positions = state.positions || [];
  const greeks    = state.greeksData || [];
  const mkt       = state.marketData || {};
  const sel       = state.riskSelectedInstrument;

  // Unique instruments from positions (price + vol)
  const seen = new Set();
  const instruments = [];
  for (const p of positions) {
    if (seen.has(p.und)) continue;
    seen.add(p.und);
    const d     = mkt[p.und];
    const price = d?.close ?? p.ltp ?? p.avg ?? null;
    const vol   = p.ann_vol_pct != null ? parseFloat(p.ann_vol_pct) / 100 : null;
    if (price == null || vol == null) continue;
    const cur = d?.currency ?? p.currency ?? 'INR';
    const sym = { EUR: '€', USD: '$', INR: '₹' }[cur] || '₹';
    instruments.push({ id: p.und, full: p.full || p.und, price, vol, sym });
  }

  // Portfolio summary row — allocation-weighted vol, total EUR value as price
  let portfolioInst = null;
  const portEur = state.portfolioMeta?.total_value_eur ?? null;
  if (portEur && greeks.length) {
    let wSum = 0, aSum = 0;
    for (const g of greeks) {
      if (g.ann_vol_pct != null && g.allocation_pct != null) {
        wSum += g.allocation_pct * g.ann_vol_pct;
        aSum += g.allocation_pct;
      }
    }
    if (aSum > 0) {
      portfolioInst = { id: 'Portfolio', full: 'Portfolio', price: portEur, vol: wSum / aSum / 100, sym: '€' };
    }
  }

  if (!instruments.length && !portfolioInst) { el.innerHTML = ''; return; }

  const fmtPrice = (v, sym, isPort) => {
    const opts = isPort
      ? { maximumFractionDigits: 0 }
      : { minimumFractionDigits: 2, maximumFractionDigits: 2 };
    return sym + v.toLocaleString('en-US', opts);
  };

  const tdNeg = (html, extra = '') =>
    `<td style="padding:6px 10px;font-size:11px;font-family:'IBM Plex Mono',monospace;color:var(--neg);${extra}">${html}</td>`;
  const tdPos = (html, extra = '') =>
    `<td style="padding:6px 10px;font-size:11px;font-family:'IBM Plex Mono',monospace;color:var(--pos);${extra}">${html}</td>`;
  const tdCtr = (html) =>
    `<td style="padding:6px 10px;font-size:12px;font-family:'IBM Plex Mono',monospace;border-left:1px solid var(--border);border-right:1px solid var(--border);">${html}</td>`;

  const renderRow = (inst, isPortfolio) => {
    const isSelected = sel === inst.id || (!sel && isPortfolio);
    const m1 = inst.vol * 1, m2 = inst.vol * 2, m3 = inst.vol * 3;
    const selStyle = isSelected
      ? 'background:color-mix(in srgb,var(--p02) 12%,transparent);outline:1px solid color-mix(in srgb,var(--p02) 30%,transparent);'
      : '';
    return `<tr style="cursor:pointer;${selStyle}" data-inst="${inst.id}" class="stddev-row">
      <td style="padding:6px 10px;font-size:12px;font-weight:${isPortfolio ? '700' : '600'};${isPortfolio ? 'color:var(--p02)' : ''}">${inst.full}</td>
      <td style="padding:6px 10px;font-size:11px;color:var(--t3);font-family:'IBM Plex Mono',monospace">${(inst.vol * 100).toFixed(1)}%</td>
      ${tdNeg(fmtPrice(inst.price * (1 - m3), inst.sym, isPortfolio))}
      ${tdNeg(fmtPrice(inst.price * (1 - m2), inst.sym, isPortfolio))}
      ${tdNeg(fmtPrice(inst.price * (1 - m1), inst.sym, isPortfolio))}
      ${tdCtr(fmtPrice(inst.price, inst.sym, isPortfolio))}
      ${tdPos(fmtPrice(inst.price * (1 + m1), inst.sym, isPortfolio))}
      ${tdPos(fmtPrice(inst.price * (1 + m2), inst.sym, isPortfolio))}
      ${tdPos(fmtPrice(inst.price * (1 + m3), inst.sym, isPortfolio))}
    </tr>`;
  };

  const allRows = [
    portfolioInst ? renderRow(portfolioInst, true) : '',
    ...instruments.map(inst => renderRow(inst, false)),
  ].join('');

  el.innerHTML = `
    <div class="card-hdr">
      <span class="card-title">Standard Deviation Price Ranges</span>
      <span class="card-sub">Click a row to filter Risk &amp; Greeks · Portfolio row uses allocation-weighted vol in EUR</span>
    </div>
    <div class="card-body" style="padding:0">
      <div class="tbl-wrap">
        <table>
          <thead><tr>
            <th>Instrument</th><th>Ann Vol</th>
            <th style="color:var(--neg)">−3σ</th>
            <th style="color:var(--neg)">−2σ</th>
            <th style="color:var(--neg)">−1σ</th>
            <th style="border-left:1px solid var(--border);border-right:1px solid var(--border)">Current</th>
            <th style="color:var(--pos)">+1σ</th>
            <th style="color:var(--pos)">+2σ</th>
            <th style="color:var(--pos)">+3σ</th>
          </tr></thead>
          <tbody>${allRows}</tbody>
          <tfoot><tr>
            <td colspan="2" style="padding:5px 10px;font-size:10px;color:var(--t4);font-family:'IBM Plex Mono',monospace">1σ 68.3% · 2σ 95.5% · 3σ 99.7% probability price stays within range</td>
            <td colspan="7"></td>
          </tr></tfoot>
        </table>
      </div>
    </div>`;

  el.querySelectorAll('.stddev-row').forEach(row => {
    row.addEventListener('click', () => {
      const id = row.dataset.inst;
      state.riskSelectedInstrument = id === 'Portfolio' ? null : id;
      document.dispatchEvent(new CustomEvent('risk-filter-change'));
    });
  });
}
