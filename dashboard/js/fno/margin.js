// ── Margin Tracker section ────────────────────────────────────────────────────
import { state } from './state.js';
import { fmt, fmtPnl, pnlClass } from './utils.js';

export function renderMarginKpis() {
  const summary = (state.marginData.summary || {});
  const ledger  = state.marginData.ledger || 3500000;
  const utilMap = state.marginData.utilization || {};

  let span, exp, total, util;
  if (state.currentExpiry === 'ALL') {
    const key = state.currentUnd === 'ALL' ? 'ALL' : state.currentUnd;
    const s   = summary[key] || {};
    span  = s.span     || 0;
    exp   = s.exposure || 0;
    total = s.total    || 0;
    util  = utilMap[key] || 0;
  } else {
    const byPos = (state.marginData.by_position || [])
      .filter(p => (state.currentUnd === 'ALL' || p.und === state.currentUnd) && p.exp === state.currentExpiry);
    span  = byPos.reduce((s, p) => s + (p.span || 0), 0);
    exp   = byPos.reduce((s, p) => s + (p.exposure || 0), 0);
    total = byPos.reduce((s, p) => s + (p.total || 0), 0);
    util  = ledger > 0 ? Math.round(total / ledger * 100) : 0;
  }
  let available = Math.max(0, ledger - total);
  let utilClass = util < 60 ? 'low' : util < 80 ? 'med' : 'high';

  document.getElementById('margin-kpis').innerHTML = `
    <div class="kpi"><div class="kpi-label">Assumed Ledger</div><div class="kpi-value">₹${(ledger / 100000).toFixed(0)}L</div><div class="kpi-sub">Total capital estimate</div></div>
    <div class="kpi"><div class="kpi-label">SPAN Margin (Est.)</div><div class="kpi-value">₹${(span / 100000).toFixed(2)}L</div><div class="kpi-sub">Futures + short options</div></div>
    <div class="kpi"><div class="kpi-label">Exposure Margin (Est.)</div><div class="kpi-value">₹${(exp / 100000).toFixed(2)}L</div><div class="kpi-sub">~20% of SPAN</div></div>
    <div class="kpi"><div class="kpi-label">Available (Est.)</div><div class="kpi-value ${util > 75 ? 'warn' : 'pos'}">₹${(available / 100000).toFixed(2)}L</div><div class="kpi-sub ${util > 75 ? '' : 'pos'}">${(100 - util).toFixed(1)}% free${util > 75 ? ' — Caution' : ''}</div></div>`;

  document.getElementById('margin-util-card').innerHTML = `
    <div class="card-hdr">
      <span class="card-title">Margin Utilization${state.currentUnd !== 'ALL' ? ' — ' + state.currentUnd : ''}</span>
      <span class="card-sub">₹${(total / 100000).toFixed(2)}L of ₹${(ledger / 100000).toFixed(0)}L estimated used · ${util}%</span>
    </div>
    <div class="card-body">
      <div style="display:flex;justify-content:space-between;font-family:var(--fm);font-size:11px;color:var(--t3);margin-bottom:4px;">
        <span>0%</span>
        <span style="color:var(--${utilClass === 'med' ? 'p03' : 'p01'});font-weight:600;">${util}% used${util > 80 ? ' — Caution' : ' — Healthy'}</span>
        <span>100%</span>
      </div>
      <div class="util-bar-outer"><div class="util-bar ${utilClass}" style="width:${util}%"></div></div>
      <div class="util-legend">
        <span><span class="util-swatch" style="background:var(--p01)"></span> &lt;60% — Healthy</span>
        <span><span class="util-swatch" style="background:var(--p03)"></span> 60–80% — Caution</span>
        <span><span class="util-swatch" style="background:var(--neg)"></span> &gt;80% — Critical</span>
      </div>
    </div>`;
}

export function updateMarginSections() {
  document.getElementById('nifty-margin-section').style.display     = state.currentUnd === 'BANKNIFTY' ? 'none' : '';
  document.getElementById('banknifty-margin-section').style.display = state.currentUnd === 'NIFTY'     ? 'none' : '';
  // Rebuild margin chart from API data
  const byPos = (state.marginData.by_position || [])
    .filter(p => (state.currentUnd === 'ALL' || p.und === state.currentUnd) && (state.currentExpiry === 'ALL' || p.exp === state.currentExpiry))
    .filter(p => p.span > 0 || p.type === 'FUT');
  const cats  = byPos.map(p => p.full.length > 16 ? p.full.slice(0, 15) + '…' : p.full);
  const spanD = byPos.map(p => p.span);
  const expD  = byPos.map(p => p.exposure);

  if (state.marginChart) state.marginChart.destroy();
  state.marginChart = new Chart(document.getElementById('margin-chart'), {
    type: 'bar',
    data: { labels: cats, datasets: [
      { label: 'SPAN', data: spanD, backgroundColor: 'rgba(0,86,184,0.72)', borderRadius: 3 },
      { label: 'Exposure', data: expD, backgroundColor: 'rgba(146,72,10,0.72)', borderRadius: 3 }
    ] },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { position: 'top', labels: { font: { family: 'IBM Plex Mono', size: 11 }, boxWidth: 10, padding: 14 } } },
      scales: {
        x: { stacked: true, grid: { display: false }, ticks: { font: { family: 'IBM Plex Mono', size: 9 } } },
        y: { stacked: true, grid: { color: 'rgba(0,0,0,.05)' }, ticks: { font: { family: 'IBM Plex Mono', size: 10 }, callback: v => `₹${(v / 100000).toFixed(1)}L` } }
      }
    }
  });
}

export function renderClosedPositions() {
  const filtered = state.closedPositions.filter(p =>
    (state.currentUnd === 'ALL' || p.underlying === state.currentUnd) &&
    (state.currentExpiry === 'ALL' || (p.expiry || '').toUpperCase().includes(state.currentExpiry))
  );
  const total = filtered.reduce((s, p) => s + p.pnl, 0);

  document.getElementById('closed-card-sub').textContent =
    `Realized P&L: ${fmtPnl(state.realizedPnl)}`;

  document.getElementById('closed-tbody').innerHTML = filtered.map(p => {
    const typeCls = p.type.toLowerCase();
    return `<tr>
      <td>${p.full || p.instrument}</td>
      <td>${p.expDate || ''}</td>
      <td><span class="inst-badge ${typeCls}">${p.type}</span></td>
      <td class="val">${p.strike || '—'}</td>
      <td class="${pnlClass(p.pnl)}">${fmtPnl(p.pnl)}</td>
    </tr>`;
  }).join('');

  const footer = document.getElementById('closed-total');
  if (footer) { footer.textContent = fmtPnl(state.realizedPnl); footer.className = `val ${pnlClass(state.realizedPnl)}`; }
}

export function renderMarginTables() {
  const fmtL = v => `₹${(v / 100000).toFixed(2)}L`;
  const byPos = state.marginData.by_position || [];

  function fillTable(und, tbodyId, footerId) {
    const rows = byPos.filter(p => p.und === und && (state.currentExpiry === 'ALL' || p.exp === state.currentExpiry) && (p.span > 0 || p.type === 'FUT'));
    document.getElementById(tbodyId).innerHTML = rows.map(p => `<tr>
      <td>${p.full}</td>
      <td><span class="exp-badge ${p.exp.toLowerCase()}">${p.exp}</span></td>
      <td><span class="inst-badge ${p.type.toLowerCase()}">${p.type}</span></td>
      <td><span class="side-badge ${p.side.toLowerCase()}">${p.side}</span></td>
      <td class="val">${p.qty.toLocaleString('en-IN')}</td>
      <td class="val">${fmtL(p.span)}</td>
      <td class="val">${fmtL(p.exposure)}</td>
      <td class="val" style="font-weight:600">${fmtL(p.total)}</td>
    </tr>`).join('');
    const s = (state.marginData.summary || {})[und] || {};
    document.getElementById(footerId).innerHTML = `
      <span class="lbl">${und} SPAN:</span><span class="val">${fmtL(s.span || 0)}</span>
      <span class="lbl">Exposure:</span><span class="val">${fmtL(s.exposure || 0)}</span>
      <span class="lbl">Total:</span><span class="val" style="font-weight:700">${fmtL(s.total || 0)}</span>`;
  }

  fillTable('NIFTY',     'nifty-margin-tbody', 'nifty-margin-footer');
  fillTable('BANKNIFTY', 'bnkn-margin-tbody',  'bnkn-margin-footer');
}
