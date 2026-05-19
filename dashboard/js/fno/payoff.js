// ── Payoff chart ──────────────────────────────────────────────────────────────
import { state } from './state.js';
import { fmtPnl } from './utils.js';

export function _buildPayoffChart(canvasId, pd, label, lineColor, spotLabel) {
  const labels = pd.labels || [];
  const data   = pd.data   || [];
  const el = document.getElementById(canvasId);
  if (!labels.length || !el) return null;
  return new Chart(el, {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label, data, borderColor: lineColor,
          backgroundColor: lineColor.replace(')', ',0.05)').replace('rgb', 'rgba'),
          borderWidth: 2.5, pointRadius: 3.5,
          pointBackgroundColor: data.map(v => v >= 0 ? '#1A6B3C' : '#9B1C1C'),
          tension: 0.3, fill: true
        },
        {
          label: 'Break-even', data: Array(labels.length).fill(0),
          borderColor: 'rgba(0,0,0,0.2)', borderWidth: 1, borderDash: [5, 4],
          pointRadius: 0, fill: false
        }
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { position: 'top', labels: { font: { family: 'IBM Plex Mono', size: 11 }, boxWidth: 10, padding: 14 } },
        tooltip: { callbacks: { label: d => fmtPnl(d.raw) } }
      },
      scales: {
        x: { grid: { display: false }, title: { display: true, text: spotLabel, font: { family: 'IBM Plex Mono', size: 10 } }, ticks: { font: { family: 'IBM Plex Mono', size: 10 } } },
        y: { grid: { color: 'rgba(0,0,0,.05)' }, ticks: { font: { family: 'IBM Plex Mono', size: 10 }, callback: v => `₹${(v / 1000).toFixed(0)}K` } }
      }
    }
  });
}

export function renderPayoffChart() {
  if (state.payoffChart)     { state.payoffChart.destroy();     state.payoffChart     = null; }
  if (state.payoffChartBnkn) { state.payoffChartBnkn.destroy(); state.payoffChartBnkn = null; }
  const niftyPd = state.payoffData.NIFTY     || (state.payoffData.labels ? state.payoffData : {});
  const bnknPd  = state.payoffData.BANKNIFTY || {};
  state.payoffChart     = _buildPayoffChart('payoff-chart',      niftyPd, 'Est. NIFTY P&L (₹)',     'rgb(0,86,184)',   'NIFTY Level');
  state.payoffChartBnkn = _buildPayoffChart('payoff-chart-bnkn', bnknPd,  'Est. BANKNIFTY P&L (₹)', 'rgb(107,47,160)', 'BANKNIFTY Level');
}
