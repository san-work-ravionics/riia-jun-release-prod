// ── Shared hedge charts — monthly OHLC candles + MoM % change (F39) ──────────
// Extracted verbatim from equity_hedge.js renderEquityHedge() so the Equity Hedge page
// and the Hedge Workflow Exposure step draw identical charts. Chart-only: takes canvas
// ids + data, owns no module state — callers keep the returned Chart instance and pass
// it back as `prev` so it is destroyed before redraw. Uses the global Chart (Chart.js).
//
// daily = [{date:'YYYY-MM-DD', price:number}, ...] (equity-hedge-scenarios portfolio.daily).

const _MONTHS = ['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'];
const _cf = 'Epilogue, sans-serif';
const _cm = 'IBM Plex Mono, monospace';
const _gridClr = 'rgba(0,0,0,.035)';
const _cWarn = '#92480A';
const _cDanger = '#9B1C1C';
const _cBuild = '#1A6B3C';
const _cBlue = '#0056B8'; // same blue as the MoM bars (rgba(0,86,184,…))
const _cT3 = '#8C877A';
const _legendCfg = { position: 'top', labels: { usePointStyle: true, pointStyle: 'line', boxWidth: 24, font: { family: _cf, size: 11 } } };

function _monthLabel(m) {
  const [y, mo] = m.split('-');
  return _MONTHS[parseInt(mo, 10) - 1] + ' ' + y.slice(2);
}

function _byMonth(daily) {
  const byMonth = {};
  for (const d of daily) {
    const key = d.date.slice(0, 7);
    if (!byMonth[key]) byMonth[key] = [];
    byMonth[key].push(d.price);
  }
  return byMonth;
}

function _canvas(id) {
  return typeof document !== 'undefined' ? document.getElementById(id) : null;
}

// Pure: monthly OHLC candles from daily closes.
export function buildMonthlyCandles(daily) {
  const byMonth = _byMonth(daily);
  const monthKeys = Object.keys(byMonth).sort();
  const candles = monthKeys.map(k => {
    const prices = byMonth[k];
    return { o: prices[0], h: Math.max(...prices), l: Math.min(...prices), c: prices.at(-1) };
  });
  return { monthKeys, candles };
}

// Pure: month-over-month close-to-close % change + population std-dev / mean.
export function buildMonthlyChanges(daily) {
  const byMonth = _byMonth(daily);
  const months = Object.keys(byMonth).sort();
  const labels = [];
  const changes = [];
  for (let i = 1; i < months.length; i++) {
    const prevClose = byMonth[months[i - 1]].at(-1);
    const curClose  = byMonth[months[i]].at(-1);
    if (prevClose > 0) {
      labels.push(months[i]);
      changes.push(((curClose - prevClose) / prevClose) * 100);
    }
  }
  const mean = changes.reduce((s, v) => s + v, 0) / (changes.length || 1);
  const stdDev = Math.sqrt(changes.reduce((s, v) => s + (v - mean) ** 2, 0) / (changes.length || 1));
  return { labels, changes, mean, stdDev };
}

// Monthly candlesticks. opts: { fmt (price formatter), bands: [{label, value, color,
// dash}] horizontal reference lines (e.g. the monthly −1σ price level), beginAtZero
// (default true = original Chart.js bar behaviour; the Exposure step passes false so the
// candles fill the plot instead of being squashed at the top), prev }.
// Returns the new Chart (or null when no canvas / not enough data).
export function renderMonthlyCandles(canvasId, daily, opts = {}) {
  const fmt = opts.fmt || (v => Number(v).toFixed(2));
  const bands = opts.bands || [];
  if (opts.prev) opts.prev.destroy();
  const ctx = _canvas(canvasId);
  if (!ctx || !daily || daily.length <= 1) return null;

  const { monthKeys, candles } = buildMonthlyCandles(daily);
  const labels = monthKeys.map(_monthLabel);
  const bodyColors = candles.map(c => c.c >= c.o ? _cBuild : _cDanger);

  const wickPlugin = {
    id: 'candlestickWicks',
    afterDatasetsDraw(chart) {
      const { ctx: c2d } = chart;
      const meta = chart.getDatasetMeta(0);
      meta.data.forEach((bar, i) => {
        const c = candles[i];
        const yHigh = chart.scales.y.getPixelForValue(c.h);
        const yLow  = chart.scales.y.getPixelForValue(c.l);
        const xCenter = bar.x;
        c2d.save();
        c2d.beginPath();
        c2d.strokeStyle = c.c >= c.o ? _cBuild : _cDanger;
        c2d.lineWidth = 1.5;
        c2d.moveTo(xCenter, yHigh);
        c2d.lineTo(xCenter, yLow);
        c2d.stroke();
        c2d.restore();
      });
    },
  };

  const datasets = [{
    label: 'Body',
    data: candles.map(c => [Math.min(c.o, c.c), Math.max(c.o, c.c)]),
    backgroundColor: bodyColors,
    borderColor: bodyColors,
    borderWidth: 1,
    borderSkipped: false,
    barPercentage: 0.9,
    categoryPercentage: 0.9,
  }];
  for (const b of bands) {
    datasets.push({
      label: b.label, data: Array(labels.length).fill(b.value), type: 'line',
      borderColor: b.color || _cDanger, borderWidth: 1.25, borderDash: b.dash || [6, 4],
      pointRadius: 0, fill: false, order: 1,
    });
  }

  return new Chart(ctx, {
    type: 'bar',
    data: { labels, datasets },
    plugins: [wickPlugin],
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: bands.length
          ? { ..._legendCfg, labels: { ..._legendCfg.labels, filter: it => it.text !== 'Body' } }
          : { display: false },
        tooltip: {
          callbacks: {
            title: c => c[0].label,
            label: c => {
              if (c.dataset.type === 'line') return `${c.dataset.label}: ${fmt(c.raw)}`;
              const k = candles[c.dataIndex];
              return [`O: ${fmt(k.o)}  H: ${fmt(k.h)}`, `L: ${fmt(k.l)}  C: ${fmt(k.c)}`];
            },
          },
        },
      },
      scales: {
        x: { grid: { color: _gridClr }, ticks: { font: { family: _cm, size: 10 } } },
        y: { beginAtZero: opts.beginAtZero !== false, grid: { color: _gridClr }, ticks: { font: { family: _cm, size: 10 }, callback: v => fmt(v) } },
      },
    },
  });
}

// Monthly MoM % change bars with ±1σ (empirical) and mean lines. opts: { titleId,
// title, prev, sigmaOnly } — sigmaOnly draws only the ±1σ dotted pair (no mean line). Returns the new Chart (or null).
export function renderMonthlyChange(canvasId, daily, opts = {}) {
  if (opts.prev) opts.prev.destroy();
  const ctx = _canvas(canvasId);
  if (!ctx || !daily || daily.length <= 1) return null;
  if (opts.titleId && opts.title != null) {
    const titleEl = _canvas(opts.titleId);
    if (titleEl) titleEl.textContent = opts.title;
  }

  const { labels, changes, mean, stdDev } = buildMonthlyChanges(daily);
  const upper1 = mean + stdDev;
  const lower1 = mean - stdDev;
  const barColors = changes.map(v => (Math.abs(v) > stdDev) ? 'rgba(155,28,28,0.65)' : 'rgba(0,86,184,0.55)');
  const lineDs = [
    { label: `+1σ (${upper1.toFixed(1)}%)`, data: Array(labels.length).fill(upper1), type: 'line', borderColor: opts.sigmaOnly ? _cBlue : _cDanger, borderWidth: 1.5, borderDash: [6, 4], pointRadius: 0, fill: false, order: 1 },
    { label: `−1σ (${lower1.toFixed(1)}%)`, data: Array(labels.length).fill(lower1), type: 'line', borderColor: _cDanger, borderWidth: 1.5, borderDash: [6, 4], pointRadius: 0, fill: false, order: 1 },
    { label: `Mean (${mean.toFixed(1)}%)`, data: Array(labels.length).fill(mean), type: 'line', borderColor: _cT3, borderWidth: 1, borderDash: [3, 3], pointRadius: 0, fill: false, order: 1 },
  ];

  return new Chart(ctx, {
    type: 'bar',
    data: {
      labels: labels.map(_monthLabel),
      datasets: [
        { label: 'Monthly Chg %', data: changes, backgroundColor: barColors, borderRadius: 3, order: 2 },
        ...(opts.sigmaOnly ? [lineDs[0], lineDs[1]] : lineDs),
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: _legendCfg,
        tooltip: { callbacks: { label: c => `${c.dataset.label}: ${c.raw.toFixed(2)}%` } },
      },
      scales: {
        x: { grid: { color: _gridClr }, ticks: { font: { family: _cm, size: 10 } } },
        y: { grid: { color: _gridClr }, ticks: { font: { family: _cm, size: 10 }, callback: v => v.toFixed(1) + '%' } },
      },
    },
  });
}

export const BAND_COLORS = { k1: _cWarn, k2: '#B45309', k3: _cDanger, up: _cBlue, down: _cDanger };
