// ── FnO Portfolio — read-only kpi tile display + 2025 performance chart ──
import { apiBase } from './api.js';

let _perfChart = null;

function _renderTiles(holdings) {
  const wrap = document.getElementById('fno-mp-tiles');
  if (!wrap) return;
  wrap.innerHTML = holdings.map(h => `
    <div class="kpi kpi-sm">
      <div class="kpi-label">${h.instrument_id}</div>
      <div class="kpi-value" style="color:var(--chat);text-align:center">${h.allocation_pct}%</div>
      <div class="kpi-delta" style="text-align:center">of portfolio</div>
    </div>`).join('');
}

async function _fetchAndRenderChart(holdings) {
  const holdingsParam = holdings
    .filter(h => h.allocation_pct > 0)
    .map(h => `${h.instrument_id}:${h.allocation_pct}`)
    .join(',');
  if (!holdingsParam) return;

  let dates = [], values = [];
  try {
    const resp = await fetch(
      apiBase() + `/api/v1/experience/rita/portfolio-performance?holdings=${encodeURIComponent(holdingsParam)}&year=2025`
    );
    if (resp.ok) { const d = await resp.json(); dates = d.dates || []; values = d.values || []; }
  } catch (_) {}

  if (!dates.length) return;

  const step = Math.max(1, Math.floor(dates.length / 60));
  const xLabels = dates.filter((_, i) => i % step === 0);
  const yValues = values.filter((_, i) => i % step === 0);

  const canvas = document.getElementById('fno-mp-perf-chart');
  if (!canvas) return;
  if (_perfChart) { _perfChart.destroy(); _perfChart = null; }

  _perfChart = new Chart(canvas.getContext('2d'), {
    type: 'line',
    data: {
      labels: xLabels,
      datasets: [{
        data: yValues,
        borderColor: '#BE185D',
        backgroundColor: 'rgba(190,24,93,0.08)',
        borderWidth: 1.5,
        pointRadius: 0,
        fill: true,
        tension: 0.3,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: {
        callbacks: { label: ctx => `${ctx.parsed.y.toFixed(1)} (base 100)` },
      }},
      scales: {
        x: {
          ticks: { font: { family: "'IBM Plex Mono', monospace", size: 9 }, color: '#8C877A', maxTicksLimit: 6, maxRotation: 0 },
          grid: { display: false },
        },
        y: {
          ticks: { font: { family: "'IBM Plex Mono', monospace", size: 9 }, color: '#8C877A', maxTicksLimit: 4 },
          grid: { color: 'rgba(0,0,0,0.05)' },
        },
      },
    },
  });
}

export async function loadFnoMyPortfolio() {
  const emptyEl  = document.getElementById('fno-mp-empty');
  const errorEl  = document.getElementById('fno-mp-error');
  const loadedEl = document.getElementById('fno-mp-loaded');

  const hide = el => { if (el) el.style.display = 'none'; };
  hide(emptyEl); hide(errorEl); hide(loadedEl);

  try {
    const token = sessionStorage.getItem('rita_token');
    const headers = { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) };
    const resp = await fetch(apiBase() + '/api/v1/experience/user-portfolio', { headers });

    if (resp.status === 401) {
      sessionStorage.removeItem('rita_token');
      window.location.href = '/';
      return;
    }

    if (resp.status === 404) {
      if (emptyEl) emptyEl.style.display = '';
      return;
    }

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      if (errorEl) { errorEl.style.display = ''; errorEl.textContent = 'Unable to load portfolio — ' + (err.detail || resp.statusText); }
      return;
    }

    const data = await resp.json();
    const holdings = data.holdings || [];

    if (!holdings.length) {
      if (emptyEl) emptyEl.style.display = '';
      return;
    }

    const nameEl    = document.getElementById('fno-mp-name');
    const updatedEl = document.getElementById('fno-mp-updated');
    if (nameEl)    nameEl.textContent    = data.name || 'Portfolio';
    if (updatedEl) updatedEl.textContent = data.updated_at ? 'Last saved: ' + new Date(data.updated_at).toLocaleString() : '';

    _renderTiles(holdings);
    if (loadedEl) loadedEl.style.display = '';
    _fetchAndRenderChart(holdings);

  } catch (e) {
    if (errorEl) { errorEl.style.display = ''; errorEl.textContent = 'Unable to load portfolio — ' + (e.message || 'unexpected error'); }
  }
}

window.loadFnoMyPortfolio = loadFnoMyPortfolio;
