// ── Risk View ──────────────────────────────────────────────
import { api } from './api.js';
import { fmt, fmtPct, setEl } from './utils.js';
import { mkChart, C } from './charts.js';
import { createCache } from '../shared/api-cache.js';
import { t } from '../shared/i18n.js';

const cachedApi = createCache(api);

export async function loadRisk() {
  try {
    const rows = await cachedApi('/api/v1/experience/rita/risk-timeline', 60000);
    if (!rows || !rows.length) {
      setEl('risk-regime-wrap', `<div class="empty">${t('risk.no_data')}</div>`);
      return;
    }
    const last = rows[rows.length - 1] || {};
    setEl('r-var', fmtPct(last.market_var_95));
    setEl('r-pvar', fmtPct(last.portfolio_var_95));
    const latestVol = last.rolling_vol_20d;
    setEl('r-vol', latestVol != null ? fmt(latestVol, 2) + '%' : '—');
    const maxDd = Math.min(...rows.map(r => r.current_drawdown_pct || 0));
    setEl('r-dd', fmtPct(maxDd));

    const dates = rows.map(r => r.date);
    const vol = rows.map(r => r.rolling_vol_20d);
    const dd = rows.map(r => r.current_drawdown_pct);

    mkChart('chart-risk', {
      type: 'line',
      data: {
        labels: dates,
        datasets: [
          { label: 'Rolling Vol 20d (%)', data: vol, borderColor: C.warn, backgroundColor: 'rgba(146,72,10,0.06)', fill: true, tension: 0.3, pointRadius: 0, borderWidth: 1.5, yAxisID: 'y' },
          { label: 'Drawdown (%)', data: dd, borderColor: C.danger, backgroundColor: 'rgba(155,28,28,0.08)', fill: true, tension: 0.2, pointRadius: 0, borderWidth: 1.5, yAxisID: 'y2' },
        ]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { position: 'top', labels: { usePointStyle: true, font: { size: 11 } } } },
        scales: {
          x: { grid: { color: 'rgba(0,0,0,.035)' }, ticks: { maxTicksLimit: 8, font: { family: C.mono, size: 10 } } },
          y: { position: 'left', grid: { color: 'rgba(0,0,0,.035)' }, ticks: { callback: v => v.toFixed(1) + '%', font: { family: C.mono, size: 10 } } },
          y2: { position: 'right', grid: { display: false }, ticks: { callback: v => v.toFixed(1) + '%', font: { family: C.mono, size: 10 } } },
        }
      }
    });

    // Regime summary table
    const regimes = {};
    rows.forEach(r => {
      const rg = r.regime || 'Unknown';
      if (!regimes[rg]) regimes[rg] = { count: 0, alloc_sum: 0 };
      regimes[rg].count++;
      regimes[rg].alloc_sum += (r.allocation || 0);
    });
    setEl('risk-regime-wrap', `
      <table>
        <thead><tr><th>${t('risk.col_regime')}</th><th>${t('risk.col_days')}</th><th>${t('risk.col_pct_period')}</th><th>${t('risk.col_avg_alloc')}</th></tr></thead>
        <tbody>${Object.entries(regimes).map(([rg, v]) => `
          <tr>
            <td>${rg}</td>
            <td class="td-mono">${v.count}</td>
            <td class="td-mono">${((v.count / rows.length) * 100).toFixed(1)}%</td>
            <td class="td-mono">${((v.alloc_sum / v.count) * 100).toFixed(1)}%</td>
          </tr>`).join('')}
        </tbody>
      </table>`);
  } catch (e) {
    setEl('risk-regime-wrap', `<div class="empty">${t('risk.error')}</div>`);
  }
}
