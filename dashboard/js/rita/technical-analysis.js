// ── Technical Analysis ─────────────────────────────────────
import { api } from './api.js';
import { setEl } from './utils.js';
import { mkChart, destroyChart, C } from './charts.js';

function _getInstrument() {
  return (localStorage.getItem('ritaInstrument') || 'NIFTY').toUpperCase();
}

function _stateClass(state) {
  if (state === 'bullish' || state === 'up')   return 'pos';
  if (state === 'bearish' || state === 'down') return 'neg';
  return 'neu';
}

function _renderCommentary(data) {
  const el = document.getElementById('ta-commentary');
  if (!el) return;

  const summaryHtml = data.signal_summary.length
    ? data.signal_summary.map(item =>
        `<span class="kpi-pill ${_stateClass(item.state)}" style="margin-right:10px;font-size:13px;padding:4px 10px">
          <strong>${item.label}</strong> ${item.value}
        </span>`
      ).join('')
    : '';

  el.innerHTML = `
    <div style="font-size:11px;font-weight:600;color:var(--t2);margin-bottom:4px;text-transform:uppercase;letter-spacing:.5px">Agent Commentary — ${data.instrument}</div>
    <div style="font-size:13px;color:var(--t1);line-height:1.6;margin-bottom:12px">${data.commentary}</div>
    <div>${summaryHtml}</div>
  `;
}

export async function loadTechnicalAnalysis() {
  const inst = _getInstrument();

  // ── Commentary panel ────────────────────────────────────
  try {
    const commentary = await api(`/api/v1/experience/rita/technical-commentary?instrument=${inst}`);
    if (commentary) {
      _renderCommentary(commentary);
    } else {
      setEl('ta-commentary', '—');
    }
  } catch (e) {
    setEl('ta-commentary', '—');
  }

  // ── Chart data ───────────────────────────────────────────
  let rows = [];
  try {
    rows = await api(`/api/v1/market-signals?instrument=${inst}&timeframe=daily&periods=90`);
  } catch (e) {
    rows = [];
  }

  if (!rows || !rows.length) return;

  const dates = rows.map(r => r.date);

  // x-axis tick formatter (daily → MM-DD)
  const _xFmt   = v => typeof v === 'string' ? v.slice(5) : v;
  const _xTicks = 12;

  // ── Price + Volume chart ──────────────────────────────────
  try {
    mkChart('chart-ta-pv', {
      type: 'bar',
      data: {
        labels: dates,
        datasets: [
          { type: 'line', label: 'Close', data: rows.map(r => r.Close),
            borderColor: C.run, backgroundColor: 'transparent',
            pointRadius: 0, borderWidth: 2, yAxisID: 'yPrice', order: 1 },
          { type: 'bar', label: 'Volume', data: rows.map(r => r.Volume),
            backgroundColor: 'rgba(0,86,184,0.18)', borderWidth: 0,
            yAxisID: 'yVol', order: 2 },
        ]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { position: 'top', labels: { font: { size: 11 } } } },
        scales: {
          x: { grid: { display: false }, ticks: { maxTicksLimit: _xTicks, callback: _xFmt, font: { family: C.mono, size: 10 } } },
          yPrice: { position: 'left',  grid: { color: 'rgba(0,0,0,.04)' }, ticks: { callback: v => v.toFixed(0), font: { family: C.mono, size: 10 } } },
          yVol:   { position: 'right', grid: { display: false }, ticks: { callback: v => v >= 1e7 ? (v/1e7).toFixed(0)+'Cr' : v >= 1e5 ? (v/1e5).toFixed(0)+'L' : v, font: { family: C.mono, size: 10 } } },
        }
      }
    });
  } catch (e) { /* chart render failed silently */ }

  // ── ATR% chart ────────────────────────────────────────────
  try {
    const atrPctData = rows.map(r => {
      const a = parseFloat(r.atr_14), c = parseFloat(r.Close);
      return (!isNaN(a) && !isNaN(c) && c) ? +(a / c * 100).toFixed(3) : null;
    });
    mkChart('chart-ta-atr', {
      type: 'line',
      data: {
        labels: dates,
        datasets: [
          { label: 'ATR%', data: atrPctData,
            borderColor: C.warn, backgroundColor: 'rgba(146,72,10,0.07)',
            fill: true, tension: 0.2, pointRadius: 0, borderWidth: 2 }
        ]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          annotation: { annotations: {
            hiLine: { type: 'line', yMin: 1.5, yMax: 1.5, borderColor: 'rgba(155,28,28,0.55)', borderWidth: 1, borderDash: [4,3] },
            loLine: { type: 'line', yMin: 0.8, yMax: 0.8, borderColor: 'rgba(26,107,60,0.45)',  borderWidth: 1, borderDash: [4,3] },
          }}
        },
        scales: {
          x: { grid: { display: false }, ticks: { maxTicksLimit: _xTicks, callback: _xFmt, font: { family: C.mono, size: 10 } } },
          y: { grid: { color: 'rgba(0,0,0,.04)' }, ticks: { callback: v => v.toFixed(1)+'%', font: { family: C.mono, size: 10 } } }
        }
      }
    });
  } catch (e) { /* chart render failed silently */ }

  // ── Trend Score chart ─────────────────────────────────────
  try {
    const trendData = rows.map(r => r.trend_score != null ? +parseFloat(r.trend_score).toFixed(3) : null);
    mkChart('chart-ta-trend', {
      type: 'line',
      data: {
        labels: dates,
        datasets: [
          { label: 'Trend Score', data: trendData,
            borderColor: C.mon, backgroundColor: 'rgba(107,47,160,0.07)',
            fill: 'origin', tension: 0.25, pointRadius: 0, borderWidth: 2 }
        ]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          annotation: { annotations: {
            zero:  { type: 'line', yMin: 0,    yMax: 0,    borderColor: 'rgba(0,0,0,0.3)',      borderWidth: 1.5 },
            upMid: { type: 'line', yMin: 0.2,  yMax: 0.2,  borderColor: 'rgba(26,107,60,0.35)', borderWidth: 1, borderDash: [3,3] },
            dnMid: { type: 'line', yMin: -0.2, yMax: -0.2, borderColor: 'rgba(155,28,28,0.35)', borderWidth: 1, borderDash: [3,3] },
            upStr: { type: 'line', yMin: 0.5,  yMax: 0.5,  borderColor: 'rgba(26,107,60,0.6)',  borderWidth: 1, borderDash: [4,3] },
            dnStr: { type: 'line', yMin: -0.5, yMax: -0.5, borderColor: 'rgba(155,28,28,0.6)',  borderWidth: 1, borderDash: [4,3] },
          }}
        },
        scales: {
          x: { grid: { display: false }, ticks: { maxTicksLimit: _xTicks, callback: _xFmt, font: { family: C.mono, size: 10 } } },
          y: { min: -1, max: 1, grid: { color: 'rgba(0,0,0,.04)' }, ticks: { callback: v => v.toFixed(1), font: { family: C.mono, size: 10 } } }
        }
      }
    });
  } catch (e) { /* chart render failed silently */ }

  // ── EMA crossover + EMA chart ─────────────────────────────
  try {
    const n = rows.length;
    const crossUp = new Array(n).fill(null), crossDown = new Array(n).fill(null);
    for (let i = 1; i < n; i++) {
      const p = rows[i-1], c = rows[i];
      if (p.ema_5 != null && p.ema_13 != null && c.ema_5 != null && c.ema_13 != null) {
        if (p.ema_5 <= p.ema_13 && c.ema_5 > c.ema_13)       crossUp[i]   = (c.ema_5 + c.ema_13) / 2;
        else if (p.ema_5 >= p.ema_13 && c.ema_5 < c.ema_13)  crossDown[i] = (c.ema_5 + c.ema_13) / 2;
      }
    }
    mkChart('chart-ta-ema', {
      type: 'line',
      data: {
        labels: dates,
        datasets: [
          { label: 'Close',    data: rows.map(r => r.Close),  borderColor: 'rgba(100,181,246,0.7)', backgroundColor: 'transparent', pointRadius: 0, borderWidth: 1.5, borderDash: [3,3] },
          { label: 'EMA 5',   data: rows.map(r => r.ema_5),  borderColor: '#9C27B0',              backgroundColor: 'transparent', pointRadius: 0, borderWidth: 1.2, borderDash: [2,2] },
          { label: 'EMA 13',  data: rows.map(r => r.ema_13), borderColor: C.build,                backgroundColor: 'transparent', pointRadius: 0, borderWidth: 1.2, borderDash: [4,2] },
          { label: 'EMA 26',  data: rows.map(r => r.ema_26), borderColor: 'rgba(0,150,136,0.85)', backgroundColor: 'transparent', pointRadius: 0, borderWidth: 1.5, borderDash: [4,3] },
          { label: 'EMA 50',  data: rows.map(r => r.ema_50), borderColor: C.warn,                 backgroundColor: 'transparent', pointRadius: 0, borderWidth: 1.5, borderDash: [6,3] },
          { label: '▲ Bull X', data: crossUp,   type: 'line', showLine: false, spanGaps: false, pointStyle: 'triangle', pointRadius: 5, rotation: 0,   borderColor: '#1a6b3c', backgroundColor: '#1a6b3c', pointBorderColor: '#1a6b3c', pointBackgroundColor: '#1a6b3c' },
          { label: '▼ Bear X', data: crossDown, type: 'line', showLine: false, spanGaps: false, pointStyle: 'triangle', pointRadius: 5, rotation: 180, borderColor: '#9b1c1c', backgroundColor: '#9b1c1c', pointBorderColor: '#9b1c1c', pointBackgroundColor: '#9b1c1c' },
        ]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { position: 'top', labels: { font: { size: 11 }, boxWidth: 20 } } },
        scales: {
          x: { grid: { color: 'rgba(0,0,0,.03)' }, ticks: { maxTicksLimit: _xTicks, callback: _xFmt, font: { family: C.mono, size: 10 } } },
          y: { grid: { color: 'rgba(0,0,0,.04)' }, ticks: { callback: v => v.toFixed(0), font: { family: C.mono, size: 10 } } }
        }
      }
    });
  } catch (e) { /* chart render failed silently */ }

  // ── MACD chart ────────────────────────────────────────────
  try {
    const macdHist = rows.map(r => r.macd_hist);
    mkChart('chart-ta-macd', {
      type: 'bar',
      data: {
        labels: dates,
        datasets: [
          { type: 'line', label: 'MACD',   data: rows.map(r => r.macd),        borderColor: C.run,  backgroundColor: 'transparent', pointRadius: 0, borderWidth: 1.5, order: 1 },
          { type: 'line', label: 'Signal', data: rows.map(r => r.macd_signal), borderColor: C.warn, backgroundColor: 'transparent', pointRadius: 0, borderWidth: 1.5, borderDash: [3,2], order: 2 },
          { type: 'bar',  label: 'Hist',   data: macdHist, backgroundColor: macdHist.map(v => (v || 0) >= 0 ? 'rgba(26,107,60,0.55)' : 'rgba(155,28,28,0.55)'), borderWidth: 0, order: 3 },
        ]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { position: 'top', labels: { font: { size: 11 } } } },
        scales: {
          x: { grid: { display: false }, ticks: { maxTicksLimit: _xTicks, callback: _xFmt, font: { family: C.mono, size: 10 } } },
          y: { grid: { color: 'rgba(0,0,0,.04)' }, ticks: { callback: v => v.toFixed(1), font: { family: C.mono, size: 10 } } }
        }
      }
    });
  } catch (e) { /* chart render failed silently */ }

  // ── Bollinger Bands chart ─────────────────────────────────
  try {
    mkChart('chart-ta-bb', {
      type: 'line',
      data: {
        labels: dates,
        datasets: [
          { label: 'Upper', data: rows.map(r => r.bb_upper), borderColor: 'rgba(146,72,10,0.4)', backgroundColor: 'rgba(146,72,10,0.04)', fill: '+1', pointRadius: 0, borderWidth: 1, borderDash: [3,2] },
          { label: 'Close', data: rows.map(r => r.Close),    borderColor: C.run,                 backgroundColor: 'rgba(0,86,184,0.06)',  fill: false, pointRadius: 0, borderWidth: 2 },
          { label: 'Lower', data: rows.map(r => r.bb_lower), borderColor: 'rgba(146,72,10,0.4)', backgroundColor: 'rgba(146,72,10,0.04)', fill: '-1', pointRadius: 0, borderWidth: 1, borderDash: [3,2] },
        ]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { position: 'top', labels: { font: { size: 11 } } } },
        scales: {
          x: { grid: { color: 'rgba(0,0,0,.03)' }, ticks: { maxTicksLimit: _xTicks, callback: _xFmt, font: { family: C.mono, size: 10 } } },
          y: { grid: { color: 'rgba(0,0,0,.04)' }, ticks: { callback: v => v.toFixed(0), font: { family: C.mono, size: 10 } } }
        }
      }
    });
  } catch (e) { /* chart render failed silently */ }

  // ── RSI-14 chart ──────────────────────────────────────────
  try {
    mkChart('chart-ta-rsi', {
      type: 'line',
      data: {
        labels: dates,
        datasets: [
          { label: 'RSI-14', data: rows.map(r => r.rsi_14),
            borderColor: C.run, backgroundColor: 'rgba(0,86,184,0.06)',
            fill: true, tension: 0.2, pointRadius: 0, borderWidth: 2 },
        ]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          annotation: { annotations: {
            ob:  { type: 'line', yMin: 70, yMax: 70, borderColor: C.danger,               borderWidth: 1, borderDash: [4,3] },
            obz: { type: 'line', yMin: 60, yMax: 60, borderColor: 'rgba(180,40,40,0.4)',  borderWidth: 1, borderDash: [2,4] },
            os:  { type: 'line', yMin: 30, yMax: 30, borderColor: C.build,                borderWidth: 1, borderDash: [4,3] },
            osz: { type: 'line', yMin: 40, yMax: 40, borderColor: 'rgba(26,107,60,0.4)',  borderWidth: 1, borderDash: [2,4] },
          }}
        },
        scales: {
          x: { grid: { color: 'rgba(0,0,0,.03)' }, ticks: { maxTicksLimit: _xTicks, callback: _xFmt, font: { family: C.mono, size: 10 } } },
          y: { min: 0, max: 100, grid: { color: 'rgba(0,0,0,.04)' }, ticks: { callback: v => v, font: { family: C.mono, size: 10 } } }
        }
      }
    });
  } catch (e) { /* chart render failed silently */ }
}
