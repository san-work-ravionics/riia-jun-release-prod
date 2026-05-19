// ── Explainability ─────────────────────────────────────────
import { api } from './api.js';
import { setEl } from './utils.js';
import { mkChart, C } from './charts.js';
import { t } from '../shared/i18n.js';

export async function loadExplain() {
  try {
    const rows = await api('/api/v1/shap');
    if (!rows || !rows.length) {
      setEl('shap-table-wrap', `<div class="empty">${t('explain.no_data')}</div>`);
      return;
    }
    const features = rows.map(r => r.feature);
    const overall = rows.map(r => parseFloat(r['Overall'] || 0));
    const cash = rows.map(r => parseFloat(r['Cash (0%)'] || 0));
    const half = rows.map(r => parseFloat(r['Half (50%)'] || 0));
    const full = rows.map(r => parseFloat(r['Full (100%)'] || 0));

    const hBar = (data, labels, colors) => ({
      type: 'bar',
      data: {
        labels,
        datasets: data.map((d, i) => ({
          label: d.label, data: d.vals,
          backgroundColor: colors[i], borderRadius: 3,
        }))
      },
      options: {
        indexAxis: 'y', responsive: true, maintainAspectRatio: false,
        plugins: { legend: { position: 'top', labels: { font: { size: 11 } } } },
        scales: {
          x: { grid: { color: 'rgba(0,0,0,.04)' }, ticks: { font: { family: C.mono, size: 10 }, callback: v => v.toFixed(4) } },
          y: { grid: { display: false }, ticks: { font: { size: 11 } } }
        }
      }
    });

    mkChart('chart-shap-overall', hBar(
      [{ label: 'Overall', vals: overall }],
      features, ['rgba(0,86,184,0.7)']
    ));

    mkChart('chart-shap-actions', hBar(
      [
        { label: 'Cash 0%', vals: cash },
        { label: 'Half 50%', vals: half },
        { label: 'Full 100%', vals: full },
      ],
      features, ['rgba(146,72,10,0.7)', 'rgba(0,86,184,0.7)', 'rgba(26,107,60,0.7)']
    ));

    setEl('shap-table-wrap', `
      <table>
        <thead><tr><th>${t('explain.col_feature')}</th><th>${t('explain.col_cash')}</th><th>${t('explain.col_half')}</th><th>${t('explain.col_full')}</th><th>${t('explain.col_overall')}</th></tr></thead>
        <tbody>${rows.map(r => `
          <tr>
            <td>${r.feature}</td>
            <td class="td-mono">${parseFloat(r['Cash (0%)'] || 0).toFixed(5)}</td>
            <td class="td-mono">${parseFloat(r['Half (50%)'] || 0).toFixed(5)}</td>
            <td class="td-mono">${parseFloat(r['Full (100%)'] || 0).toFixed(5)}</td>
            <td class="td-mono" style="font-weight:600">${parseFloat(r['Overall'] || 0).toFixed(5)}</td>
          </tr>`).join('')}
        </tbody>
      </table>`);
  } catch (e) {
    setEl('shap-table-wrap', `<div class="empty">${t('explain.error')}</div>`);
  }
}
