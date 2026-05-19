// ── Training Progress ──────────────────────────────────────
import { api } from './api.js';
import { fmt, fmtPct, setEl } from './utils.js';
import { mkChart, C } from './charts.js';
import { createCache } from '../shared/api-cache.js';

const cachedApi = createCache(api);

export async function loadTrainProgress() {
  try {
    const rows = await cachedApi('/api/v1/experience/rita/training-history', 120000);
    if (!rows || !rows.length) {
      setEl('training-table-wrap', '<div class="empty">No training history found.</div>');
      return;
    }
    const labels = rows.map(r => 'Round ' + r.round);
    const valSharpe = rows.map(r => r.val_sharpe);
    const btSharpe = rows.map(r => r.backtest_sharpe);

    mkChart('chart-training-sharpe', {
      type: 'bar',
      data: {
        labels,
        datasets: [
          { label: 'Val Sharpe', data: valSharpe, backgroundColor: 'rgba(0,86,184,0.6)', borderRadius: 3 },
          { label: 'Backtest Sharpe', data: btSharpe, backgroundColor: 'rgba(26,107,60,0.65)', borderRadius: 3 },
        ]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { position: 'top', labels: { font: { size: 11 } } } },
        scales: {
          x: { grid: { display: false } },
          y: { grid: { color: 'rgba(0,0,0,.04)' }, ticks: { callback: v => v.toFixed(2), font: { family: C.mono, size: 10 } } }
        }
      }
    });

    setEl('training-table-wrap', `
      <table>
        <thead><tr><th>Round</th><th>Timestamp</th><th>Timesteps</th><th>Source</th><th>Val Sharpe</th><th>BT Sharpe</th><th>BT MDD</th><th>BT Return</th><th>BT CAGR</th><th>Constraints</th></tr></thead>
        <tbody>${rows.map(r => `
          <tr>
            <td class="td-mono">${r.round}</td>
            <td class="td-mono" style="font-size:11px">${(r.timestamp || '').slice(0, 16)}</td>
            <td class="td-mono">${r.timesteps != null ? Number(r.timesteps).toLocaleString() : '—'}</td>
            <td>${r.source || '—'}</td>
            <td class="td-mono">${fmt(r.val_sharpe, 3)}</td>
            <td class="td-mono" style="font-weight:600">${fmt(r.backtest_sharpe, 3)}</td>
            <td class="td-mono">${fmtPct(r.backtest_mdd_pct)}</td>
            <td class="td-mono">${fmtPct(r.backtest_return_pct)}</td>
            <td class="td-mono">${fmtPct(r.backtest_cagr_pct)}</td>
            <td>${r.backtest_constraints_met ? '<span class="badge ok">Met</span>' : '<span class="badge err">Not Met</span>'}</td>
          </tr>`).join('')}
        </tbody>
      </table>`);
  } catch (e) {
    setEl('training-table-wrap', '<div class="empty">Error loading training history.</div>');
  }
}
