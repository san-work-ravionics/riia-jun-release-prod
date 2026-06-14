// ── Trade Journal ──────────────────────────────────────────
import { api } from './api.js';
import { setEl } from './utils.js';
import { mkChart, chartOpts, C } from './charts.js';
import { createCache } from '../shared/api-cache.js';
import { t } from '../shared/i18n.js';

const cachedApi = createCache(api);

export const TJ_PHASE = {
  Train:      { color: '#1565C0', bg: 'rgba(21,101,192,0.13)',  rowBg: '#E3F2FD' },
  Validation: { color: '#6A1B9A', bg: 'rgba(106,27,154,0.13)', rowBg: '#F3E5F5' },
  Backtest:   { color: '#2E7D32', bg: 'rgba(46,125,50,0.15)',   rowBg: '#E8F5E9' },
};
let _tjRows = [];  // cached for snapshot

export async function loadTrades() {
  try {
    const instrument = localStorage.getItem('ritaInstrument') || 'NIFTY';
    const [rows, history, perf, split] = await Promise.all([
      cachedApi(`/api/v1/experience/rita/risk-timeline?phase=all&instrument=${encodeURIComponent(instrument)}`, 60000),
      cachedApi(`/api/v1/experience/rita/training-history?instrument=${encodeURIComponent(instrument)}`, 120000).catch(() => []),
      cachedApi('/api/v1/performance-summary', 120000).catch(() => null),
      api(`/api/v1/training-split?instrument=${encodeURIComponent(instrument)}`).catch(() => null),
    ]);
    if (!rows || !rows.length) {
      setEl('trades-table-wrap', `<div class="empty">${t('trades.no_data')}</div>`);
      return;
    }
    _tjRows = rows;
    document.getElementById('btn-tj-download').style.display = '';

    const runs = Array.isArray(history) ? history : [];
    const latest = runs[0]; // newest-first

    const _fv  = v => (v != null && !isNaN(parseFloat(v))) ? parseFloat(v).toFixed(2) + '%' : '—';
    const _fs  = v => (v != null && !isNaN(parseFloat(v))) ? parseFloat(v).toFixed(3) : '—';
    const _fi  = v => (v != null && !isNaN(parseInt(v, 10))) ? parseInt(v, 10).toLocaleString() : '—';

    // ── Model info — same row as phase legend (trades-model-info in HTML) ───
    const miEl = document.getElementById('trades-model-info');
    if (miEl) {
      miEl.innerHTML = latest ? [
        `<span style="color:var(--t3)">Rounds</span>&nbsp;<strong>${runs.length}</strong>`,
        `<span style="color:var(--t3)">Algorithm</span>&nbsp;<strong>${latest.algorithm || 'DDQN'}</strong>`,
        `<span style="color:var(--t3)">Timesteps</span>&nbsp;<strong>${latest.timesteps ? (latest.timesteps / 1000).toFixed(0) + 'k' : '—'}</strong>`,
        `<span style="color:var(--t3)">Model ver</span>&nbsp;<strong>${latest.model_version || '—'}</strong>`,
      ].join('<span style="color:var(--t3);margin:0 2px">·</span>') : '';
    }

    // ── Phase legend labels — update with actual date ranges ─────────────────
    const _lbl = d => { if (!d) return null; const dt = new Date(d + 'T00:00:00'); return dt.toLocaleDateString('en-GB', { month: 'short', year: 'numeric' }); };
    if (split) {
      const trainLabel = document.getElementById('tj-label-train');
      const valLabel   = document.getElementById('tj-label-val');
      const btLabel    = document.getElementById('tj-label-bt');
      if (trainLabel && split.train_start && split.train_end)
        trainLabel.textContent = `Train (${_lbl(split.train_start)} – ${_lbl(split.train_end)})`;
      if (valLabel && split.val_start) {
        const valDisplayEnd = split.backtest_start || split.val_end;
        if (valDisplayEnd)
          valLabel.textContent = `Validation (${_lbl(split.val_start)} – ${_lbl(valDisplayEnd)})`;
      }
      if (btLabel && split.backtest_start && split.backtest_end)
        btLabel.textContent = `Backtest (${_lbl(split.backtest_start)} – ${_lbl(split.backtest_end)})`;
    }

    // ── Phase KPI cards ──────────────────────────────────────────────────────
    const cfgTr = TJ_PHASE['Train'];
    const cfgVa = TJ_PHASE['Validation'];
    const cfgBt = TJ_PHASE['Backtest'];

    const trainCard = latest ? `
      <div style="border:1px solid ${cfgTr.color};border-radius:7px;padding:12px 14px;background:${cfgTr.bg};height:100%">
        <div style="font-weight:700;color:${cfgTr.color};margin-bottom:8px;font-size:12px">${t('trades.train')}</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;font-size:11px">
          <div><span style="color:var(--t3)">${t('trades.label_sharpe')}</span><div style="font-weight:600">${_fs(latest.train_sharpe)}</div></div>
          <div><span style="color:var(--t3)">${t('trades.label_mdd')}</span><div style="font-weight:600">${_fv(latest.train_mdd_pct)}</div></div>
          <div><span style="color:var(--t3)">${t('trades.label_return')}</span><div style="font-weight:600">${_fv(latest.train_return_pct)}</div></div>
          <div><span style="color:var(--t3)">${t('trades.label_trades')}</span><div style="font-weight:600">${_fi(latest.train_trades)}</div></div>
        </div>
      </div>` : `<div style="border:1px solid ${cfgTr.color};border-radius:7px;padding:12px 14px;background:${cfgTr.bg}">
        <div style="font-weight:700;color:${cfgTr.color};margin-bottom:4px;font-size:12px">${t('trades.train')}</div>
        <div style="font-size:11px;color:var(--t3)">${t('trades.no_data_short')}</div>
      </div>`;

    const testCard = latest ? `
      <div style="border:1px solid ${cfgVa.color};border-radius:7px;padding:12px 14px;background:${cfgVa.bg};height:100%">
        <div style="font-weight:700;color:${cfgVa.color};margin-bottom:8px;font-size:12px">${t('trades.test')}</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;font-size:11px">
          <div><span style="color:var(--t3)">${t('trades.label_sharpe')}</span><div style="font-weight:600">${_fs(latest.val_sharpe)}</div></div>
          <div><span style="color:var(--t3)">${t('trades.label_mdd')}</span><div style="font-weight:600">${_fv(latest.val_mdd_pct)}</div></div>
          <div><span style="color:var(--t3)">${t('trades.label_return')}</span><div style="font-weight:600">${_fv(latest.val_return_pct)}</div></div>
          <div><span style="color:var(--t3)">${t('trades.label_trades')}</span><div style="font-weight:600">${_fi(latest.val_trades)}</div></div>
        </div>
      </div>` : `<div style="border:1px solid ${cfgVa.color};border-radius:7px;padding:12px 14px;background:${cfgVa.bg}">
        <div style="font-weight:700;color:${cfgVa.color};margin-bottom:4px;font-size:12px">${t('trades.test')}</div>
        <div style="font-size:11px;color:var(--t3)">${t('trades.no_data_short')}</div>
      </div>`;

    // Backtest — 8 metrics (4 from risk-timeline + 4 from training-history)
    const btRows = rows.filter(r => r.phase === 'Backtest');
    let backtestCard = '';
    if (btRows.length || latest) {
      const cashDays = btRows.filter(r => parseFloat(r.allocation || 0) === 0).length;
      const halfDays = btRows.filter(r => parseFloat(r.allocation || 0) === 0.5).length;
      const fullDays = btRows.filter(r => parseFloat(r.allocation || 0) >= 0.99).length;
      const maxDD    = btRows.length ? Math.min(...btRows.map(r => parseFloat(r.current_drawdown_pct || 0))) : null;

      // Use performance-summary for Sharpe/MDD/Return — same source as Performance page
      const btSharpe  = perf ? _fs(perf.sharpe_ratio) : '—';
      const btMdd     = perf ? _fv(perf.max_drawdown_pct) : '—';
      const btReturn  = perf ? _fv(perf.portfolio_total_return_pct) : '—';
      const btTrades  = perf ? _fi(perf.total_trades) : '—';

      backtestCard = `
        <div style="border:1px solid ${cfgBt.color};border-radius:7px;padding:12px 14px;background:${cfgBt.bg};height:100%">
          <div style="font-weight:700;color:${cfgBt.color};margin-bottom:8px;font-size:12px">${t('trades.backtest')}</div>
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:6px;font-size:11px">
            <div><span style="color:var(--t3)">${t('trades.label_days')}</span><div style="font-weight:600">${btRows.length || '—'}</div></div>
            <div><span style="color:var(--t3)">${t('trades.label_sharpe')}</span><div style="font-weight:600">${btSharpe}</div></div>
            <div><span style="color:var(--t3)">${t('trades.label_max_dd')}</span><div style="font-weight:600">${maxDD != null ? maxDD.toFixed(2) + '%' : '—'}</div></div>
            <div><span style="color:var(--t3)">${t('trades.label_mdd')}</span><div style="font-weight:600">${btMdd}</div></div>
            <div><span style="color:var(--t3)">${t('trades.label_cash')}</span><div style="font-weight:600">${cashDays}d</div></div>
            <div><span style="color:var(--t3)">${t('trades.label_return')}</span><div style="font-weight:600">${btReturn}</div></div>
            <div><span style="color:var(--t3)">${t('trades.label_half_full')}</span><div style="font-weight:600">${halfDays}d / ${fullDays}d</div></div>
            <div><span style="color:var(--t3)">${t('trades.label_trades')}</span><div style="font-weight:600">${btTrades}</div></div>
          </div>
        </div>`;
    }

    setEl('trades-kpi-strip', trainCard + testCard + backtestCard);

    // ── Chart — allocation over time ─────────────────────────────────────────
    const allDates = rows.map(r => r.date);

    const phases = Object.keys(TJ_PHASE);
    const datasets = phases.map(ph => {
      const cfg = TJ_PHASE[ph] || {};
      return {
        label: ph,
        data: rows.map(r => r.phase === ph && r.allocation != null ? parseFloat(r.allocation) * 100 : null),
        borderColor: cfg.color,
        backgroundColor: cfg.color,
        fill: false, stepped: false, pointRadius: 0, borderWidth: 2, spanGaps: false, tension: 0.3,
      };
    }).filter(d => d.data.some(v => v != null));

    mkChart('chart-allocation', {
      type: 'line',
      data: { labels: allDates, datasets },
      options: {
        ...chartOpts('Allocation (%)', v => v + '%', allDates),
        scales: {
          x: { ticks: { maxTicksLimit: 24, font: { family: C.mono, size: 10 } }, grid: { color: 'rgba(0,0,0,.04)' } },
          y: { min: 0, max: 110, ticks: { callback: v => v + '%', font: { family: C.mono, size: 10 } }, grid: { color: 'rgba(0,0,0,.04)' } },
        },
      },
    });

    // ── Table ────────────────────────────────────────────────────────────────
    setEl('trades-table-wrap', `
      <table>
        <thead><tr>
          <th>${t('trades.col_date')}</th><th>${t('trades.col_phase')}</th><th>${t('trades.col_allocation')}</th>
          <th>${t('trades.col_portfolio')}</th><th>${t('trades.col_drawdown')}</th><th>${t('trades.col_regime')}</th>
        </tr></thead>
        <tbody>${rows.map(r => {
          const cfg = TJ_PHASE[r.phase] || {};
          const portPct = r.portfolio_value_norm != null ? ((parseFloat(r.portfolio_value_norm) - 1) * 100).toFixed(2) + '%' : '—';
          const dd = r.current_drawdown_pct != null ? parseFloat(r.current_drawdown_pct).toFixed(2) + '%' : '—';
          const ddColor = parseFloat(r.current_drawdown_pct || 0) < -5 ? 'color:#9B1C1C;font-weight:600' : '';
          return `<tr>
            <td class="td-mono">${r.date || '—'}</td>
            <td><span style="font-size:10px;font-weight:700;color:${cfg.color || ''}">${r.phase || '—'}</span></td>
            <td>${allocBadge(r.allocation)}</td>
            <td class="td-mono">${portPct}</td>
            <td class="td-mono" style="${ddColor}">${dd}</td>
            <td style="font-size:11px;color:var(--t3)">${r.regime || '—'}</td>
          </tr>`;
        }).join('')}
        </tbody>
      </table>`);
  } catch (e) {
    setEl('trades-table-wrap', `<div class="empty">${t('trades.error')}</div>`);
  }
}

export function downloadTradeJournal() {
  if (!_tjRows.length) return;
  const cols = ['date', 'phase', 'allocation', 'portfolio_value_norm', 'current_drawdown_pct', 'regime'];
  const header = cols.join(',');
  const body = _tjRows.map(r => cols.map(c => r[c] ?? '').join(',')).join('\n');
  const ts = new Date().toISOString().slice(0, 19).replace(/[-:T]/g, c => c === 'T' ? '_' : c);
  const blob = new Blob([header + '\n' + body], { type: 'text/csv' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `trade_journal_${ts}.csv`;
  a.click();
}

export function allocBadge(v) {
  if (v == null) return '<span class="badge neu">—</span>';
  const pct = parseFloat(v) * 100;
  if (pct === 0) return `<span class="badge warn">${t('trades.hold')}</span>`;
  if (pct === 50) return `<span class="badge run">${t('trades.half')}</span>`;
  if (pct >= 99) return `<span class="badge ok">${t('trades.full')}</span>`;
  return `<span class="badge neu">${pct.toFixed(0)}%</span>`;
}
