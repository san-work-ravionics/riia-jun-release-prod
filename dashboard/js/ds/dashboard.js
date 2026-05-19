import { api } from './api.js';
import { DS_C, mkTbl, fmtPctRaw } from './utils.js';

const C = DS_C;

function fmt(v, dec=2) {
  if (v==null||v==='') return '—';
  const n = parseFloat(v);
  return isNaN(n) ? String(v) : n.toFixed(dec);
}

export async function loadDashboard() {
  try {
    api('/api/v1/experience/rita/training-history').then(hist => {
      if (!hist || !hist.length) return;
      const last = hist[hist.length - 1];
      const badge = document.getElementById('dash-run-badge');
      if (!badge) return;
      const parts = [];
      if (last.timestamp) parts.push(last.timestamp.slice(0,10));
      if (last.val_sharpe != null) parts.push('Val Sharpe ' + parseFloat(last.val_sharpe).toFixed(3));
      if (last.backtest_sharpe != null) parts.push('BT Sharpe ' + parseFloat(last.backtest_sharpe).toFixed(3));
      if (parts.length) { badge.textContent = parts.join(' · '); badge.style.display = ''; }
    }).catch(()=>{});

    const d = await api('/api/v1/performance-summary');
    const set = (id, v, cls) => { const e = document.getElementById(id); if(e){ e.textContent = v; if(cls) e.className = 'kpi-value ' + cls; } };

    const ret = parseFloat(d.portfolio_total_return_pct ?? d.total_return_pct ?? d.total_return ?? 0);
    set('d-return', fmtPctRaw(ret, 1), ret >= 0 ? 'pos' : 'neg');
    set('d-cagr',    fmtPctRaw(parseFloat(d.portfolio_cagr_pct ?? d.cagr_pct ?? d.cagr ?? 0), 1), '');
    const sharpe = parseFloat(d.sharpe_ratio ?? d.sharpe ?? 0);
    set('d-sharpe',  fmt(sharpe, 2), sharpe >= 1 ? 'pos' : sharpe >= 0 ? 'neu' : 'neg');
    const mdd = parseFloat(d.max_drawdown_pct ?? d.max_drawdown ?? 0);
    set('d-mdd',     fmtPctRaw(mdd, 1), 'neg');
    set('d-winrate', fmtPctRaw(parseFloat(d.win_rate_pct ?? d.win_rate ?? 0), 1), '');

    const constraintRows = [
      { name: 'Sharpe Ratio',  met: d.sharpe_constraint_met,   value: fmt(d.sharpe_ratio, 2),           threshold: '≥ 0.5' },
      { name: 'Max Drawdown',  met: d.drawdown_constraint_met,  value: fmtPctRaw(d.max_drawdown_pct, 1), threshold: '≤ -25%' },
      { name: 'All Constraints', met: d.constraints_met,        value: '',                                threshold: '' },
    ].filter(c => c.met !== undefined);

    if (constraintRows.length) {
      document.getElementById('dash-constraints').innerHTML = constraintRows.map(c => {
        const ok = String(c.met).toLowerCase() === 'true';
        const cls = ok ? 'ok' : 'err';
        return `<div class="alert-row ${cls}"><span class="alert-icon">${ok ? '✓' : '✗'}</span><span class="alert-msg">${c.name}${c.value ? ': ' + c.value : ''}</span><span class="alert-tag">${c.threshold}</span></div>`;
      }).join('');
    }

    api('/api/v1/experience/rita/training-history').then(hist => {
      if (!hist || !hist.length) return;
      const last = hist[hist.length - 1];
      const rows = [
        ['Round',            last.round],
        ['Timestamp',        last.timestamp],
        ['Timesteps',        last.timesteps?.toLocaleString()],
        ['Val Sharpe',       last.val_sharpe != null ? parseFloat(last.val_sharpe).toFixed(3) : null],
        ['Val CAGR',         last.val_cagr_pct != null ? fmtPctRaw(last.val_cagr_pct, 1) : null],
        ['Val Max DD',       last.val_mdd_pct != null ? fmtPctRaw(last.val_mdd_pct, 1) : null],
        ['Backtest Sharpe',  last.backtest_sharpe != null ? parseFloat(last.backtest_sharpe).toFixed(3) : null],
        ['Backtest Return',  last.backtest_return_pct != null ? fmtPctRaw(last.backtest_return_pct, 1) : null],
        ['Backtest CAGR',    last.backtest_cagr_pct != null ? fmtPctRaw(last.backtest_cagr_pct, 1) : null],
        ['Trade Count',      last.backtest_trade_count],
        ['Notes',            last.notes],
      ].filter(([, v]) => v != null && v !== '' && v !== 'null');
      document.getElementById('dash-goal').innerHTML = '<div style="padding:2px 0">' +
        rows.map(([k, v]) => `<div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid var(--border);font-size:12px"><span style="color:var(--t3)">${k}</span><span style="font-family:var(--fm);font-weight:500">${v}</span></div>`).join('') +
        '</div>';
    }).catch(() => {});

  } catch(e) { console.warn('Dashboard:', e); }
}
