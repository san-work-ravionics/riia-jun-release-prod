// ── Dashboard section ─────────────────────────────────────────────────────────
import { state, activePositions } from './state.js';
import { fmtPnl, pnlClass } from './utils.js';
import { loadHistory } from './rr.js';
import { t } from '../shared/i18n.js';

export function renderDashKpis() {
  const filtered   = activePositions();
  const unreal     = filtered.reduce((s, p) => s + p.pnl, 0);
  const realized   = state.realizedPnl || 0;
  const net        = unreal + realized;
  const netDelta   = state.currentUnd === 'ALL'
    ? Object.values(state.portDelta).reduce((s, v) => s + v, 0)
    : (state.portDelta[state.currentUnd] || 0);
  const totalPnl   = (state.positions || []).reduce((s, p) => s + (p.pnl || 0), 0);

  // Sub-label: list all underlyings for ALL, or per-instrument count
  const undCounts = {};
  filtered.forEach(p => { undCounts[p.und] = (undCounts[p.und] || 0) + 1; });
  const subLine = state.currentUnd === 'ALL'
    ? Object.entries(undCounts).map(([u, c]) => `${c} ${u}`).join(' · ') || '—'
    : `${filtered.length} ${state.currentUnd} positions`;
  const closedCnt = state.closedPositions.filter(p => state.currentUnd === 'ALL' || p.underlying === state.currentUnd).length;

  // Portfolio Value from meta
  const totalVal = state.portfolioMeta?.total_value_eur;
  const valStr = totalVal != null
    ? '€' + parseFloat(totalVal).toLocaleString('en-EU', { maximumFractionDigits: 0 })
    : '—';
  const pnlSign = totalPnl >= 0 ? '+' : '';
  const pnlStr  = pnlSign + totalPnl.toLocaleString('en-EU', { maximumFractionDigits: 0 });

  document.getElementById('dash-kpis').innerHTML = `
    <div class="kpi"><div class="kpi-label">Portfolio Value</div><div class="kpi-value">${valStr}</div><div class="kpi-sub">saved portfolio</div></div>
    <div class="kpi"><div class="kpi-label">Total P&amp;L</div><div class="kpi-value ${pnlClass(totalPnl)}">${pnlStr}</div><div class="kpi-sub">all positions</div></div>
    <div class="kpi"><div class="kpi-label">${t('fno.active_positions')}</div><div class="kpi-value">${filtered.length}</div><div class="kpi-sub">${subLine}</div></div>
    <div class="kpi"><div class="kpi-label">${t('fno.unrealized_pnl')}</div><div class="kpi-value ${pnlClass(unreal)}">${fmtPnl(unreal)}</div><div class="kpi-sub">${t('fno.open_positions_sub')}</div></div>
    <div class="kpi"><div class="kpi-label">${t('fno.realized_pnl')}</div><div class="kpi-value ${pnlClass(realized)}">${fmtPnl(realized)}</div><div class="kpi-sub ${realized > 0 ? 'pos' : ''}">${closedCnt} closed trades</div></div>
    <div class="kpi"><div class="kpi-label">${t('fno.net_pnl')}</div><div class="kpi-value ${pnlClass(net)}">${fmtPnl(net)}</div><div class="kpi-sub">${t('fno.real_unreal')}</div></div>
    <div class="kpi"><div class="kpi-label">${t('fno.net_delta')}</div><div class="kpi-value ${netDelta < 0 ? 'neg' : 'pos'}">${netDelta > 0 ? '+' : ''}${netDelta.toFixed(2)}</div><div class="kpi-sub ${netDelta < 0 ? 'neg' : 'pos'}">${netDelta < 0 ? t('fno.net_short') : t('fno.net_long')}</div></div>
  `;
}

function _fmtEur(v) {
  return '€' + Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function _renderEquityCard(u, d) {
  const retChg   = parseFloat(d.chgFromOpen);
  const retClass = retChg >= 0 ? 'pos' : 'neg';
  return `<div class="kpi" style="border-left:3px solid var(--p03)">
    <div class="kpi-label">${u} · Equity · ${d.date}</div>
    <div class="kpi-value ${retClass}" style="font-size:18px">${_fmtEur(d.close)}</div>
    <div class="kpi-delta ${retClass}">${retChg >= 0 ? '▲ +' : '▼ '}${Math.abs(retChg).toFixed(2)}% · from ${_fmtEur(d.prevClose)}</div>
    <div class="kpi-sub" style="margin-top:5px;line-height:1.6">
      H ${_fmtEur(d.high)} · L ${_fmtEur(d.low)}<br>
      Vol 30d: ${d.vol_30d != null ? d.vol_30d.toFixed(1) + '%' : '—'} · ${d.shares}
    </div>
  </div>`;
}

export function renderMarketSnapshot() {
  const grid = document.getElementById('mkt-grid');
  if (!grid || grid.style.display === 'none') return;
  let underlyings;
  if (state.currentUnd === 'ALL') {
    underlyings = state.marketData['ASML']?._from_eq_hedge ? ['ASML'] : [];
  } else {
    underlyings = state.marketData[state.currentUnd] ? [state.currentUnd] : [];
  }
  if (!underlyings.length) { grid.innerHTML = ''; return; }
  const cols = underlyings.length >= 3 ? 'c3' : underlyings.length === 2 ? 'c2' : 'c1';
  grid.className = `mkt-grid ${cols}`;

  grid.innerHTML = underlyings.map(u => {
    const d = state.marketData[u];
    if (!d) return '';

    if (d._from_eq_hedge) return _renderEquityCard(u, d);

    const dayChg   = parseFloat(d.chgFromOpen);
    const prevChg  = d.chgFromPrev != null ? parseFloat(d.chgFromPrev) : null;
    const range    = d.high - d.low;
    const rangePct = Math.round(((d.close - d.low) / (d.high - d.low)) * 100);
    const prevPts  = prevChg != null ? (d.close - d.prevClose).toFixed(2) : null;
    const dayPts   = (d.close - d.open).toFixed(2);
    const prevLine = prevChg != null
      ? `<div class="mkt-chg ${prevChg >= 0 ? 'pos' : 'neg'}" style="margin-top:2px;">
           ${prevChg >= 0 ? '▲ +' : '▼ '}${Math.abs(prevChg).toFixed(2)}% vs prev close
           &nbsp;<span style="font-weight:400;opacity:.75">(${prevChg >= 0 ? '+' : ''}${prevPts} pts · prev ${d.prevClose.toLocaleString('en-IN', { minimumFractionDigits: 2 })})</span>
         </div>`
      : '';
    return `<div class="mkt-card ${u.toLowerCase()}">
      <div class="mkt-hdr">
        <span class="mkt-name">${u === 'BANKNIFTY' ? 'BANK NIFTY' : u}</span>
        <span class="mkt-date">${d.date}</span>
      </div>
      <div class="mkt-close">${d.close.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</div>
      ${prevLine}
      <div class="mkt-chg ${dayChg >= 0 ? 'pos' : 'neg'}" style="margin-top:2px;">
        ${dayChg >= 0 ? '▲ +' : '▼ '}${Math.abs(dayChg).toFixed(2)}% day move
        &nbsp;<span style="font-weight:400;opacity:.75">(${dayChg >= 0 ? '+' : ''}${dayPts} pts · open ${d.open.toLocaleString('en-IN', { minimumFractionDigits: 2 })})</span>
      </div>
      <div class="mkt-range-bar" style="margin-top:8px;"><div class="mkt-range-fill ${u.toLowerCase()}" style="left:0;width:${rangePct}%;"></div></div>
      <div class="mkt-ohlc">
        <div class="mkt-ohlc-item"><div class="mkt-ohlc-lbl">${t('fno.ohlc_open')}</div><div class="mkt-ohlc-val">${d.open.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</div></div>
        <div class="mkt-ohlc-item"><div class="mkt-ohlc-lbl">${t('fno.ohlc_high')}</div><div class="mkt-ohlc-val" style="color:var(--pos)">${d.high.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</div></div>
        <div class="mkt-ohlc-item"><div class="mkt-ohlc-lbl">${t('fno.ohlc_low')}</div><div class="mkt-ohlc-val" style="color:var(--neg)">${d.low.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</div></div>
        <div class="mkt-ohlc-item"><div class="mkt-ohlc-lbl">${t('fno.ohlc_close')}</div><div class="mkt-ohlc-val">${d.close.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</div></div>
      </div>
      <div class="mkt-stats">
        <span>Range: ${range.toFixed(2)} pts</span>
        <span>Vol: ${d.shares}</span>
        <span>T/O: ₹${d.turnover} Cr</span>
      </div>
    </div>`;
  }).join('');
}


export function renderDailyProgress() {
  const canvas = document.getElementById('daily-progress-chart');
  if (!canvas) return;
  if (state.dpChart) { state.dpChart.destroy(); state.dpChart = null; }

  const history = loadHistory().filter(h => h.asml);
  if (!history.length) {
    document.getElementById('daily-progress-wrap').innerHTML =
      '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--t3);font-family:var(--fm);font-size:12px;">No history yet — data accumulates automatically each day you open this page.</div>';
    return;
  }

  const labels = history.map(h => h.date);
  const netPnl = history.map(h => (h.niftyPnl || 0) + (h.bnknPnl || 0));
  const base0A = history[0].asml;
  const asmlPct = history.map(h => +((h.asml / base0A - 1) * 100).toFixed(2));

  const pnlColors  = netPnl.map(v => v >= 0 ? 'rgba(26,107,60,0.75)'  : 'rgba(155,28,28,0.75)');
  const pnlBorders = netPnl.map(v => v >= 0 ? '#1A6B3C' : '#9B1C1C');

  state.dpChart = new Chart(canvas, {
    data: {
      labels,
      datasets: [
        {
          type: 'bar', label: 'Net P&L (₹)', data: netPnl,
          backgroundColor: pnlColors, borderColor: pnlBorders,
          borderWidth: 1.5, borderRadius: 3, yAxisID: 'yPnl', order: 2,
        },
        {
          type: 'line', label: 'ASML %', data: asmlPct,
          borderColor: '#92480A', backgroundColor: 'transparent',
          borderWidth: 2, pointRadius: 3, pointHoverRadius: 5, tension: 0.3, yAxisID: 'yIdx', order: 1,
          spanGaps: true,
        },
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: {
          display: true, position: 'top',
          labels: { font: { family: 'IBM Plex Mono', size: 11 }, boxWidth: 12, padding: 14 }
        },
        tooltip: {
          callbacks: {
            label: ctx => ctx.dataset.yAxisID === 'yPnl'
              ? `Net P&L: ${fmtPnl(ctx.raw)}`
              : `${ctx.dataset.label}: ${ctx.raw >= 0 ? '+' : ''}${ctx.raw}%`
          }
        }
      },
      scales: {
        x: {
          grid: { display: false },
          ticks: { font: { family: 'IBM Plex Mono', size: 10 }, maxRotation: 0, maxTicksLimit: 10 }
        },
        yPnl: {
          position: 'left',
          grid: { color: 'rgba(0,0,0,.05)' },
          ticks: { font: { family: 'IBM Plex Mono', size: 10 }, callback: v => `₹${(v / 1000).toFixed(0)}K` }
        },
        yIdx: {
          position: 'right',
          grid: { drawOnChartArea: false },
          ticks: { font: { family: 'IBM Plex Mono', size: 10 }, callback: v => `${v >= 0 ? '+' : ''}${v}%` }
        }
      }
    }
  });
}

