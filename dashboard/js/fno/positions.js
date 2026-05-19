// ── Positions section ─────────────────────────────────────────────────────────
import { state } from './state.js';
import { fmt, pnlClass } from './utils.js';

const _SYM = { EUR: '€', USD: '$', INR: '₹' };
const sym = (currency) => _SYM[currency] || '₹';

function fmtAmt(val, currency) {
  const s = sym(currency);
  if (val >= 0) return s + val.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return '-' + s + Math.abs(val).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function activeFiltered() {
  return state.positions.filter(p =>
    (state.currentUnd === 'ALL' || p.und === state.currentUnd) &&
    (state.currentExpiry === 'ALL' || p.exp === state.currentExpiry)
  );
}

export function renderPositionsKpis() {
  const filtered = activeFiltered();

  // Group by "UNDERLYING EXP" label (or just EXP when one instrument selected)
  const groups = {};
  filtered.forEach(p => {
    const key = state.currentUnd === 'ALL' ? `${p.und} ${p.exp}` : p.exp;
    if (!groups[key]) groups[key] = { label: key, pnl: 0, count: 0, currency: p.currency || 'INR' };
    groups[key].pnl += p.pnl;
    groups[key].count++;
  });

  const entries = Object.values(groups).sort((a, b) => a.label.localeCompare(b.label));
  const cols = Math.min(Math.max(entries.length, 1), 5);
  const kpiEl = document.getElementById('pos-kpis');
  kpiEl.className = `kpi-row c${cols}`;

  if (entries.length === 0) {
    const modeLabel = state.paperMode ? 'Paper' : 'Live';
    kpiEl.innerHTML = `<div class="kpi"><div class="kpi-label">No ${modeLabel} Positions</div><div class="kpi-value" style="font-size:14px;">—</div><div class="kpi-sub">No positions found for current filter</div></div>`;
    return;
  }

  kpiEl.innerHTML = entries.map(g => `
    <div class="kpi">
      <div class="kpi-label">${g.label}</div>
      <div class="kpi-value ${pnlClass(g.pnl)}">${fmtAmt(g.pnl, g.currency)}</div>
      <div class="kpi-sub">${g.count} position${g.count !== 1 ? 's' : ''}</div>
    </div>`).join('');
}

export function renderPositionsTable() {
  const hqsMap = {};
  ((state.hedgeQuality.positions) || []).forEach(h => { hqsMap[h.instrument] = h; });

  const filtered = activeFiltered().filter(p => {
    if (state.currentPosFilter === 'ALL') return true;
    return p.type === state.currentPosFilter;
  });

  document.getElementById('pos-tbody').innerHTML = filtered.map(p => {
    const chgClass = p.chg >= 0 ? 'pos' : 'neg';
    const currency = p.currency || 'INR';
    const s = sym(currency);
    const fmtPrice = (v) => p.type === 'FUT' ? s + fmt(v) : v.toFixed(2);

    let hqsCell = '<td></td>';
    if (p.type !== 'FUT' && p.side === 'Long') {
      const h = hqsMap[p.instrument];
      if (h) {
        const icon = { green: '🟢', yellow: '🟡', red: '🔴' }[h.hqs_tier];
        hqsCell = `<td><span class="hqs-badge ${h.hqs_tier}">${icon} ${h.hqs}</span></td>`;
      }
    }

    // DTE badge
    let dteBadge = '';
    if (p.expiry_date) {
      const dte = Math.ceil((new Date(p.expiry_date) - new Date()) / 86400000);
      if (dte >= 0) {
        const dteColor = dte <= 7 ? 'var(--neg)' : dte <= 21 ? 'var(--p03)' : 'var(--t3)';
        dteBadge = ` <span style="font-family:var(--fm);font-size:9px;color:${dteColor};margin-left:4px;">${dte}d</span>`;
      }
    }

    // SL distance badge
    let slBadge = '';
    if (p.sl_price != null) {
      const spotClose = (state.marketData[p.und] || {}).close;
      if (spotClose) {
        const distSl = ((p.sl_price - spotClose) / spotClose * 100).toFixed(1);
        slBadge = ` <span style="font-family:var(--fm);font-size:9px;color:var(--neg);background:var(--neg-bg);padding:1px 5px;border-radius:3px;margin-left:4px;">SL ${distSl}%</span>`;
      }
    }

    return `<tr>
      <td>${p.full}${dteBadge}${slBadge}</td>
      <td><span class="exp-badge ${p.exp.toLowerCase()}">${p.exp}</span></td>
      <td><span class="inst-badge ${p.type.toLowerCase()}">${p.type}</span></td>
      <td class="val">${p.strike ?? '—'}</td>
      <td><span class="side-badge ${p.side.toLowerCase()}">${p.side}</span></td>
      <td class="val">${fmt(p.qty)}</td>
      <td class="val">${fmtPrice(p.avg)}</td>
      <td class="val">${fmtPrice(p.ltp)}</td>
      <td class="${chgClass} val">${p.chg >= 0 ? '+' : ''}${p.chg.toFixed(2)}%</td>
      <td class="${pnlClass(p.pnl)}">${fmtAmt(p.pnl, currency)}</td>
      ${hqsCell}
    </tr>`;
  }).join('');

  const total = filtered.reduce((s, p) => s + p.pnl, 0);
  const currency = filtered.length ? (filtered[0].currency || 'INR') : 'INR';
  document.getElementById('pos-count-lbl').textContent = `${filtered.length} position${filtered.length !== 1 ? 's' : ''}`;
  const el = document.getElementById('pos-total');
  el.textContent = fmtAmt(total, currency);
  el.className = `val ${pnlClass(total)}`;

  // Update page sub-label
  const modeTag = state.paperMode
    ? '<span style="font-family:var(--fm);font-size:10px;font-weight:600;color:var(--p03);background:var(--p03-bg);padding:1px 6px;border-radius:3px;margin-left:6px;">PAPER</span>'
    : '<span style="font-family:var(--fm);font-size:10px;font-weight:600;color:var(--p01);background:var(--p01-bg);padding:1px 6px;border-radius:3px;margin-left:6px;">LIVE</span>';
  const sub = document.getElementById('pos-page-sub');
  if (sub) sub.innerHTML = `${filtered.length} active${modeTag}`;
}

export function filterPos(f, btn) {
  state.currentPosFilter = f;
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  renderPositionsTable();
}
