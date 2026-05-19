// ── Chart registry & helpers ───────────────────────────────
import { openChartModal } from '../rita/chart-modal.js';

const _charts = {};

export function destroyChart(id) {
  if (_charts[id]) { _charts[id].destroy(); delete _charts[id]; }
}

export function mkChart(id, config) {
  destroyChart(id);
  const ctx = document.getElementById(id);
  if (!ctx) return null;
  _charts[id] = new Chart(ctx, config);

  // Attach expand-on-click to parent .chart-wrap (once only)
  const wrap = ctx.closest('.chart-wrap');
  if (wrap && !wrap.dataset.expandBound) {
    wrap.dataset.expandBound = '1';
    wrap.style.cursor = 'zoom-in';
    // Derive title from the .chart-title element inside the wrap
    wrap.addEventListener('click', () => {
      const titleEl = wrap.querySelector('.chart-title');
      const title = titleEl ? titleEl.textContent.trim() : '';
      openChartModal(id, title);
    });
  }

  return _charts[id];
}

// ── Chart.js shared defaults ───────────────────────────────
export const C = {
  cream: '#F5F3EE',
  build: '#1A6B3C',
  run: '#0056B8',
  mon: '#6B2FA0',
  warn: '#92480A',
  danger: '#9B1C1C',
  t3: '#8C877A',
  t4: '#B8B2A6',
  font: 'Epilogue, sans-serif',
  mono: 'IBM Plex Mono, monospace',
};
Chart.defaults.font.family = C.font;
Chart.defaults.font.size = 11;
Chart.defaults.color = C.t3;
if (window.ChartAnnotation) Chart.register(window.ChartAnnotation);

export function chartOpts(label, tickCb, labels) {
  const maxTicks = Math.min(8, Math.ceil(labels.length / 30));
  return {
    responsive: true, maintainAspectRatio: false,
    plugins: { legend: { position: 'top', labels: { usePointStyle: true, pointStyle: 'line', boxWidth: 24, font: { size: 11 } } } },
    scales: {
      x: { grid: { color: 'rgba(0,0,0,.035)' }, ticks: { maxTicksLimit: maxTicks, font: { family: C.mono, size: 10 } } },
      y: { grid: { color: 'rgba(0,0,0,.035)' }, ticks: { callback: tickCb, font: { family: C.mono, size: 10 } } },
    }
  };
}
