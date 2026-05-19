// ── Dashboard section ─────────────────────────────────────────────────────────
import { state, activePositions } from './state.js';
import { fmt, fmtPnl, pnlClass } from './utils.js';
import { loadHistory } from './rr.js';
import { t } from '../shared/i18n.js';

export function renderDashboard() {
  renderDashKpis();
  renderMarketSnapshot();
  renderSegmentChart();
  renderDailyProgress();
  renderMovers();
}

export function renderDashKpis() {
  const filtered   = activePositions();
  const unreal     = filtered.reduce((s, p) => s + p.pnl, 0);
  const realized   = state.currentUnd === 'BANKNIFTY' ? 0 : state.realizedPnl;
  const net        = unreal + realized;
  const netDelta   = state.currentUnd === 'ALL'
    ? Object.values(state.portDelta).reduce((s, v) => s + v, 0)
    : (state.portDelta[state.currentUnd] || 0);
  const nCnt = state.positions.filter(p => p.und === 'NIFTY' && (state.currentExpiry === 'ALL' || p.exp === state.currentExpiry)).length;
  const bCnt = state.positions.filter(p => p.und === 'BANKNIFTY' && (state.currentExpiry === 'ALL' || p.exp === state.currentExpiry)).length;
  const subLine = state.currentUnd === 'ALL' ? `${nCnt} NIFTY · ${bCnt} BANKNIFTY`
                : `${filtered.length} ${state.currentUnd} positions`;
  const closedCnt = state.closedPositions.filter(p => state.currentUnd === 'ALL' || p.underlying === state.currentUnd).length;

  document.getElementById('dash-kpis').innerHTML = `
    <div class="kpi"><div class="kpi-label">${t('fno.active_positions')}</div><div class="kpi-value">${filtered.length}</div><div class="kpi-sub">${subLine}</div></div>
    <div class="kpi"><div class="kpi-label">${t('fno.unrealized_pnl')}</div><div class="kpi-value ${pnlClass(unreal)}">${fmtPnl(unreal)}</div><div class="kpi-sub">${t('fno.open_positions_sub')}</div></div>
    <div class="kpi"><div class="kpi-label">${t('fno.realized_pnl')}</div><div class="kpi-value ${pnlClass(realized)}">${fmtPnl(realized)}</div><div class="kpi-sub ${realized > 0 ? 'pos' : ''}">${state.currentUnd === 'BANKNIFTY' ? 'No closed BANKNIFTY trades' : `${closedCnt} closed trades`}</div></div>
    <div class="kpi"><div class="kpi-label">${t('fno.net_pnl')}</div><div class="kpi-value ${pnlClass(net)}">${fmtPnl(net)}</div><div class="kpi-sub">${t('fno.real_unreal')}</div></div>
    <div class="kpi"><div class="kpi-label">${t('fno.net_delta')}</div><div class="kpi-value ${netDelta < 0 ? 'neg' : 'pos'}">${netDelta > 0 ? '+' : ''}${netDelta}</div><div class="kpi-sub ${netDelta < 0 ? 'neg' : 'pos'}">${netDelta < 0 ? t('fno.net_short') : t('fno.net_long')}</div></div>
  `;
}

export function renderMarketSnapshot() {
  const grid = document.getElementById('mkt-grid');
  const underlyings = state.currentUnd === 'ALL'
    ? ['NIFTY', 'BANKNIFTY']
    : state.marketData[state.currentUnd] ? [state.currentUnd] : [];
  if (!underlyings.length) { grid.innerHTML = ''; return; }
  grid.className = `mkt-grid ${underlyings.length === 1 ? 'c1' : 'c2'}`;

  grid.innerHTML = underlyings.map(u => {
    const d        = state.marketData[u];
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

export function renderSegmentChart() {
  const expiries = state.currentExpiry !== 'ALL' ? [state.currentExpiry]
    : [...new Set(state.positions.map(p => p.exp))].sort();
  const sumPnl = (und, exp) => activePositions()
    .filter(p => (und === 'ALL' || p.und === und) && p.exp === exp)
    .reduce((s, p) => s + p.pnl, 0);

  let labels = [], data = [];
  if (state.currentUnd === 'NIFTY') {
    expiries.forEach(e => { labels.push(`NIFTY ${e}`); data.push(sumPnl('NIFTY', e)); });
    if (state.currentExpiry === 'ALL') { labels.push('Realized'); data.push(state.realizedPnl); }
  } else if (state.currentUnd === 'BANKNIFTY') {
    expiries.forEach(e => { labels.push(`BNKN ${e}`); data.push(sumPnl('BANKNIFTY', e)); });
  } else if (state.currentUnd !== 'ALL') {
    expiries.forEach(e => { labels.push(`${state.currentUnd} ${e}`); data.push(sumPnl(state.currentUnd, e)); });
  } else {
    expiries.forEach(e => {
      labels.push(`NIFTY ${e}`); data.push(sumPnl('NIFTY', e));
      labels.push(`BNKN ${e}`);  data.push(sumPnl('BANKNIFTY', e));
    });
    if (state.currentExpiry === 'ALL') { labels.push('Realized'); data.push(state.realizedPnl); }
  }

  const colors  = data.map(v => v >= 0 ? 'rgba(26,107,60,0.75)' : 'rgba(155,28,28,0.75)');
  const borders = data.map(v => v >= 0 ? '#1A6B3C' : '#9B1C1C');

  if (state.segChart) state.segChart.destroy();
  state.segChart = new Chart(document.getElementById('segment-chart'), {
    type: 'bar',
    data: { labels, datasets: [{ label: 'P&L (₹)', data, backgroundColor: colors, borderColor: borders, borderWidth: 1.5, borderRadius: 4 }] },
    options: {
      indexAxis: 'y', responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: d => fmtPnl(d.raw) } } },
      scales: {
        x: { grid: { color: 'rgba(0,0,0,.05)' }, ticks: { font: { family: 'IBM Plex Mono', size: 10 }, callback: v => `₹${(v / 1000).toFixed(0)}K` } },
        y: { grid: { display: false }, ticks: { font: { family: 'IBM Plex Mono', size: 11 } } }
      }
    }
  });
}

export function renderDailyProgress() {
  const canvas = document.getElementById('daily-progress-chart');
  if (!canvas) return;
  if (state.dpChart) { state.dpChart.destroy(); state.dpChart = null; }

  const history = loadHistory().filter(h => h.nifty && h.banknifty);
  if (!history.length) {
    document.getElementById('daily-progress-wrap').innerHTML =
      '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--t3);font-family:var(--fm);font-size:12px;">No history yet — data accumulates automatically each day you open this page.</div>';
    return;
  }

  const labels  = history.map(h => h.date);
  const netPnl  = history.map(h => (h.niftyPnl || 0) + (h.bnknPnl || 0));

  const base0N = history[0].nifty;
  const base0B = history[0].banknifty;
  const base0A = history.find(h => h.asml)?.asml || null;
  const niftyPct = history.map(h => +((h.nifty  / base0N - 1) * 100).toFixed(2));
  const bnknPct  = history.map(h => +((h.banknifty / base0B - 1) * 100).toFixed(2));
  const asmlPct  = base0A ? history.map(h => h.asml ? +((h.asml / base0A - 1) * 100).toFixed(2) : null) : null;

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
          type: 'line', label: 'NIFTY %', data: niftyPct,
          borderColor: '#0056B8', backgroundColor: 'transparent',
          borderWidth: 2, pointRadius: 3, pointHoverRadius: 5, tension: 0.3, yAxisID: 'yIdx', order: 1,
        },
        {
          type: 'line', label: 'BANKNIFTY %', data: bnknPct,
          borderColor: '#6B2FA0', backgroundColor: 'transparent',
          borderWidth: 2, pointRadius: 3, pointHoverRadius: 5, tension: 0.3, yAxisID: 'yIdx', order: 1,
        },
        ...(asmlPct ? [{
          type: 'line', label: 'ASML %', data: asmlPct,
          borderColor: '#92480A', backgroundColor: 'transparent',
          borderWidth: 2, pointRadius: 3, pointHoverRadius: 5, tension: 0.3, yAxisID: 'yIdx', order: 1,
          spanGaps: true,
        }] : []),
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

export function renderMovers() {
  const filtered = activePositions();
  const sorted = [...filtered].sort((a, b) => b.pnl - a.pnl);
  const top3 = sorted.slice(0, 3);
  const bot3 = sorted.slice(-3).reverse();
  document.getElementById('movers-sub').textContent = state.currentUnd === 'ALL' ? 'All underlyings' : state.currentUnd + ' positions';
  document.getElementById('movers-tbody').innerHTML = [
    ...top3.map(p => `<tr><td>${p.full}</td><td><span class="exp-badge ${p.exp.toLowerCase()}">${p.exp}</span></td><td><span class="side-badge ${p.side.toLowerCase()}">${p.side}</span></td><td class="pos">${fmtPnl(p.pnl)}</td></tr>`),
    `<tr><td colspan="4" style="padding:2px 12px;"><div style="border-top:1.5px dashed var(--border2);"></div></td></tr>`,
    ...bot3.map(p => `<tr><td>${p.full}</td><td><span class="exp-badge ${p.exp.toLowerCase()}">${p.exp}</span></td><td><span class="side-badge ${p.side.toLowerCase()}">${p.side}</span></td><td class="neg">${fmtPnl(p.pnl)}</td></tr>`)
  ].join('');
}
