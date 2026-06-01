// ── Portfolio Hedge — Feature 28 Phase 3 ──────────────────────────────────────
// Section entry point: loadPortfolioHedge()
// Phase 3: all hedge params computed client-side (Phase 2 backend adds real data).
// APIs used:
//   GET /api/v1/experience/user-portfolio     (JWT)
//   GET /api/v1/experience/rita/geography-overview (no auth, for risk/return)

import { apiFetch } from './api.js';

// ── State ─────────────────────────────────────────────────────────────────────
let _holdings    = [];   // [{instrument_id, allocation_pct}]
let _instruments = {};   // id → {daily_return_pct, signal, region}
let _coverage    = 50;   // 0–100
let _scenarioTab = 'pp'; // 'pp' | 'ps' | 'collar'
let _payoffChart = null;

// ── F&O eligibility (Phase 2 will source from API) ───────────────────────────
const FNO_ELIGIBLE = new Set([
  'RELIANCE','TATAMOTOR','TCS','INFY','HDFCBANK','WIPRO','BAJFINANCE',
  'TATASTEEL','SBIN','ICICIBANK','KOTAKBANK','AXISBANK','SUNPHARMA','HCLTECH','LT',
  'ONGC','NTPC','POWERGRID','BPCL','HINDUNILVR','NESTLEIND',
]);

// ── DOM helpers ───────────────────────────────────────────────────────────────
function _show(id) { const el = document.getElementById(id); if (el) el.style.display = ''; }
function _hide(id) { const el = document.getElementById(id); if (el) el.style.display = 'none'; }
function _setText(id, txt) { const el = document.getElementById(id); if (el) el.textContent = txt; }
function _setHtml(id, html) { const el = document.getElementById(id); if (el) el.innerHTML = html; }

// ── Risk estimation (same bucketing as RITA portfolio-builder) ────────────────
function _estRisk(daily_return_pct) {
  const abs = Math.abs(daily_return_pct || 0);
  if (abs < 0.3) return 1;
  if (abs < 0.7) return 2;
  if (abs < 1.2) return 3;
  if (abs < 2.0) return 4;
  return 5;
}

function _riskDots(r) {
  return Array.from({ length: 5 }, (_, i) =>
    `<span style="font-size:11px;color:${i < r ? '#BE185D' : 'rgba(0,0,0,.15)'}">●</span>`
  ).join('');
}

// ── Hedge type per holding ────────────────────────────────────────────────────
function _hedgeType(id, region, alloc_pct) {
  if (FNO_ELIGIBLE.has(id)) {
    return alloc_pct >= 20 ? 'put_spread' : 'protective_put';
  }
  if (region === 'US') return 'ndx_proxy';
  return 'nifty_proxy';
}

function _hedgeLabel(type) {
  return {
    protective_put: 'Protective put',
    put_spread:     'Put spread',
    ndx_proxy:      'NDX put proxy',
    nifty_proxy:    'NIFTY put proxy',
  }[type] || type;
}

function _isProxy(type) { return type === 'ndx_proxy' || type === 'nifty_proxy'; }

// ── Coverage → per-row params ─────────────────────────────────────────────────
function _rowParams(type, risk, coverage) {
  const c = coverage / 100;

  // Strike: lerp from −12% OTM (c=0) to −2% OTM (c=1)
  const strikePct = -(12 - c * 10);  // −12% → −2%

  // Strike label
  let strikeLabel;
  if (type === 'put_spread') {
    const lo = Math.round(strikePct);
    const hi = Math.round(strikePct - 6);
    strikeLabel = `${lo}/${hi}%`;
  } else {
    strikeLabel = `${Math.round(strikePct)}% OTM`;
  }

  // Monthly cost % (simplified, calibrated to produce ~0.6% aggregate at c=0.5, 5 holdings)
  const baseVol = risk * 0.065;
  const costPct = _isProxy(type)
    ? baseVol * 0.28 * (0.4 + c * 0.6)
    : baseVol * 0.40 * (0.4 + c * 0.6);

  // Protected % (30% at c=0, 80% at c=1)
  const protectedPct = Math.round((30 + c * 50) * (_isProxy(type) ? 0.85 : 1));

  return { strikePct, strikeLabel, costPct, protectedPct };
}

// ── Build enriched row list ───────────────────────────────────────────────────
// Phase 2: if _apiHedge is available, prefer its per-row data (real BS pricing).
// Phase 1 fallback: derive everything client-side.
function _buildRows() {
  // Build API lookup by instrument_id if available
  const apiMap = {};
  if (_apiHedge && Array.isArray(_apiHedge.holdings)) {
    for (const h of _apiHedge.holdings) apiMap[h.instrument_id] = h;
  }

  return _holdings.map(h => {
    const inst   = _instruments[h.instrument_id] || {};
    const region = inst.region || 'Other';
    const api    = apiMap[h.instrument_id];

    if (api) {
      // Phase 2: use real API values
      return {
        id:            h.instrument_id,
        weight:        h.allocation_pct,
        ret:           api.return_1y_pct ?? inst.daily_return_pct,
        risk:          api.risk_score ?? _estRisk(inst.daily_return_pct),
        region,
        type:          api.hedge_type,
        label:         _hedgeLabel(api.hedge_type),
        proxy:         _isProxy(api.hedge_type),
        strikePct:     api.strike_pct,
        strikeLabel:   api.strike_label,
        costPct:       api.cost_pct,
        protectedPct:  api.protected_pct,
      };
    }

    // Phase 1 fallback: client-side derived
    const risk   = inst.risk_score ?? _estRisk(inst.daily_return_pct);
    const ret    = inst.return_1y_pct ?? inst.daily_return_pct;
    const type   = _hedgeType(h.instrument_id, region, h.allocation_pct);
    const params = _rowParams(type, risk, _coverage);
    return {
      id:     h.instrument_id,
      weight: h.allocation_pct,
      ret,
      risk,
      region,
      type,
      label:  _hedgeLabel(type),
      proxy:  _isProxy(type),
      ...params,
    };
  });
}

// ── Aggregate readouts ────────────────────────────────────────────────────────
function _aggregates(rows) {
  // Phase 2: use real API aggregates when available
  if (_apiHedge && _apiHedge.aggregate) {
    const agg = _apiHedge.aggregate;
    const totalCost = agg.monthly_cost_pct;
    const maxDdHedged   = agg.max_dd_protected_pct;
    const maxDdUnhedged = agg.max_dd_unhedged_pct;
    // avgStrike needed for payoff chart — approximate from rows
    const avgStrike = rows.reduce((s, r) => s + r.strikePct * (r.weight / 100), 0);
    return { totalCost, avgStrike, maxDdHedged, maxDdUnhedged };
  }
  // Phase 1 fallback: client-side
  const totalCost = rows.reduce((s, r) => s + r.costPct * (r.weight / 100), 0);
  const avgStrike = rows.reduce((s, r) => s + r.strikePct * (r.weight / 100), 0);
  const maxDdHedged   = Math.max(avgStrike - totalCost, -25);
  const maxDdUnhedged = -22;
  return { totalCost, avgStrike, maxDdHedged, maxDdUnhedged };
}

// ── Render: hedge table ───────────────────────────────────────────────────────
function _renderTable() {
  const rows = _buildRows();
  const tbody = document.getElementById('ph-table-body');
  if (!tbody) return;

  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="9" style="padding:16px;text-align:center;color:#94a3b8;font-size:12px">No portfolio holdings to display. Build a portfolio in RITA first.</td></tr>';
    return;
  }

  tbody.innerHTML = rows.map(r => {
    const retColor = (r.ret || 0) > 0 ? '#16a34a' : (r.ret || 0) < 0 ? '#dc2626' : '#64748b';
    const retStr = r.ret != null ? ((r.ret >= 0 ? '+' : '') + r.ret.toFixed(2) + '%') : '—';
    const proxyBadge = r.proxy
      ? `style="border:1px solid rgba(190,24,93,.4);color:#BE185D;background:rgba(190,24,93,.06)"`
      : `style="border:1px solid rgba(0,0,0,.1);color:#64748b;background:rgba(0,0,0,.03)"`;
    const barW = Math.min(r.protectedPct, 100);
    return `<tr style="border-bottom:1px solid rgba(0,0,0,.05);background:${r.proxy ? 'rgba(190,24,93,.02)' : 'transparent'}">
      <td style="padding:9px 10px;font-weight:700;font-family:'IBM Plex Mono',monospace;font-size:13px">${r.id}</td>
      <td style="padding:9px 10px;text-align:right;font-family:'IBM Plex Mono',monospace;font-size:12px">${r.weight}%</td>
      <td style="padding:9px 10px;text-align:right;font-family:'IBM Plex Mono',monospace;font-size:12px;color:${retColor}">${retStr}</td>
      <td style="padding:9px 10px">${_riskDots(r.risk)}</td>
      <td style="padding:9px 10px">
        <span style="display:inline-block;font-size:11px;padding:2px 8px;border-radius:100px;font-weight:500;white-space:nowrap;${proxyBadge.slice(7,-1)}">${r.label}</span>
      </td>
      <td style="padding:9px 10px;font-family:'IBM Plex Mono',monospace;font-size:12px;color:#64748b">${r.strikeLabel}</td>
      <td style="padding:9px 10px;text-align:right;font-family:'IBM Plex Mono',monospace;font-size:12px">${r.costPct.toFixed(2)}%</td>
      <td style="padding:9px 10px">
        <div style="display:flex;align-items:center;gap:8px">
          <div style="width:60px;height:5px;border-radius:3px;background:rgba(0,0,0,.08)">
            <div style="width:${barW}%;height:100%;border-radius:3px;background:#BE185D"></div>
          </div>
          <span style="font-size:12px;font-family:'IBM Plex Mono',monospace;font-weight:600">${r.protectedPct}%</span>
        </div>
      </td>
    </tr>`;
  }).join('');

  // Proxy note
  const hasProxy = rows.some(r => r.proxy);
  const note = document.getElementById('ph-no-fno-note');
  if (note) note.style.display = hasProxy ? '' : 'none';
}

// ── Render: coverage band readouts ───────────────────────────────────────────
function _renderCoverageBand() {
  const rows = _buildRows();
  if (!rows.length) return;
  const { totalCost, maxDdHedged, maxDdUnhedged } = _aggregates(rows);

  _setText('ph-max-dd-hedged',   `${maxDdHedged.toFixed(0)}%`);
  _setText('ph-max-dd-unhedged', `vs ${maxDdUnhedged}% unhedged`);
  _setText('ph-monthly-cost',    `${totalCost.toFixed(2)}%`);
  _setText('ph-monthly-cost-sub','premium drag');

  // Update slider label
  const c = _coverage;
  let label = 'Lightly hedged';
  if (c <= 20) label = 'Unhedged';
  else if (c >= 80) label = 'Fully protected';
  _setText('ph-coverage-label', label);
}

// ── Render: payoff chart ──────────────────────────────────────────────────────
function _renderPayoffChart() {
  const canvas = document.getElementById('ph-payoff-chart');
  if (!canvas) return;
  const rows = _buildRows();
  if (!rows.length) return;

  const { totalCost, avgStrike } = _aggregates(rows);
  const moves = [];
  for (let m = -25; m <= 15; m++) moves.push(m);

  function _hedgedPL(m, tab) {
    if (tab === 'pp') {
      return Math.max(m, avgStrike) - totalCost;
    } else if (tab === 'ps') {
      const spreadWidth = 5;
      const lo = avgStrike;
      const hi = avgStrike - spreadWidth;
      if (m > lo) return m - totalCost * 0.65;
      if (m > hi) return lo - totalCost * 0.65;
      return m + (lo - hi) - totalCost * 0.65;
    } else {
      // Collar: floor + upside cap at +5%
      const capped = Math.min(m, 5);
      return Math.max(capped, avgStrike) - totalCost;
    }
  }

  const unhedgedData = moves.map(m => m);
  const hedgedData   = moves.map(m => parseFloat(_hedgedPL(m, _scenarioTab).toFixed(2)));

  if (_payoffChart) { _payoffChart.destroy(); _payoffChart = null; }

  requestAnimationFrame(() => {
    _payoffChart = new Chart(canvas, {
      type: 'line',
      data: {
        labels: moves.map(m => m + '%'),
        datasets: [
          {
            label: 'hedged',
            data: hedgedData,
            borderColor: '#BE185D',
            borderWidth: 2.5,
            pointRadius: 0,
            tension: 0.1,
            fill: false,
          },
          {
            label: 'unhedged',
            data: unhedgedData,
            borderColor: 'rgba(100,116,139,.5)',
            borderWidth: 1.5,
            borderDash: [5, 4],
            pointRadius: 0,
            tension: 0,
            fill: false,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            display: true,
            position: 'top',
            labels: { font: { family: 'IBM Plex Mono', size: 10 }, boxWidth: 20, padding: 10 },
          },
          tooltip: {
            mode: 'index',
            intersect: false,
            callbacks: {
              label: ctx => `${ctx.dataset.label}: ${ctx.parsed.y.toFixed(1)}%`,
            },
          },
          annotation: {
            annotations: {
              zeroline: {
                type: 'line',
                yMin: 0, yMax: 0,
                borderColor: 'rgba(0,0,0,.15)',
                borderWidth: 1,
              },
            },
          },
        },
        scales: {
          x: {
            title: { display: true, text: 'market move →', font: { family: 'IBM Plex Mono', size: 10 } },
            grid: { color: 'rgba(0,0,0,.04)' },
            ticks: { font: { family: 'IBM Plex Mono', size: 9 }, maxTicksLimit: 10 },
          },
          y: {
            title: { display: true, text: 'P&L %', font: { family: 'IBM Plex Mono', size: 10 } },
            grid: { color: 'rgba(0,0,0,.04)' },
            ticks: { font: { family: 'IBM Plex Mono', size: 9 }, callback: v => v + '%' },
          },
        },
      },
    });
  });
}

// ── Render: scenario table ────────────────────────────────────────────────────
function _renderScenarioTable() {
  const rows = _buildRows();
  if (!rows.length) return;
  const { totalCost, avgStrike } = _aggregates(rows);
  const MOVES = [-20, -10, 0, 10];

  function _hedgedPL(m, tab) {
    if (tab === 'pp') {
      return Math.max(m, avgStrike) - totalCost;
    } else if (tab === 'ps') {
      const lo = avgStrike;
      const hi = avgStrike - 5;
      if (m > lo) return m - totalCost * 0.65;
      if (m > hi) return lo - totalCost * 0.65;
      return m + (lo - hi) - totalCost * 0.65;
    } else {
      const capped = Math.min(m, 5);
      return Math.max(capped, avgStrike) - totalCost;
    }
  }

  function _fmtPct(v) {
    const s = v.toFixed(0);
    const color = v > 0 ? '#16a34a' : v < -0.5 ? '#dc2626' : '#64748b';
    return `<span style="font-family:'IBM Plex Mono',monospace;font-weight:700;color:${color}">${v > 0 ? '+' : ''}${s}%</span>`;
  }

  const tbody = document.getElementById('ph-scenario-body');
  if (tbody) {
    tbody.innerHTML = MOVES.map(m => {
      const hedged = _hedgedPL(m, _scenarioTab);
      const mLabel = m === 0 ? 'Flat' : (m > 0 ? '+' : '') + m + '%';
      return `<tr style="border-bottom:1px solid rgba(0,0,0,.06)">
        <td style="padding:8px 12px;font-size:13px;color:#64748b">${mLabel}</td>
        <td style="padding:8px 12px;text-align:right">${_fmtPct(m)}</td>
        <td style="padding:8px 12px;text-align:right">${_fmtPct(hedged)}</td>
      </tr>`;
    }).join('');
  }

  _setText('ph-cost-display', `${totalCost.toFixed(2)}%/mo`);

  // Update chart coverage badge
  const badge = document.getElementById('ph-chart-coverage-badge');
  if (badge) badge.textContent = `at ${_coverage}% coverage`;
}

// ── Scenario tab switching ────────────────────────────────────────────────────
function _highlightScenarioTab() {
  ['pp', 'ps', 'collar'].forEach(t => {
    const btn = document.getElementById(`ph-tab-${t}`);
    if (!btn) return;
    if (t === _scenarioTab) {
      btn.style.background = '#BE185D';
      btn.style.color = '#fff';
      btn.style.border = '1px solid #BE185D';
    } else {
      btn.style.background = 'transparent';
      btn.style.color = '#64748b';
      btn.style.border = '1px solid rgba(0,0,0,.12)';
    }
  });
}

// ── Full refresh (called whenever coverage or tab changes) ────────────────────
function _refresh() {
  _renderTable();
  _renderCoverageBand();
  _renderPayoffChart();
  _renderScenarioTable();
  _highlightScenarioTab();
}

// ── Phase 2: real hedge data from API, merged into _apiHedge ─────────────────
let _apiHedge = null;  // PortfolioHedgeResponse or null when unavailable

async function _fetchApiHedge(token, coverage) {
  try {
    const data = await apiFetch(
      `/api/v1/experience/fno/portfolio-hedge?coverage=${coverage}`,
      { headers: { Authorization: `Bearer ${token}` } }
    );
    return data || null;
  } catch (_) {
    return null;  // graceful degradation to client-side
  }
}

// ── Section loader ────────────────────────────────────────────────────────────
export async function loadPortfolioHedge() {
  _show('ph-loading');
  _hide('ph-error');
  _hide('ph-empty');
  _hide('ph-content');

  const token = sessionStorage.getItem('auth_token');
  if (!token) {
    _hide('ph-loading');
    _show('ph-empty');
    _setText('ph-empty-msg', 'Please sign in to view your hedge plan.');
    return;
  }

  try {
    // Phase 2: load API hedge data + geo overview in parallel
    const [apiHedge, portfolio, geo] = await Promise.all([
      _fetchApiHedge(token, _coverage),
      apiFetch('/api/v1/experience/user-portfolio', {
        headers: { Authorization: `Bearer ${token}` },
      }),
      apiFetch('/api/v1/experience/rita/geography-overview'),
    ]);

    _hide('ph-loading');

    if (!portfolio || !portfolio.holdings || !portfolio.holdings.length) {
      _show('ph-empty');
      _setText('ph-empty-msg', 'No portfolio saved yet. Build one in the RITA Portfolio Builder.');
      return;
    }

    _holdings = portfolio.holdings;
    _apiHedge = apiHedge;  // null = fallback to client-side math

    // Build instrument lookup for client-side fallback: id → {daily_return_pct, risk_score, region}
    _instruments = {};
    if (geo && geo.regions) {
      for (const r of geo.regions) {
        for (const i of (r.instruments || [])) {
          _instruments[i.id] = { ...i, region: r.region };
        }
      }
    }

    const nameEl = document.getElementById('ph-portfolio-name');
    if (nameEl && portfolio.name) nameEl.textContent = portfolio.name;

    const slider = document.getElementById('ph-coverage-slider');
    if (slider) slider.value = _coverage;

    _show('ph-content');
    _refresh();

  } catch (e) {
    _hide('ph-loading');
    _show('ph-error');
    _setText('ph-error-msg', e.message || 'Failed to load portfolio hedge data.');
    console.error('[PH] loadPortfolioHedge error:', e);
  }
}

// ── Exported window actions ───────────────────────────────────────────────────
export function phSetCoverage(val) {
  _coverage = parseInt(val, 10);
  _refresh();  // immediate client-side update for responsive feel

  // Phase 2: async re-fetch from API with new coverage (debounced via closure)
  const token = sessionStorage.getItem('auth_token');
  if (token) {
    const captureCov = _coverage;
    setTimeout(async () => {
      if (captureCov !== _coverage) return;  // superseded by a newer drag
      const fresh = await _fetchApiHedge(token, captureCov);
      if (fresh && captureCov === _coverage) {
        _apiHedge = fresh;
        _refresh();
      }
    }, 300);
  }
}

export function phSetScenarioTab(tab) {
  _scenarioTab = tab;
  _highlightScenarioTab();
  _renderPayoffChart();
  _renderScenarioTable();
}
