import { api } from './api.js';
import { state } from './state.js';
import { mkChart } from '../shared/charts.js';

let _expRows = [];

export async function loadExperimentResults() {
  const wrap = document.getElementById('exp-results-wrap');
  if (!wrap) return;
  wrap.innerHTML = '<div class="empty">Loading…</div>';
  try {
    const instrument = (state.activeInst?.id) || localStorage.getItem('ritaInstrument') || 'NIFTY';
    const [rows, history, perf, split] = await Promise.all([
      api(`/api/v1/experience/rita/risk-timeline?phase=all&instrument=${encodeURIComponent(instrument)}`),
      api(`/api/v1/experience/rita/training-history?instrument=${encodeURIComponent(instrument)}`).catch(() => []),
      api('/api/v1/performance-summary').catch(() => null),
      api(`/api/v1/training-split?instrument=${encodeURIComponent(instrument)}`).catch(() => null),
    ]);
    if (!rows || !rows.length) {
      wrap.innerHTML = '<div class="empty">No trade records found — run the pipeline first.</div>';
      return;
    }
    _expRows = rows;
    const runs = Array.isArray(history) ? history : [];
    const latest = runs[0];
    const _fv = v => (v != null && !isNaN(parseFloat(v))) ? parseFloat(v).toFixed(2) + '%' : '—';
    const _fs = v => (v != null && !isNaN(parseFloat(v))) ? parseFloat(v).toFixed(3) : '—';
    const _fi = v => (v != null && !isNaN(parseInt(v, 10))) ? parseInt(v, 10).toLocaleString() : '—';
    const _lbl = d => { if (!d) return null; const dt = new Date(d + 'T00:00:00'); return dt.toLocaleDateString('en-GB', { month: 'short', year: 'numeric' }); };

    const PC = {
      Train:      { color: '#1565C0', bg: 'rgba(21,101,192,0.13)' },
      Validation: { color: '#6A1B9A', bg: 'rgba(106,27,154,0.13)' },
      Backtest:   { color: '#2E7D32', bg: 'rgba(46,125,50,0.15)'  },
    };

    const modelInfoHtml = latest ? `
      <div style="font-size:11px;color:var(--t3);margin-bottom:12px;display:flex;gap:16px;flex-wrap:wrap">
        <span><span>Rounds</span>&nbsp;<strong style="color:var(--text)">${runs.length}</strong></span>
        <span><span>Algorithm</span>&nbsp;<strong style="color:var(--text)">${latest.algorithm || 'DDQN'}</strong></span>
        <span><span>Timesteps</span>&nbsp;<strong style="color:var(--text)">${latest.timesteps ? (latest.timesteps / 1000).toFixed(0) + 'k' : '—'}</strong></span>
        <span><span>Model ver</span>&nbsp;<strong style="color:var(--text)">${latest.model_version || '—'}</strong></span>
      </div>` : '';

    const btRows = rows.filter(r => r.phase === 'Backtest');
    const cashDays = btRows.filter(r => parseFloat(r.allocation || 0) === 0).length;
    const halfDays = btRows.filter(r => parseFloat(r.allocation || 0) === 0.5).length;
    const fullDays = btRows.filter(r => parseFloat(r.allocation || 0) >= 0.99).length;
    const maxDD    = btRows.length ? Math.min(...btRows.map(r => parseFloat(r.current_drawdown_pct || 0))) : null;

    const trainCard = `
      <div style="border:1px solid ${PC.Train.color};border-radius:7px;padding:12px 14px;background:${PC.Train.bg}">
        <div style="font-weight:700;color:${PC.Train.color};margin-bottom:8px;font-size:12px">Train</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;font-size:11px">
          <div><span style="color:var(--t3)">Sharpe</span><div style="font-weight:600">${_fs(latest?.train_sharpe)}</div></div>
          <div><span style="color:var(--t3)">MDD %</span><div style="font-weight:600">${_fv(latest?.train_mdd_pct)}</div></div>
          <div><span style="color:var(--t3)">Return %</span><div style="font-weight:600">${_fv(latest?.train_return_pct)}</div></div>
          <div><span style="color:var(--t3)">Trades</span><div style="font-weight:600">${_fi(latest?.train_trades)}</div></div>
        </div>
      </div>`;

    const testCard = `
      <div style="border:1px solid ${PC.Validation.color};border-radius:7px;padding:12px 14px;background:${PC.Validation.bg}">
        <div style="font-weight:700;color:${PC.Validation.color};margin-bottom:8px;font-size:12px">Validation</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;font-size:11px">
          <div><span style="color:var(--t3)">Sharpe</span><div style="font-weight:600">${_fs(latest?.val_sharpe)}</div></div>
          <div><span style="color:var(--t3)">MDD %</span><div style="font-weight:600">${_fv(latest?.val_mdd_pct)}</div></div>
          <div><span style="color:var(--t3)">Return %</span><div style="font-weight:600">${_fv(latest?.val_return_pct)}</div></div>
          <div><span style="color:var(--t3)">Trades</span><div style="font-weight:600">${_fi(latest?.val_trades)}</div></div>
        </div>
      </div>`;

    const btCard = `
      <div style="border:1px solid ${PC.Backtest.color};border-radius:7px;padding:12px 14px;background:${PC.Backtest.bg}">
        <div style="font-weight:700;color:${PC.Backtest.color};margin-bottom:8px;font-size:12px">Backtest</div>
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:6px;font-size:11px">
          <div><span style="color:var(--t3)">Days</span><div style="font-weight:600">${btRows.length || '—'}</div></div>
          <div><span style="color:var(--t3)">Sharpe</span><div style="font-weight:600">${perf ? _fs(perf.sharpe_ratio) : '—'}</div></div>
          <div><span style="color:var(--t3)">Max DD</span><div style="font-weight:600">${maxDD != null ? maxDD.toFixed(2) + '%' : '—'}</div></div>
          <div><span style="color:var(--t3)">MDD %</span><div style="font-weight:600">${perf ? _fv(perf.max_drawdown_pct) : '—'}</div></div>
          <div><span style="color:var(--t3)">Cash</span><div style="font-weight:600">${cashDays}d</div></div>
          <div><span style="color:var(--t3)">Return %</span><div style="font-weight:600">${perf ? _fv(perf.portfolio_total_return_pct) : '—'}</div></div>
          <div><span style="color:var(--t3)">Half/Full</span><div style="font-weight:600">${halfDays}d / ${fullDays}d</div></div>
          <div><span style="color:var(--t3)">Trades</span><div style="font-weight:600">${perf ? _fi(perf.total_trades) : '—'}</div></div>
        </div>
      </div>`;

    const phaseCardsHtml = `<div style="display:grid;grid-template-columns:1fr 1fr 2fr;gap:14px;margin-bottom:16px">${trainCard}${testCard}${btCard}</div>`;

    const chartHtml = `
      <div class="chart-wrap">
        <div class="chart-title">Allocation Over Time (%)</div>
        <div class="chart-box h260"><canvas id="chart-exp-alloc"></canvas></div>
      </div>`;

    const tableHtml = `
      <div class="card">
        <div class="card-hdr"><span class="card-title">Allocation Timeline</span><span class="card-sub">${rows.length} rows</span></div>
        <div class="tbl-wrap">
          <table>
            <thead><tr>
              <th>Date</th><th>Phase</th><th>Allocation</th>
              <th>Portfolio (norm)</th><th>Drawdown %</th><th>Regime</th>
            </tr></thead>
            <tbody>${rows.map(r => {
              const cfg = PC[r.phase] || {};
              const portPct = r.portfolio_value_norm != null ? ((parseFloat(r.portfolio_value_norm) - 1) * 100).toFixed(2) + '%' : '—';
              const dd = r.current_drawdown_pct != null ? parseFloat(r.current_drawdown_pct).toFixed(2) + '%' : '—';
              const ddStyle = parseFloat(r.current_drawdown_pct || 0) < -5 ? 'color:var(--danger);font-weight:600' : '';
              const alloc = parseFloat(r.allocation || 0) * 100;
              const allocBadge = alloc === 0 ? '<span class="badge warn">HOLD 0%</span>'
                : alloc === 50 ? '<span class="badge run">HALF 50%</span>'
                : alloc >= 99 ? '<span class="badge ok">FULL 100%</span>'
                : `<span class="badge neu">${alloc.toFixed(0)}%</span>`;
              return `<tr>
                <td class="td-mono">${r.date || '—'}</td>
                <td><span style="font-size:10px;font-weight:700;color:${cfg.color || ''}">${r.phase || '—'}</span></td>
                <td>${allocBadge}</td>
                <td class="td-mono">${portPct}</td>
                <td class="td-mono" style="${ddStyle}">${dd}</td>
                <td style="font-size:11px;color:var(--t3)">${r.regime || '—'}</td>
              </tr>`;
            }).join('')}
            </tbody>
          </table>
        </div>
      </div>`;

    wrap.innerHTML = modelInfoHtml + phaseCardsHtml + chartHtml + tableHtml;

    const allDates = rows.map(r => r.date);
    const chartDatasets = Object.keys(PC).map(ph => ({
      label: ph,
      data: rows.map(r => r.phase === ph && r.allocation != null ? parseFloat(r.allocation) * 100 : null),
      borderColor: PC[ph].color,
      backgroundColor: PC[ph].color,
      fill: false, stepped: false, pointRadius: 0, borderWidth: 2, spanGaps: false, tension: 0.3,
    })).filter(d => d.data.some(v => v != null));

    mkChart('chart-exp-alloc',
      { type: 'line', data: { labels: allDates, datasets: chartDatasets },
        options: { responsive: true, maintainAspectRatio: false,
          plugins: { legend: { labels: { font: { family: "'IBM Plex Mono'", size: 10 } } } },
          scales: { y: { min: 0, max: 110, ticks: { callback: v => v + '%' } } } } }
    );

  } catch (e) {
    wrap.innerHTML = `<div class="empty">Error loading experiment results: ${e.message}</div>`;
  }
}

export function downloadExperimentResults() {
  if (!_expRows.length) { alert('No data loaded — navigate to Experiment Results first.'); return; }
  const cols = ['date', 'phase', 'allocation', 'portfolio_value_norm', 'current_drawdown_pct', 'regime'];
  const header = cols.join(',');
  const body = _expRows.map(r => cols.map(c => r[c] ?? '').join(',')).join('\n');
  const ts = new Date().toISOString().slice(0, 19).replace(/[T:]/g, c => c === 'T' ? '_' : c).replace(/-/g, '');
  const blob = new Blob([header + '\n' + body], { type: 'text/csv' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = `experiment_results_${ts}.csv`; a.click();
  URL.revokeObjectURL(a.href);
}
