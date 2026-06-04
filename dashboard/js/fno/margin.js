// ── Margin Tracker section ────────────────────────────────────────────────────
import { t } from '../shared/i18n.js';
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
    <div class="kpi"><div class="kpi-label">${t('margin.assumed_ledger')}</div><div class="kpi-value">₹${(ledger / 100000).toFixed(0)}L</div><div class="kpi-sub">${t('margin.total_capital_est')}</div></div>
    <div class="kpi"><div class="kpi-label">${t('margin.span_margin')}</div><div class="kpi-value">₹${(span / 100000).toFixed(2)}L</div><div class="kpi-sub">${t('margin.span_sub')}</div></div>
    <div class="kpi"><div class="kpi-label">${t('margin.exposure_margin')}</div><div class="kpi-value">₹${(exp / 100000).toFixed(2)}L</div><div class="kpi-sub">${t('margin.exposure_sub')}</div></div>
    <div class="kpi"><div class="kpi-label">${t('margin.available')}</div><div class="kpi-value ${util > 75 ? 'warn' : 'pos'}">₹${(available / 100000).toFixed(2)}L</div><div class="kpi-sub ${util > 75 ? '' : 'pos'}">${(100 - util).toFixed(1)}${t('margin.pct_free')}${util > 75 ? t('margin.caution') : ''}</div></div>`;

  document.getElementById('margin-util-card').innerHTML = `
    <div class="card-hdr">
      <span class="card-title">${t('margin.utilization')}${state.currentUnd !== 'ALL' ? ' — ' + state.currentUnd : ''}</span>
      <span class="card-sub">₹${(total / 100000).toFixed(2)}L of ₹${(ledger / 100000).toFixed(0)}L estimated used · ${util}%</span>
    </div>
    <div class="card-body">
      <div style="display:flex;justify-content:space-between;font-family:var(--fm);font-size:11px;color:var(--t3);margin-bottom:4px;">
        <span>0%</span>
        <span style="color:var(--${utilClass === 'med' ? 'p03' : 'p01'});font-weight:600;">${util}${t('margin.pct_used')}${util > 80 ? t('margin.caution') : t('margin.healthy')}</span>
        <span>100%</span>
      </div>
      <div class="util-bar-outer"><div class="util-bar ${utilClass}" style="width:${util}%"></div></div>
      <div class="util-legend">
        <span><span class="util-swatch" style="background:var(--p01)"></span> ${t('margin.util_low')}</span>
        <span><span class="util-swatch" style="background:var(--p03)"></span> ${t('margin.util_med')}</span>
        <span><span class="util-swatch" style="background:var(--neg)"></span> ${t('margin.util_high')}</span>
      </div>
    </div>`;
}

export function updateMarginSections() {
  const asmlSection = document.getElementById('asml-margin-section');
  if (asmlSection) {
    asmlSection.style.display = state.equityHedgeData != null ? '' : 'none';
  }
  // Rebuild margin chart from API data (exclude EUR equity positions to keep INR scale clean)
  const byPos = (state.marginData.by_position || [])
    .filter(p => (state.currentUnd === 'ALL' || p.und === state.currentUnd) && (state.currentExpiry === 'ALL' || p.exp === state.currentExpiry))
    .filter(p => !p._from_eq_hedge)
    .filter(p => p.span > 0 || p.type === 'FUT');
  const cats  = byPos.map(p => p.full.length > 16 ? p.full.slice(0, 15) + '…' : p.full);
  const spanD = byPos.map(p => p.span);
  const expD  = byPos.map(p => p.exposure);

  if (state.marginChart) state.marginChart.destroy();
  state.marginChart = new Chart(document.getElementById('margin-chart'), {
    type: 'bar',
    data: { labels: cats, datasets: [
      { label: t('margin.label_span').replace(':', ''), data: spanD, backgroundColor: 'rgba(0,86,184,0.72)', borderRadius: 3 },
      { label: t('margin.label_exposure').replace(':', ''), data: expD, backgroundColor: 'rgba(146,72,10,0.72)', borderRadius: 3 }
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

  const subEl = document.getElementById('closed-card-sub');
  if (subEl) subEl.textContent = `Realized P&L: ${fmtPnl(state.realizedPnl)}`;

  const tbodyEl = document.getElementById('closed-tbody');
  if (!tbodyEl) return;
  tbodyEl.innerHTML = filtered.map(p => {
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
      <span class="lbl">${und} ${t('margin.label_span')}</span><span class="val">${fmtL(s.span || 0)}</span>
      <span class="lbl">${t('margin.label_exposure')}</span><span class="val">${fmtL(s.exposure || 0)}</span>
      <span class="lbl">${t('margin.label_total')}</span><span class="val" style="font-weight:700">${fmtL(s.total || 0)}</span>`;
  }

  // ASML equity hedge positions (EUR-denominated, separate from INR tables)
  if (state.equityHedgeData) {
    const fmtE = v => '€' + Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const instrument = (document.getElementById('eh-instrument')?.value || 'ASML').trim().toUpperCase();
    const asmlRows = (state.marginData.by_position || [])
      .filter(p => p._from_eq_hedge && (state.currentExpiry === 'ALL' || p.exp === state.currentExpiry));
    const asmlTbody = document.getElementById('asml-margin-tbody');
    const asmlFooter = document.getElementById('asml-margin-footer');
    if (asmlTbody) {
      asmlTbody.innerHTML = asmlRows.map(p => `<tr>
        <td>${p.full}</td>
        <td><span class="exp-badge">${p.exp}</span></td>
        <td><span class="inst-badge ${p.type.toLowerCase()}">${p.type}</span></td>
        <td><span class="side-badge ${p.side.toLowerCase()}">${p.side}</span></td>
        <td class="val">${p.qty}</td>
        <td class="val">${p.span > 0 ? fmtE(p.span) : '—'}</td>
        <td class="val">${p.exposure > 0 ? fmtE(p.exposure) : 'Premium paid'}</td>
        <td class="val" style="font-weight:600">${fmtE(p.total)}</td>
      </tr>`).join('');
    }
    if (asmlFooter) {
      const s = (state.marginData.summary || {})[instrument] || {};
      asmlFooter.innerHTML = `
        <span class="lbl">${instrument} SPAN:</span><span class="val">${fmtE(s.span || 0)}</span>
        <span class="lbl">Exposure:</span><span class="val">${fmtE(s.exposure || 0)}</span>
        <span class="lbl">Total (Est.):</span><span class="val" style="font-weight:700">${fmtE(s.total || 0)}</span>`;
    }
  }
}
