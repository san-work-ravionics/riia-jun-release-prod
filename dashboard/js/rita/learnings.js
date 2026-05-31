// ── Learnings ───────────────────────────────────────────────
import { t } from '../shared/i18n.js';
import { api } from './api.js';
import { mkChart, C } from './charts.js';

export function toggleLearnCard(id) {
  const body = document.getElementById('learn-body-' + id);
  const chev = document.getElementById('learn-chevron-' + id);
  if (!body) return;
  const open = body.style.display !== 'none';
  body.style.display = open ? 'none' : 'block';
  if (chev) chev.textContent = open ? '▶' : '▼';
}

export async function loadLearnings() {
  // Cards 1–3: placeholder only — content added by user separately
  // (no dynamic rendering needed; HTML is static in rita.html)

  // Card 4: Market Trends — live charts
  try {
    const rows = await api('/api/v1/market-signals?timeframe=daily&periods=252&instrument=ASML');
    if (!rows || !rows.length) {
      const c4 = document.getElementById('learn-body-trends');
      if (c4) c4.innerHTML = `<div class="empty">${t('learnings.no_data')}</div>`;
      return;
    }
    const dates = rows.map(r => r.date);
    const _xFmt = v => typeof v === 'string' ? v.slice(5) : v;

    mkChart('chart-learn-price', {
      type: 'line',
      data: {
        labels: dates,
        datasets: [{
          label: t('learnings.label_nifty_close'), data: rows.map(r => r.Close),
          borderColor: C.run, backgroundColor: 'rgba(0,86,184,0.07)',
          fill: true, tension: 0.2, pointRadius: 0, borderWidth: 2
        }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { position: 'top', labels: { font: { size: 11 } } } },
        scales: {
          x: { grid: { display: false }, ticks: { maxTicksLimit: 12, callback: _xFmt, font: { size: 10 } } },
          y: { grid: { color: 'rgba(0,0,0,.04)' }, ticks: { font: { size: 10 } } }
        }
      }
    });

    mkChart('chart-learn-rsi', {
      type: 'line',
      data: {
        labels: dates,
        datasets: [
          {
            label: 'RSI-14', data: rows.map(r => parseFloat(r.rsi_14)),
            borderColor: C.warn, backgroundColor: 'transparent',
            fill: false, tension: 0.2, pointRadius: 0, borderWidth: 2
          },
          {
            label: t('learnings.label_overbought'), data: rows.map(() => 60),
            borderColor: 'rgba(155,28,28,0.35)', borderDash: [4, 3],
            fill: false, pointRadius: 0, borderWidth: 1
          },
          {
            label: t('learnings.label_oversold'), data: rows.map(() => 30),
            borderColor: 'rgba(0,128,0,0.35)', borderDash: [4, 3],
            fill: false, pointRadius: 0, borderWidth: 1
          }
        ]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { position: 'top', labels: { font: { size: 11 } } } },
        scales: {
          x: { grid: { display: false }, ticks: { maxTicksLimit: 12, callback: _xFmt, font: { size: 10 } } },
          y: { min: 0, max: 100, grid: { color: 'rgba(0,0,0,.04)' }, ticks: { font: { size: 10 } } }
        }
      }
    });

  } catch (e) {
    console.warn('learnings chart error', e);
  }
}
