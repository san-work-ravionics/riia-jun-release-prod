// ── Portfolio — allocation builder + 2025 performance chart ──
import { api, apiBase } from '../shared/api.js';
import { setEl } from './utils.js';

let _instrumentIds = [];
let _perfChart = null;

function _updateTotal() {
  let total = 0;
  for (const id of _instrumentIds) {
    const el = document.getElementById(`mp-input-${id}`);
    if (el) total += parseInt(el.value || '0', 10);
  }
  const display = document.getElementById('mp-total-display');
  const bar     = document.getElementById('mp-alloc-bar');
  const btn     = document.getElementById('mp-save-btn');
  if (display) {
    display.textContent = `Total: ${total}%`;
    display.classList.toggle('mp-total-ok',  total === 100);
    display.classList.toggle('mp-total-err', total !== 100);
  }
  if (bar) bar.value = total;
  if (btn) btn.disabled = (total !== 100);
}

function _renderSavedDisplay(data) {
  const savedEl = document.getElementById('mp-saved-display');
  if (!savedEl) return;

  const updatedAt = data.updated_at
    ? new Date(data.updated_at).toLocaleString()
    : '—';
  const titleEl = document.getElementById('mp-saved-title-text');
  const tsEl    = document.getElementById('mp-saved-ts');
  const chipsEl = document.getElementById('mp-saved-chips');

  if (titleEl) titleEl.textContent = `Saved: ${data.name || 'Portfolio'}`;
  if (tsEl)    tsEl.textContent    = `Last saved: ${updatedAt}`;
  if (chipsEl) {
    chipsEl.innerHTML = (data.holdings || [])
      .map(h => `<span class="mp-chip">${h.instrument_id} ${h.allocation_pct}%</span>`)
      .join('');
  }

  savedEl.style.display = '';
  _fetchAndRenderChart(data.holdings || []);
}

async function _fetchAndRenderChart(holdings) {
  if (!holdings.length) return;
  const holdingsParam = holdings
    .filter(h => h.allocation_pct > 0)
    .map(h => `${h.instrument_id}:${h.allocation_pct}`)
    .join(',');
  if (!holdingsParam) return;

  let dates = [], values = [];
  try {
    const data = await api(
      `/api/v1/experience/rita/portfolio-performance?holdings=${encodeURIComponent(holdingsParam)}&year=2025`
    );
    dates  = data.dates  || [];
    values = data.values || [];
  } catch (_) {}

  if (!dates.length) return;
  _renderPerfChart(dates, values);
}

function _renderPerfChart(dates, values) {
  const canvas = document.getElementById('mp-perf-chart');
  if (!canvas) return;

  // Thin to ~60 points for a clean chart
  const step = Math.max(1, Math.floor(dates.length / 60));
  const xLabels = dates.filter((_, i) => i % step === 0);
  const yValues = values.filter((_, i) => i % step === 0);

  if (_perfChart) { _perfChart.destroy(); _perfChart = null; }

  const ctx = canvas.getContext('2d');
  _perfChart = new Chart(ctx, {
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
        callbacks: {
          label: ctx => `${ctx.parsed.y.toFixed(1)} (base 100)`,
          title: ctx => ctx[0].label,
        },
      }},
      scales: {
        x: {
          ticks: {
            font: { family: "'IBM Plex Mono', monospace", size: 9 },
            color: '#8C877A',
            maxTicksLimit: 6,
            maxRotation: 0,
          },
          grid: { display: false },
        },
        y: {
          ticks: {
            font: { family: "'IBM Plex Mono', monospace", size: 9 },
            color: '#8C877A',
            maxTicksLimit: 4,
          },
          grid: { color: 'rgba(0,0,0,0.05)' },
        },
      },
    },
  });
}

export async function loadMyPortfolio() {
  _instrumentIds = [];

  // ── Load instrument list ──────────────────────────────────────
  let instruments = [];
  try {
    const geo = await api('/api/v1/experience/rita/geography-overview');
    for (const region of (geo.regions || [])) {
      for (const inst of (region.instruments || [])) {
        if (inst.id !== 'ATHER') instruments.push(inst);
      }
    }
  } catch (_) {
    setEl('mp-builder', 'Unable to load available instruments. Please refresh.');
    return;
  }

  _instrumentIds = instruments.map(i => i.id);

  // ── Render kpi-sm allocation tiles ───────────────────────────
  const tiles = instruments.map(i => `
    <div class="kpi kpi-sm mp-tile">
      <div class="kpi-label">${i.name}</div>
      <div class="kpi-value" style="display:flex;align-items:baseline;justify-content:center;gap:2px">
        <input type="number" id="mp-input-${i.id}" class="mp-alloc-input"
               min="0" max="100" step="1" value="0"
               oninput="window._mpUpdateTotal()">
        <span style="font-size:10px;color:var(--t3)">%</span>
      </div>
      <div class="kpi-delta">of portfolio</div>
    </div>`).join('');
  setEl('mp-instruments', tiles);

  window._mpUpdateTotal = _updateTotal;

  // ── Pre-populate from saved portfolio ─────────────────────────
  const savedEl = document.getElementById('mp-saved-display');
  if (savedEl) savedEl.style.display = 'none';
  setEl('mp-status-msg', '');

  try {
    const token = sessionStorage.getItem('rita_token');
    const headers = { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) };
    const resp = await fetch(apiBase() + '/api/v1/experience/user-portfolio', { headers });
    if (resp.ok) {
      const portfolio = await resp.json();
      for (const h of (portfolio.holdings || [])) {
        const inp = document.getElementById(`mp-input-${h.instrument_id}`);
        if (inp) inp.value = h.allocation_pct;
      }
      _renderSavedDisplay(portfolio);
    }
  } catch (_) {}

  _updateTotal();
}

export async function savePortfolio() {
  const token = sessionStorage.getItem('rita_token');
  if (!token) {
    sessionStorage.setItem('post_login_redirect', window.location.href);
    window.location.href = '/auth/google/login?state=rita';
    return;
  }

  const holdings = _instrumentIds
    .map(id => {
      const el = document.getElementById(`mp-input-${id}`);
      return { instrument_id: id, allocation_pct: parseInt(el ? el.value || '0' : '0', 10) };
    })
    .filter(h => h.allocation_pct > 0);

  const nameEl = document.getElementById('mp-portfolio-name');
  const name   = (nameEl && nameEl.value.trim()) ? nameEl.value.trim() : 'Portfolio';

  setEl('mp-status-msg', '');

  try {
    const result = await api('/api/v1/user-portfolio/', 'POST', { name, holdings });
    if (result) {
      setEl('mp-status-msg', '<span class="mp-ok">Portfolio saved.</span>');
      _renderSavedDisplay(result);
    }
  } catch (err) {
    setEl('mp-status-msg', `<span class="mp-err">${err.message || 'Save failed.'}</span>`);
  }
}
