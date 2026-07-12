// ── Portfolio Builder — Feature 28 Phase 1 ────────────────────────────────────
// Section entry point: loadPortfolioBuilder()
// API: GET /api/v1/experience/rita/geography-overview (no auth)
//      GET /api/v1/experience/user-portfolio          (JWT, silent 404)
//      POST /api/v1/user-portfolio/                   (JWT, basket build)

import { api, apiFetch } from './api.js';
import { ensureDevToken, isLocalDev } from '../shared/dev-auth.js';

// ── State ─────────────────────────────────────────────────────────────────────
const _basket = new Set();
const _allocationPct = new Map(); // instrument id → allocation %
let _mapChart  = null;
let _draftChart = null;
let _sortCol   = 'return';
let _sortAsc   = false;
let _geoCache  = null;
let _draftItems = [];   // [{id, ret, on}]
let _activePreset = null;
let _optimizerMode = false;
let _optimizerResponse = null;
let _optimizerFetchId = 0; // race-condition guard: latest-call-wins

// Phase 2: sector, risk_score, return_1y_pct now come from the API.
// This fallback map is used only when the API field is null (instruments with
// insufficient price history for vol computation).
const _SECTOR_FALLBACK = {
  RELIANCE:'Energy', TATAMOTOR:'Auto', NVIDIA:'Tech', MSFT:'Tech',
  AAPL:'Tech', TSLA:'Auto', ASML:'Tech', SAP:'Tech',
};

// ── DOM helpers ───────────────────────────────────────────────────────────────
function _show(id) { const el = document.getElementById(id); if (el) el.style.display = ''; }
function _hide(id) { const el = document.getElementById(id); if (el) el.style.display = 'none'; }
function _setText(id, txt) { const el = document.getElementById(id); if (el) el.textContent = txt; }

// ── Data helpers ──────────────────────────────────────────────────────────────
function _estRisk(pct) {
  const abs = Math.abs(pct || 0);
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

function _miniBar(pct) {
  const w = Math.min(Math.abs(pct || 0) * 10, 40);
  return `<span style="display:inline-block;width:${w}px;height:5px;border-radius:2px;background:${(pct||0)>=0?'#BE185D':'#94a3b8'};vertical-align:middle;flex-shrink:0"></span>`;
}

function _fmtRet(pct, est) {
  if (pct == null) return '—';
  return (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%' + (est ? ' (est.)' : '');
}

function _allInstruments(geo) {
  return (geo.regions || []).flatMap(r => r.instruments || []);
}

function _priceForId(id) {
  if (!_geoCache) return null;
  for (const r of (_geoCache.regions || [])) {
    const inst = (r.instruments || []).find(i => i.id === id);
    if (inst && inst.close) return inst.close;
  }
  return null;
}

function _totalEurInput() {
  const v = parseFloat(document.getElementById('pb-total-eur')?.value);
  return isNaN(v) || v <= 0 ? 0 : v;
}

function _sharesAndCash(totalEur, allocPct, price) {
  if (!totalEur || !allocPct || !price) return null;
  const allocEur = totalEur * allocPct / 100;
  const shares   = Math.floor(allocEur / price);
  const actual   = shares * price;
  const cash     = allocEur - actual;
  return { allocEur, shares, actual, cash };
}

function _regionDisplay(apiRegion) {
  return { India: 'India', US: 'US', EU: 'Europe', Other: 'Other' }[apiRegion] || apiRegion;
}

function _buildRegionLookup(geo) {
  const map = {};
  for (const r of (geo.regions || [])) {
    const d = _regionDisplay(r.region);
    for (const i of (r.instruments || [])) map[i.id] = d;
  }
  return map;
}

// ── Auto-select top 5 instruments (cross-geography) by return at 20% each ────
function _autoSelectTop5(geo) {
  if (_basket.size > 0) return; // only run when basket is empty (no saved portfolio loaded)
  const all = _allInstruments(geo).slice().sort((a, b) =>
    ((b.return_1y_pct ?? b.daily_return_pct) || 0) - ((a.return_1y_pct ?? a.daily_return_pct) || 0)
  );
  for (const inst of all.slice(0, 5)) {
    _basket.add(inst.id);
    _allocationPct.set(inst.id, 20);
  }
}

// ── Render: region summary panel ──────────────────────────────────────────────
function _renderRegionSummary() {
  const el = document.getElementById('pb-region-summary');
  if (!el) return;

  const total = _basket.size;
  const allocSum = [..._basket].reduce((s, id) => s + (_allocationPct.get(id) ?? 0), 0);

  if (total === 0) {
    el.innerHTML = '<div style="color:#94a3b8;font-size:12px;padding:2px 0">No instruments selected.</div>';
    _updateSummaryStats(0, null);
    return;
  }

  const geo = _geoCache;
  const LABELS = { India: '🇮🇳 India', US: '🇺🇸 US', EU: '🇪🇺 Europe', Other: '🌐 Other' };
  const rows = [];
  let totalRet = 0, retCount = 0;

  if (geo) {
    for (const r of (geo.regions || [])) {
      const sel = (r.instruments || []).filter(i => _basket.has(i.id));
      if (!sel.length) continue;
      const alloc = sel.reduce((s, i) => s + (_allocationPct.get(i.id) ?? 0), 0);
      const label = LABELS[r.region] || r.region;
      const n = sel.length;
      rows.push(`<div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid var(--border);font-size:12px">
        <div>
          <div style="font-weight:600;color:var(--text)">${label}</div>
          <div style="font-size:11px;color:var(--t2)">${n} instrument${n === 1 ? '' : 's'}</div>
        </div>
        <span style="font-family:'IBM Plex Mono',monospace;font-weight:700;font-size:13px;color:#BE185D">${alloc}%</span>
      </div>`);
      for (const i of sel) {
        if (i.daily_return_pct != null) { totalRet += i.daily_return_pct; retCount++; }
      }
    }
  }

  // Fallback: if no geo data, show basket IDs only
  if (!rows.length) {
    rows.push(`<div style="font-size:12px;color:var(--t2);padding:4px 0">${total} instrument${total === 1 ? '' : 's'} selected</div>`);
  }

  // Compute total cash across all basket instruments
  const totalEurForCash = _totalEurInput();
  let totalCash = 0;
  let hasPrices = false;
  if (totalEurForCash > 0) {
    for (const id of _basket) {
      const p = _priceForId(id);
      const sc = p ? _sharesAndCash(totalEurForCash, _allocationPct.get(id) ?? 0, p) : null;
      if (sc) { totalCash += sc.cash; hasPrices = true; }
    }
  }
  const cashRow = hasPrices
    ? `<div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;font-size:12px;margin-top:2px">
        <span style="color:var(--t2)">Cash balance</span>
        <span style="font-family:'IBM Plex Mono',monospace;font-weight:700;font-size:13px;color:#16a34a">€${totalCash.toFixed(0)}</span>
       </div>`
    : '';

  el.innerHTML = rows.join('') + cashRow;
  _updateSummaryStats(allocSum, retCount > 0 ? totalRet / retCount : null);
}

function _updateSummaryStats(allocSum, avgRet) {
  const allocEl = document.getElementById('pb-basket-alloc-sum');
  if (allocEl) {
    allocEl.textContent = `${allocSum}%`;
    allocEl.style.color = Math.abs(allocSum - 100) < 0.5 ? '#16a34a' : allocSum > 100 ? '#dc2626' : '#64748b';
  }
  const retEl = document.getElementById('pb-basket-avg-return');
  if (retEl) {
    retEl.textContent = avgRet != null ? _fmtRet(avgRet) : '—';
    if (avgRet != null) retEl.style.color = avgRet >= 0 ? '#16a34a' : '#dc2626';
  }
  const is100 = Math.abs(allocSum - 100) < 0.5;
  const buildBtn = document.getElementById('pb-basket-build-btn');
  if (buildBtn) {
    buildBtn.disabled = !is100;
    buildBtn.style.opacity = is100 ? '1' : '.45';
    buildBtn.style.cursor  = is100 ? 'pointer' : 'not-allowed';
  }
}

// ── Render: region buckets ────────────────────────────────────────────────────
function _renderBuckets(geo) {
  const keyMap = { India: 'india', US: 'us', EU: 'europe' };
  for (const region of (geo.regions || [])) {
    const key = keyMap[region.region];
    if (!key) continue; // "Other" instruments show in table/map only

    const container = document.getElementById(`pb-instruments-${key}`);
    if (!container) continue;

    const insts = region.instruments || [];
    const avg = insts.length ? insts.reduce((s, i) => s + (i.daily_return_pct || 0), 0) / insts.length : null;

    const metaEl = document.getElementById(`pb-region-meta-${key}`);
    if (metaEl) metaEl.textContent = `${insts.length} instruments · ranked by return`;
    const avgEl = document.getElementById(`pb-region-avg-${key}`);
    if (avgEl && avg != null) {
      avgEl.textContent = _fmtRet(avg);
      avgEl.style.color = avg >= 0 ? '#16a34a' : '#dc2626';
    }

    // Sort by 1Y return (Phase 2) or daily return fallback (Phase 1)
    const sorted = [...insts].sort((a, b) =>
      ((b.return_1y_pct ?? b.daily_return_pct) || 0) - ((a.return_1y_pct ?? a.daily_return_pct) || 0)
    );

    container.innerHTML = sorted.map(inst => {
      const inBasket = _basket.has(inst.id);
      // Phase 2: use API-provided sector/risk_score/return_1y_pct; fallback to derived values
      const sector   = inst.sector   || _SECTOR_FALLBACK[inst.id] || '—';
      const dispRet  = inst.return_1y_pct ?? inst.daily_return_pct;
      const retLabel = inst.return_1y_pct != null
        ? _fmtRet(inst.return_1y_pct)          // real 1Y — no "(est.)"
        : _fmtRet(inst.daily_return_pct, true); // daily fallback with "(est.)"
      const retColor = (dispRet || 0) >= 0 ? '#16a34a' : '#dc2626';
      return `<div onclick="pbToggleInstrument('${inst.id}')"
                   style="display:flex;align-items:center;gap:8px;padding:7px 8px;border-radius:6px;cursor:pointer;
                          border:1px solid ${inBasket ? 'rgba(190,24,93,.3)' : 'transparent'};
                          background:${inBasket ? 'rgba(190,24,93,.06)' : 'transparent'};margin-bottom:3px">
        <input type="checkbox" ${inBasket ? 'checked' : ''} onclick="event.stopPropagation();pbToggleInstrument('${inst.id}')" style="accent-color:#BE185D;flex-shrink:0">
        <div style="flex:1;min-width:0">
          <div style="font-weight:700;font-size:13px;color:${inBasket ? '#BE185D' : 'var(--text)'}">${inst.id}</div>
          <span style="display:inline-block;font-size:10px;padding:1px 6px;border-radius:100px;background:rgba(0,0,0,.06);color:var(--t2);font-weight:500">${sector}</span>
        </div>
        ${_miniBar(dispRet)}
        <span style="font-size:12px;font-weight:700;font-family:'IBM Plex Mono',monospace;color:${retColor};white-space:nowrap">${retLabel}</span>
      </div>`;
    }).join('') || '<div style="color:#94a3b8;font-size:12px;padding:8px">No instruments</div>';
  }
}

// ── Render: basket sidebar ────────────────────────────────────────────────────
function _renderBasket() {
  const geo = _geoCache;
  const count = _basket.size;

  const badge = document.getElementById('pb-basket-badge');
  if (badge) badge.textContent = count;

  const listEl  = document.getElementById('pb-basket-list');
  const emptyMsg = document.getElementById('pb-basket-empty-msg');
  if (listEl) {
    if (count === 0) {
      listEl.innerHTML = '';
      if (emptyMsg) emptyMsg.style.display = '';
    } else {
      if (emptyMsg) emptyMsg.style.display = 'none';
      const totalEur = _totalEurInput();
      // 2-column chip grid — each chip is 2 rows: ticker+remove / % input / shares+cash
      listEl.innerHTML = [..._basket].map(id => {
        const pct   = _allocationPct.get(id) ?? 0;
        const price = _priceForId(id);
        const sc    = totalEur > 0 && price ? _sharesAndCash(totalEur, pct, price) : null;
        const scHtml = sc
          ? `<div id="pb-chip-sc-${id}" style="display:flex;justify-content:space-between;margin-top:4px;font-size:10px;font-family:'IBM Plex Mono',monospace">
               <span style="color:#16a34a;font-weight:700">${sc.shares} shares</span>
               <span style="color:#64748b">€${sc.cash.toFixed(0)} cash</span>
             </div>`
          : `<div id="pb-chip-sc-${id}"></div>`;
        return `<div style="border-radius:8px;background:rgba(190,24,93,.06);border:1px solid rgba(190,24,93,.2);padding:6px 8px">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:5px">
            <span style="font-size:11px;font-weight:700;font-family:'IBM Plex Mono',monospace;color:#BE185D;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:80px">${id}</span>
            <button onclick="pbToggleInstrument('${id}')" style="background:none;border:none;color:#94a3b8;cursor:pointer;font-size:14px;line-height:1;padding:0;flex-shrink:0">×</button>
          </div>
          <div style="display:flex;align-items:center;gap:4px">
            <input type="number" min="0" max="100" step="1" value="${pct}"
                   oninput="pbSetAlloc('${id}',+this.value)"
                   style="flex:1;min-width:0;padding:3px 6px;border:1px solid rgba(190,24,93,.35);border-radius:5px;font-size:12px;font-family:'IBM Plex Mono',monospace;text-align:right;color:#1e293b;background:#fff">
            <span style="font-size:11px;color:#64748b;font-weight:600;flex-shrink:0">%</span>
          </div>
          ${scHtml}
        </div>`;
      }).join('');
    }
  }

  _renderRegionSummary();
}

// ── Render: scatter map ───────────────────────────────────────────────────────
function _renderMap(geo) {
  const instruments = _allInstruments(geo).filter(i => i.daily_return_pct != null);
  const mapEmpty = document.getElementById('pb-map-empty');

  if (!instruments.length) {
    _hide('pb-map-canvas');
    if (mapEmpty) mapEmpty.style.display = '';
    return;
  }
  _show('pb-map-canvas');
  if (mapEmpty) mapEmpty.style.display = 'none';

  if (_mapChart) { _mapChart.destroy(); _mapChart = null; }
  const canvas = document.getElementById('pb-map-canvas');
  if (!canvas) return;

  const points = instruments.map(i => ({
    x: i.return_1y_pct ?? i.daily_return_pct,
    y: i.risk_score ?? _estRisk(i.daily_return_pct),
    label: i.id,
  }));

  requestAnimationFrame(() => {
    _mapChart = new Chart(canvas, {
      type: 'scatter',
      data: {
        datasets: [{
          label: 'Instruments',
          data: points.map(p => ({ x: p.x, y: p.y })),
          backgroundColor: points.map(p => _basket.has(p.label) ? 'rgba(190,24,93,.85)' : 'rgba(100,116,139,.5)'),
          pointRadius: points.map(p => _basket.has(p.label) ? 9 : 7),
          pointHoverRadius: 11,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        onClick: (_, elements) => {
          if (elements.length > 0) pbToggleInstrument(points[elements[0].index].label);
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: ctx => {
                const p = points[ctx.dataIndex];
                return `${p.label}  return: ${ctx.parsed.x != null ? ctx.parsed.x.toFixed(1) + '%' : '—'}  risk: ${ctx.parsed.y}/5`;
              },
            },
          },
        },
        scales: {
          x: {
            title: { display: true, text: 'RETURN →', font: { family: 'IBM Plex Mono', size: 10 } },
            grid: { color: 'rgba(0,0,0,.05)' },
            ticks: { font: { family: 'IBM Plex Mono', size: 10 } },
          },
          y: {
            title: { display: true, text: 'RISK →', font: { family: 'IBM Plex Mono', size: 10 } },
            min: 0, max: 6,
            ticks: { stepSize: 1, font: { family: 'IBM Plex Mono', size: 10 }, callback: v => (v > 0 && v < 6) ? v : '' },
            grid: { color: 'rgba(0,0,0,.05)' },
          },
        },
      },
    });
  });
}

// ── Render: sortable table ────────────────────────────────────────────────────
function _renderTable(geo) {
  const regionLookup = _buildRegionLookup(geo);
  let instruments = _allInstruments(geo).slice().sort((a, b) => {
    let av, bv;
    if (_sortCol === 'name')   { av = a.id; bv = b.id; }
    if (_sortCol === 'region') { av = regionLookup[a.id] || ''; bv = regionLookup[b.id] || ''; }
    if (_sortCol === 'return') { av = (a.return_1y_pct ?? a.daily_return_pct) ?? -999; bv = (b.return_1y_pct ?? b.daily_return_pct) ?? -999; }
    if (_sortCol === 'risk')   { av = a.risk_score ?? _estRisk(a.daily_return_pct); bv = b.risk_score ?? _estRisk(b.daily_return_pct); }
    if (av === bv) return 0;
    const cmp = av < bv ? -1 : 1;
    return _sortAsc ? cmp : -cmp;
  });

  const wrap = document.getElementById('pb-table-wrap');
  const tableEmpty = document.getElementById('pb-table-empty');
  if (!instruments.length) {
    if (wrap) wrap.style.display = 'none';
    if (tableEmpty) tableEmpty.style.display = '';
    return;
  }
  if (wrap) wrap.style.display = '';
  if (tableEmpty) tableEmpty.style.display = 'none';

  function _th(col, label) {
    const active = _sortCol === col;
    return `<th onclick="pbSortTable('${col}')" style="padding:8px;text-align:${col==='return'?'right':'left'};font-weight:700;cursor:pointer;user-select:none">
      ${label}${active ? (' ' + (_sortAsc ? '▲' : '▼')) : ''}
    </th>`;
  }

  const table = document.getElementById('pb-table');
  if (!table) return;
  table.innerHTML = `
    <thead>
      <tr style="font-size:11px;color:#64748b;border-bottom:2px solid rgba(0,0,0,.1);text-transform:uppercase;letter-spacing:.04em">
        <th style="padding:8px;width:30px"></th>
        ${_th('name','Ticker')}
        ${_th('region','Region')}
        ${_th('return','Return')}
        ${_th('risk','Risk')}
        <th style="padding:8px;text-align:center">Action</th>
      </tr>
    </thead>
    <tbody>
      ${instruments.map(i => {
        const inBasket = _basket.has(i.id);
        const dispRet  = i.return_1y_pct ?? i.daily_return_pct;
        const retColor = (dispRet || 0) > 0 ? '#16a34a' : (dispRet || 0) < 0 ? '#dc2626' : '#64748b';
        const risk = i.risk_score ?? _estRisk(i.daily_return_pct);
        const region = regionLookup[i.id] || '—';
        return `<tr onclick="pbToggleInstrument('${i.id}')"
                    style="cursor:pointer;border-bottom:1px solid rgba(0,0,0,.05);background:${inBasket ? 'rgba(190,24,93,.04)' : 'transparent'}">
          <td style="padding:7px 8px;text-align:center">
            <input type="checkbox" ${inBasket ? 'checked' : ''} onclick="event.stopPropagation();pbToggleInstrument('${i.id}')" style="accent-color:#BE185D">
          </td>
          <td style="padding:7px 8px;font-weight:700;font-family:'IBM Plex Mono',monospace;color:${inBasket ? '#BE185D' : 'var(--text)'}">
            ${i.id}
          </td>
          <td style="padding:7px 8px">
            <span style="font-size:11px;padding:2px 8px;border-radius:100px;background:rgba(0,0,0,.06);color:var(--t2);font-weight:500">${region}</span>
          </td>
          <td style="padding:7px 8px;text-align:right;font-family:'IBM Plex Mono',monospace;font-weight:700;font-size:12px;color:${retColor}">
            ${i.return_1y_pct != null ? _fmtRet(i.return_1y_pct) : _fmtRet(i.daily_return_pct, true)}
          </td>
          <td style="padding:7px 8px">${_riskDots(risk)}</td>
          <td style="padding:7px 8px;text-align:center">
            <button onclick="event.stopPropagation();pbToggleInstrument('${i.id}')"
                    style="padding:4px 12px;border-radius:100px;border:none;
                           background:${inBasket ? 'rgba(190,24,93,1)' : 'rgba(0,0,0,.07)'};
                           color:${inBasket ? '#fff' : '#64748b'};
                           font-size:11px;font-weight:600;cursor:pointer;min-width:48px">
              ${inBasket ? 'added' : 'add'}
            </button>
          </td>
        </tr>`;
      }).join('')}
    </tbody>`;
}

// ── Guided basket — investment horizon presets ────────────────────────────────
// Labels and client-side fallback thresholds mirror investment_horizons.py.
// When the API populates inst.horizons[], that takes precedence over fallbacks.
const _HORIZON_PRESETS = {
  short_term: {
    label:       'Short Term',
    returnField: 'return_1y_pct',
    // Fallback filter (used when inst.horizons is empty — e.g., insufficient history)
    fallback:    inst => (inst.return_1y_pct ?? inst.daily_return_pct ?? 0) >= 15,
  },
  medium_term: {
    label:       'Medium Term',
    returnField: 'return_5y_pct',
    fallback:    inst => (inst.return_5y_pct ?? inst.return_1y_pct ?? inst.daily_return_pct ?? 0) >= 12,
  },
  long_term: {
    label:       'Long Term',
    returnField: 'return_15y_pct',
    fallback:    inst => (inst.return_15y_pct ?? inst.return_1y_pct ?? inst.daily_return_pct ?? 0) >= 8,
  },
};

function _draftAlloc() {
  const on = _draftItems.filter(i => i.on);
  if (!on.length) return {};

  // Optimizer mode: use backend allocation_pct per instrument
  if (_optimizerMode && _optimizerResponse && _optimizerResponse.allocations && _optimizerResponse.allocations.length) {
    const map = {};
    for (const item of on) {
      const match = _optimizerResponse.allocations.find(
        a => a.ticker.toUpperCase() === item.id.toUpperCase()
      );
      if (match) {
        map[item.id] = match.allocation_pct;
      } else {
        // Ticker not found in optimizer response — fallback to 0
        map[item.id] = 0;
      }
    }
    return map;
  }

  // Equal-weight fallback
  const base = Math.floor(100 / on.length);
  const rem  = 100 - base * on.length;
  const map  = {};
  on.forEach((i, idx) => { map[i.id] = base + (idx === 0 ? rem : 0); });
  return map;
}

function _renderDraftDonut(items) {
  if (_draftChart) { _draftChart.destroy(); _draftChart = null; }
  const canvas = document.getElementById('pb-draft-donut');
  if (!canvas) return;
  const on = items.filter(i => i.on);
  const COLORS = ['#BE185D','#9f1239','#e11d48','#f43f5e','#fb7185','#fda4af','#fecdd3'];
  if (!on.length) {
    _draftChart = new Chart(canvas, {
      type: 'doughnut',
      data: { datasets: [{ data: [1], backgroundColor: ['#f1f5f9'], borderWidth: 0 }] },
      options: { plugins: { legend: { display: false }, tooltip: { enabled: false } }, cutout: '65%', responsive: false },
    });
    return;
  }
  const alloc = _draftAlloc();
  _draftChart = new Chart(canvas, {
    type: 'doughnut',
    data: {
      labels: on.map(i => i.id),
      datasets: [{
        data: on.map(i => alloc[i.id] || 0),
        backgroundColor: on.map((_, idx) => COLORS[idx % COLORS.length]),
        borderWidth: 2,
        borderColor: '#fff',
      }],
    },
    options: {
      responsive: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: ctx => `${ctx.label}: ${ctx.parsed}%` } },
      },
      cutout: '65%',
    },
  });
}

function _updateDraftStats() {
  const on = _draftItems.filter(i => i.on);

  _setText('pb-draft-holdings', on.length || '—');

  // Mode badge
  const badgeEl = document.getElementById('pb-draft-mode-badge');
  if (badgeEl) {
    if (_optimizerMode) {
      badgeEl.textContent = 'Optimized';
      badgeEl.style.display = '';
      badgeEl.style.background = 'rgba(22,163,106,.12)';
      badgeEl.style.color = '#16a34a';
    } else {
      badgeEl.textContent = 'Equal Weight';
      badgeEl.style.display = '';
      badgeEl.style.background = 'rgba(100,116,139,.1)';
      badgeEl.style.color = '#64748b';
    }
  }

  if (_optimizerMode && _optimizerResponse) {
    // Portfolio-level metrics from optimizer
    const projEl = document.getElementById('pb-draft-proj-return');
    if (projEl) {
      projEl.textContent = _optimizerResponse.estimated_sharpe != null
        ? _optimizerResponse.estimated_sharpe.toFixed(2)
        : '—';
      projEl.style.color = (_optimizerResponse.estimated_sharpe || 0) >= 1 ? '#16a34a' : '#64748b';
    }
    const riskEl = document.getElementById('pb-draft-risk');
    if (riskEl) {
      riskEl.textContent = _optimizerResponse.estimated_mdd_pct != null
        ? _optimizerResponse.estimated_mdd_pct.toFixed(1) + '%'
        : '—';
    }
    // Sharpe and MDD stat rows
    const sharpeEl = document.getElementById('pb-draft-sharpe');
    if (sharpeEl) {
      sharpeEl.textContent = _optimizerResponse.estimated_sharpe != null
        ? _optimizerResponse.estimated_sharpe.toFixed(2)
        : '—';
      sharpeEl.style.color = (_optimizerResponse.estimated_sharpe || 0) >= 1 ? '#16a34a' : '#64748b';
    }
    const mddEl = document.getElementById('pb-draft-mdd');
    if (mddEl) {
      mddEl.textContent = _optimizerResponse.estimated_mdd_pct != null
        ? _optimizerResponse.estimated_mdd_pct.toFixed(1) + '%'
        : '—';
      mddEl.style.color = (_optimizerResponse.estimated_mdd_pct || 0) > 10 ? '#dc2626' : '#16a34a';
    }
  } else {
    // Equal-weight mode: original stats
    const avgRet  = on.length ? on.reduce((s, i) => s + (i.ret || 0), 0) / on.length : null;
    const avgRisk = on.length ? on.reduce((s, i) => s + _estRisk(i.ret), 0) / on.length : null;

    const projEl = document.getElementById('pb-draft-proj-return');
    if (projEl) {
      projEl.textContent  = avgRet != null ? _fmtRet(avgRet) : '—';
      projEl.style.color  = (avgRet || 0) >= 0 ? '#16a34a' : '#dc2626';
    }
    const riskEl = document.getElementById('pb-draft-risk');
    if (riskEl) riskEl.innerHTML = avgRisk != null ? _riskDots(Math.round(avgRisk)) : '—';

    // Hide optimizer-specific stats in equal-weight mode
    const sharpeEl = document.getElementById('pb-draft-sharpe');
    if (sharpeEl) sharpeEl.textContent = '—';
    const mddEl = document.getElementById('pb-draft-mdd');
    if (mddEl) mddEl.textContent = '—';
  }

  _renderDraftDonut(_draftItems);
}

function _renderDraftList() {
  const draftEl = document.getElementById('pb-guided-draft');
  if (!draftEl) return;
  if (!_draftItems.length) {
    draftEl.innerHTML = '<div style="padding:12px 14px;color:#94a3b8;font-size:12px">Select a goal above to see a ranked draft.</div>';
    return;
  }
  const alloc = _draftAlloc();
  draftEl.innerHTML = _draftItems.map((item, idx) => {
    const retColor = (item.ret || 0) >= 0 ? '#16a34a' : '#dc2626';
    const pct = item.on ? (alloc[item.id] || 0) : 0;
    const barW = Math.min(pct * 2, 100);

    // Optimizer mode: show per-instrument Sharpe, MDD, and metric_source
    let metricsHtml = '';
    if (_optimizerMode && _optimizerResponse && _optimizerResponse.allocations) {
      const match = _optimizerResponse.allocations.find(
        a => a.ticker.toUpperCase() === item.id.toUpperCase()
      );
      if (match && item.on) {
        const srcBadge = match.metric_source === 'model'
          ? '<span style="font-size:9px;padding:1px 4px;border-radius:3px;background:rgba(22,163,106,.12);color:#16a34a;font-weight:600">model</span>'
          : '<span style="font-size:9px;padding:1px 4px;border-radius:3px;background:rgba(100,116,139,.1);color:#64748b;font-weight:600">proxy</span>';
        metricsHtml = `<span style="font-size:10px;color:#64748b;font-family:'IBM Plex Mono',monospace;white-space:nowrap">S:${match.sharpe.toFixed(1)} MDD:${match.mdd_pct.toFixed(0)}%</span> ${srcBadge}`;
      }
    }

    return `<div style="display:flex;align-items:center;gap:10px;padding:9px 14px;border-bottom:1px solid var(--border);background:${item.on ? 'transparent' : 'rgba(0,0,0,.02)'}">
      <span style="width:16px;text-align:right;font-size:11px;color:var(--t2);font-family:'IBM Plex Mono',monospace">${idx + 1}</span>
      <span style="font-weight:700;font-size:13px;font-family:'IBM Plex Mono',monospace;width:68px">${item.id}</span>
      <span style="font-size:12px;font-weight:700;color:${retColor};font-family:'IBM Plex Mono',monospace;width:52px">${_fmtRet(item.ret)}</span>
      ${metricsHtml}
      <div style="flex:1;height:5px;border-radius:3px;background:rgba(0,0,0,.08)">
        <div style="width:${barW}%;height:100%;border-radius:3px;background:${item.on ? '#BE185D' : '#cbd5e1'}"></div>
      </div>
      <span style="font-size:11px;font-family:'IBM Plex Mono',monospace;color:var(--t2);width:32px;text-align:right">${item.on ? pct + '%' : ''}</span>
      <button onclick="pbToggleDraftItem('${item.id}')"
              style="width:38px;height:21px;border-radius:100px;border:none;
                     background:${item.on ? '#BE185D' : '#cbd5e1'};
                     cursor:pointer;position:relative;padding:0;flex-shrink:0;transition:background .2s">
        <span style="position:absolute;top:2px;${item.on ? 'right:2px' : 'left:2px'};
                     width:17px;height:17px;border-radius:50%;background:#fff"></span>
      </button>
    </div>`;
  }).join('');
}

function _horizonReturn(inst, key) {
  if (key === 'short_term')  return inst.return_1y_pct  ?? inst.daily_return_pct;
  if (key === 'medium_term') return inst.return_5y_pct  ?? inst.return_1y_pct ?? inst.daily_return_pct;
  if (key === 'long_term')   return inst.return_15y_pct ?? inst.return_1y_pct ?? inst.daily_return_pct;
  return inst.return_1y_pct ?? inst.daily_return_pct;
}

async function _applyPreset(presetKey, geo) {
  _activePreset = presetKey;
  const preset = _HORIZON_PRESETS[presetKey];
  if (!preset) return;

  // Highlight selected horizon card
  ['short_term', 'medium_term', 'long_term'].forEach(k => {
    const el = document.getElementById(`pb-preset-${k}`);
    if (!el) return;
    el.style.border     = k === presetKey ? '2px solid #BE185D' : '2px solid var(--border)';
    el.style.background = k === presetKey ? 'rgba(190,24,93,.05)' : '';
  });

  const titleEl = document.getElementById('pb-draft-title');
  if (titleEl) titleEl.textContent = preset.label;

  // Filter: use API-computed horizons[] when present, else client-side fallback
  const all = _allInstruments(geo).filter(inst => {
    if (Array.isArray(inst.horizons) && inst.horizons.length > 0) {
      return inst.horizons.includes(presetKey);
    }
    return preset.fallback(inst);
  });

  // Rank by the horizon-relevant return metric, show top 7, first 5 toggled on
  const ranked = all.slice().sort((a, b) =>
    (_horizonReturn(b, presetKey) || 0) - (_horizonReturn(a, presetKey) || 0)
  ).slice(0, 7);

  _draftItems = ranked.map((i, idx) => ({
    id: i.id,
    ret: _horizonReturn(i, presetKey),
    on: idx < 5,
  }));

  // Call optimizer endpoint — show loading state while in flight
  const fetchId = ++_optimizerFetchId;
  const draftEl = document.getElementById('pb-guided-draft');
  if (draftEl) {
    draftEl.innerHTML = '<div style="padding:12px 14px;color:#64748b;font-size:12px;display:flex;align-items:center;gap:8px"><span style="display:inline-block;width:14px;height:14px;border:2px solid #BE185D;border-top-color:transparent;border-radius:50%;animation:spin 0.8s linear infinite"></span> Optimizing...</div>';
  }

  try {
    const data = await apiFetch('/api/v1/experience/rita/optimal-allocation?horizon=' + presetKey);

    // Race-condition guard: ignore stale responses
    if (fetchId !== _optimizerFetchId) return;

    if (data && (data.solver_status === 'OPTIMAL' || data.solver_status === 'FEASIBLE')
        && Array.isArray(data.allocations) && data.allocations.length > 0) {
      _optimizerMode = true;
      _optimizerResponse = data;

      // Override draft items with optimizer allocations (ticker matching)
      _draftItems = data.allocations.map((a, idx) => {
        const existingItem = ranked.find(r => r.id.toUpperCase() === a.ticker.toUpperCase());
        return {
          id: a.ticker.toUpperCase(),
          ret: existingItem ? _horizonReturn(existingItem, presetKey) : null,
          on: true,
        };
      });

      if (titleEl) titleEl.textContent = preset.label + ' (Optimized)';
    } else {
      // Non-optimal status or empty allocations — equal-weight fallback
      _optimizerMode = false;
      _optimizerResponse = null;
    }
  } catch (e) {
    // Network error or 500 — fall back to equal-weight silently
    if (fetchId !== _optimizerFetchId) return;
    _optimizerMode = false;
    _optimizerResponse = null;
    console.warn('[PB] Optimizer fetch failed, using equal-weight:', e.message || e);
  }

  _renderDraftList();
  _updateDraftStats();
}

// ── Section loader ────────────────────────────────────────────────────────────
export async function loadPortfolioBuilder() {
  _hide('pb-error');
  _hide('pb-empty');
  _show('pb-loading');
  _hide('pb-status-msg');

  try {
    const geo = await apiFetch('/api/v1/experience/rita/geography-overview');
    _hide('pb-loading');

    if (!geo || !geo.regions || !geo.regions.length) {
      _show('pb-empty');
      _renderBasket();
      return;
    }
    _geoCache = geo;

    // Pre-fill basket from saved portfolio (silent on 401/404)
    try {
      const token = sessionStorage.getItem('auth_token');
      if (token) {
        const up = await apiFetch('/api/v1/experience/user-portfolio', {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (up && Array.isArray(up.holdings)) {
          for (const h of up.holdings) {
            if (h.instrument_id) _basket.add(h.instrument_id.toUpperCase());
          }
        }
      }
    } catch (_) {}

    _autoSelectTop5(geo);
    _renderBuckets(geo);
    _renderTable(geo);
    _renderBasket();
    _renderMap(geo);
    _applyPreset('short_term', geo);

    // Re-render basket chips whenever total EUR changes (shares/cash recalculation)
    const eurInput = document.getElementById('pb-total-eur');
    if (eurInput) eurInput.addEventListener('input', () => _renderBasket());

  } catch (e) {
    _hide('pb-loading');
    _setText('pb-error-msg', e.message || 'Failed to load portfolio data');
    _show('pb-error');
    console.error('[PB] load error:', e);
  }
}

// ── Exported actions ──────────────────────────────────────────────────────────
export function pbToggleInstrument(id) {
  if (_basket.has(id)) {
    _basket.delete(id);
    _allocationPct.delete(id);
  } else {
    _basket.add(id);
    _allocationPct.set(id, 15);
  }
  _renderBasket();
  if (_geoCache) {
    _renderBuckets(_geoCache);
    _renderTable(_geoCache);
    _renderMap(_geoCache);
  }
}

export function pbSelectAllRegion(regionKey) {
  if (!_geoCache) return;
  const apiKey = { india: 'India', us: 'US', europe: 'EU', other: 'Other' }[regionKey] || regionKey;
  const region = (_geoCache.regions || []).find(r => r.region === apiKey);
  if (!region) return;
  for (const i of region.instruments) { _basket.add(i.id); if (!_allocationPct.has(i.id)) _allocationPct.set(i.id, 15); }
  _renderBasket();
  _renderBuckets(_geoCache);
  _renderTable(_geoCache);
  _renderMap(_geoCache);
}

export function pbClearAllRegion(regionKey) {
  if (!_geoCache) return;
  const apiKey = { india: 'India', us: 'US', europe: 'EU', other: 'Other' }[regionKey] || regionKey;
  const region = (_geoCache.regions || []).find(r => r.region === apiKey);
  if (!region) return;
  for (const i of region.instruments) { _basket.delete(i.id); _allocationPct.delete(i.id); }
  _renderBasket();
  _renderBuckets(_geoCache);
  _renderTable(_geoCache);
  _renderMap(_geoCache);
}

export function pbSortTable(col) {
  if (_sortCol === col) _sortAsc = !_sortAsc;
  else { _sortCol = col; _sortAsc = (col === 'name' || col === 'region'); }
  if (_geoCache) _renderTable(_geoCache);
}

export function pbApplyGoalPreset(presetKey) {
  if (!_HORIZON_PRESETS[presetKey]) return;
  if (_geoCache) _applyPreset(presetKey, _geoCache);
}

export function pbToggleDraftItem(id) {
  const item = _draftItems.find(i => i.id === id);
  if (!item) return;
  item.on = !item.on;

  // Toggling an item OFF in optimizer mode switches to equal-weight
  if (_optimizerMode && !item.on) {
    _optimizerMode = false;
    _optimizerResponse = null;
    const titleEl = document.getElementById('pb-draft-title');
    const preset = _activePreset ? _HORIZON_PRESETS[_activePreset] : null;
    if (titleEl && preset) titleEl.textContent = preset.label;
  }

  _renderDraftList();
  _updateDraftStats();
}

export function pbBuildFromDraft() {
  const on = _draftItems.filter(i => i.on);
  if (!on.length) return;
  for (const item of on) _basket.add(item.id);
  _renderBasket();
  if (_geoCache) { _renderBuckets(_geoCache); _renderTable(_geoCache); _renderMap(_geoCache); }
  pbBuildPortfolio();
}

export function pbClearBasket() {
  _basket.clear();
  _allocationPct.clear();
  _renderBasket();
  if (_geoCache) { _renderBuckets(_geoCache); _renderTable(_geoCache); _renderMap(_geoCache); }
}

export function pbSetAlloc(id, pct) {
  _allocationPct.set(id, Math.max(0, Math.min(100, Math.round(pct) || 0)));
  _renderRegionSummary(); // summary panel reflects new totals without re-rendering chips
  // Update shares/cash for this chip without re-rendering the whole basket
  const scEl = document.getElementById(`pb-chip-sc-${id}`);
  if (scEl) {
    const totalEur = _totalEurInput();
    const price    = _priceForId(id);
    const sc       = totalEur > 0 && price ? _sharesAndCash(totalEur, _allocationPct.get(id) ?? 0, price) : null;
    scEl.style.display = sc ? 'flex' : 'none';
    scEl.style.justifyContent = 'space-between';
    scEl.style.marginTop = '4px';
    scEl.style.fontSize = '10px';
    scEl.style.fontFamily = "'IBM Plex Mono',monospace";
    scEl.innerHTML = sc
      ? `<span style="color:#16a34a;font-weight:700">${sc.shares} shares</span><span style="color:#64748b">€${sc.cash.toFixed(0)} cash</span>`
      : '';
  }
}

export async function pbBuildPortfolio() {
  if (_basket.size === 0) {
    const msg = document.getElementById('pb-status-msg');
    if (msg) { msg.textContent = 'Add at least one instrument to the basket first.'; msg.style.color = '#dc2626'; msg.style.display = ''; }
    return;
  }
  await ensureDevToken();
  const token = sessionStorage.getItem('auth_token');
  if (!token) {
    if (!isLocalDev()) {
      sessionStorage.setItem('post_login_redirect', window.location.href);
      window.location.href = '/auth/google/login?state=rita';
    }
    return;
  }
  const name = `My Portfolio ${new Date().toLocaleDateString('en-IN')}`;
  const totalValueEur = _totalEurInput() || null;
  // Use custom allocations if they sum to ~100, else fall back to equal split
  const allocSum = [..._basket].reduce((s, id) => s + (_allocationPct.get(id) ?? 0), 0);
  let baseHoldings;
  if (Math.abs(allocSum - 100) < 1) {
    baseHoldings = [..._basket]
      .map(id => ({ instrument_id: id, allocation_pct: _allocationPct.get(id) ?? 0 }))
      .filter(h => h.allocation_pct > 0);
  } else {
    const eq = Math.floor(100 / _basket.size);
    baseHoldings = [..._basket].map(id => ({ instrument_id: id, allocation_pct: eq }));
    const rem = 100 - eq * _basket.size;
    if (rem > 0) baseHoldings[0].allocation_pct += rem;
  }
  // Enrich each holding with whole-share count and cash remainder
  const holdings = baseHoldings.map(h => {
    const price = _priceForId(h.instrument_id);
    const sc    = totalValueEur && price ? _sharesAndCash(totalValueEur, h.allocation_pct, price) : null;
    return { ...h, shares: sc ? sc.shares : null, cash_eur: sc ? parseFloat(sc.cash.toFixed(2)) : null };
  });

  const buildBtn      = document.getElementById('pb-basket-build-btn');
  const draftBuildBtn = document.getElementById('pb-draft-build-btn');
  [buildBtn, draftBuildBtn].forEach(b => { if (b) { b.disabled = true; b.textContent = 'Building…'; } });
  _hide('pb-status-msg');

  try {
    await api('/api/v1/user-portfolio/', 'POST', { name, holdings, total_value_eur: totalValueEur });
    const msg = document.getElementById('pb-status-msg');
    if (msg) { msg.textContent = `Portfolio "${name}" saved with ${_basket.size} instruments.`; msg.style.color = '#16a34a'; msg.style.display = ''; }
  } catch (e) {
    const msg = document.getElementById('pb-status-msg');
    if (msg) { msg.textContent = `Save failed: ${e.message || 'Unknown error'}`; msg.style.color = '#dc2626'; msg.style.display = ''; }
  } finally {
    if (buildBtn)      buildBtn.textContent = 'Allocate';
    if (draftBuildBtn) { draftBuildBtn.disabled = false; draftBuildBtn.textContent = 'Build portfolio →'; }
    _renderRegionSummary(); // restores correct enabled/disabled state on both buttons
  }
}
