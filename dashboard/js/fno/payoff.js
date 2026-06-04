// ── Payoff chart ──────────────────────────────────────────────────────────────
import { t } from '../shared/i18n.js';
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
          label: t('payoff.break_even'), data: Array(labels.length).fill(0),
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

  // ── Portfolio mode (analytics state — F30 Phase 3) ──────────────────────────
  const pd = state.payoffData;
  if (pd?.portfolio?.labels?.length) {
    // Hide BANKNIFTY wrap; relabel NIFTY wrap as "Portfolio Payoff at Expiry"
    const bnknWrap  = document.getElementById('payoff-bnkn-wrap');
    if (bnknWrap) bnknWrap.style.display = 'none';
    const niftyWrap = document.getElementById('payoff-nifty-wrap');
    if (niftyWrap) {
      const hdr = niftyWrap.querySelector('div[style]');
      if (hdr) hdr.textContent = 'Portfolio Payoff at Expiry';
    }

    const el = document.getElementById('payoff-chart');
    if (!el) return;

    const labels     = pd.portfolio.labels;
    const portData   = pd.portfolio.data   || [];
    const hedgedData = pd.hedged?.data     || [];

    state.payoffChart = new Chart(el, {
      type: 'line',
      data: {
        labels,
        datasets: [
          {
            label: 'Portfolio P&L',
            data: portData,
            borderColor: 'rgb(0,86,184)',
            backgroundColor: 'rgba(0,86,184,0.05)',
            borderWidth: 2.5, pointRadius: 3,
            pointBackgroundColor: portData.map(v => v >= 0 ? '#1A6B3C' : '#9B1C1C'),
            tension: 0.3, fill: true,
          },
          ...(hedgedData.length ? [{
            label: 'Hedged P&L',
            data: hedgedData,
            borderColor: 'rgb(26,107,60)',
            backgroundColor: 'rgba(26,107,60,0.05)',
            borderWidth: 2, pointRadius: 2, borderDash: [5, 3],
            tension: 0.3, fill: true,
          }] : []),
          {
            label: t('payoff.break_even'), data: Array(labels.length).fill(0),
            borderColor: 'rgba(0,0,0,0.2)', borderWidth: 1, borderDash: [5, 4],
            pointRadius: 0, fill: false,
          },
        ]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { position: 'top', labels: { font: { family: 'IBM Plex Mono', size: 11 }, boxWidth: 10, padding: 14 } },
          tooltip: { callbacks: { label: d => fmtPnl(d.raw) } }
        },
        scales: {
          x: { grid: { display: false }, title: { display: true, text: 'Price at Expiry', font: { family: 'IBM Plex Mono', size: 10 } }, ticks: { font: { family: 'IBM Plex Mono', size: 10 } } },
          y: { grid: { color: 'rgba(0,0,0,.05)' }, ticks: { font: { family: 'IBM Plex Mono', size: 10 }, callback: v => `₹${(v / 1000).toFixed(0)}K` } }
        }
      }
    });
    return;
  }

  // ── Legacy path: NIFTY / BANKNIFTY shape ────────────────────────────────────
  // Restore visibility in case a previous portfolio-mode run hid the bnkn wrap
  const bnknWrap = document.getElementById('payoff-bnkn-wrap');
  if (bnknWrap) bnknWrap.style.display = '';

  const niftyPd = pd?.NIFTY || (pd?.labels ? pd : {});
  const bnknPd  = pd?.BANKNIFTY || {};
  state.payoffChart     = _buildPayoffChart('payoff-chart',      niftyPd, t('payoff.nifty_pnl_label'),     'rgb(0,86,184)',   t('payoff.nifty_level'));
  state.payoffChartBnkn = _buildPayoffChart('payoff-chart-bnkn', bnknPd,  t('payoff.bnkn_pnl_label'), 'rgb(107,47,160)', t('payoff.bnkn_level'));
}
