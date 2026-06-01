// ── Portfolio Builder — Feature 28 Phase 1 ────────────────────────────────────
// Section entry point: loadPortfolioBuilder()
// API: GET /api/v1/experience/rita/geography-overview (no auth)
//      GET /api/v1/experience/user-portfolio          (JWT, silent 404)
//      POST /api/v1/user-portfolio/                   (JWT, basket build)
//
// FC-IMP verified:
//   api       — fno/api.js re-exports from shared/api.js: export async function api ✓
//   apiFetch  — fno/api.js re-exports from shared/api.js: export async function apiFetch ✓
//   apiBase   — fno/api.js re-exports from shared/api.js: export const apiBase ✓

import { api, apiFetch, apiBase } from './api.js';

// ── Basket state — persists across section re-loads ───────────────────────────
const _basket = new Set();

// Chart instance — destroyed and re-created on scatter view
let _mapChart = null;

// Sort state for table view
let _sortCol = 'name';
let _sortAsc = true;

// Cached geo data (avoid re-fetch on tab switch)
let _geoCache = null;

// ── Risk bucketing ────────────────────────────────────────────────────────────
function _estRisk(daily_return_pct) {
  // Returns 1-5 based on absolute daily return magnitude
  const abs = Math.abs(daily_return_pct || 0);
  if (abs < 0.3) return 1;
  if (abs < 0.7) return 2;
  if (abs < 1.2) return 3;
  if (abs < 2.0) return 4;
  return 5;
}

function _riskLabel(r) {
  return ['', 'Very Low', 'Low', 'Moderate', 'High', 'Very High'][r] || '—';
}

// ── Signal badge ──────────────────────────────────────────────────────────────
function _signalBadge(signal) {
  const map = { bullish: '#16a34a', bearish: '#dc2626', neutral: '#64748b' };
  const color = map[signal] || '#64748b';
  return `<span style="display:inline-block;padding:1px 6px;border-radius:100px;background:${color};color:#fff;font-size:9px;font-weight:600;font-family:'IBM Plex Mono',monospace;text-transform:uppercase">${signal || 'n/a'}</span>`;
}

// ── Basket chip ───────────────────────────────────────────────────────────────
function _basketChip(id) {
  return `<span style="display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border-radius:100px;background:rgba(190,24,93,.12);color:#BE185D;font-size:11px;font-family:'IBM Plex Mono',monospace;font-weight:600">${id} <button onclick="pbToggleInstrument('${id}')" style="background:none;border:none;color:#BE185D;cursor:pointer;font-size:13px;line-height:1;padding:0">×</button></span>`;
}

// ── Status / error helpers ────────────────────────────────────────────────────
function _show(id) { const el = document.getElementById(id); if (el) el.style.display = ''; }
function _hide(id) { const el = document.getElementById(id); if (el) el.style.display = 'none'; }
function _setHtml(id, html) { const el = document.getElementById(id); if (el) el.innerHTML = html; }
function _setText(id, txt)  { const el = document.getElementById(id); if (el) el.textContent = txt; }

// ── Render basket panel ───────────────────────────────────────────────────────
function _renderBasket() {
  const count = _basket.size;
  _setText('pb-basket-count', count === 0 ? 'Basket empty' : `${count} instrument${count === 1 ? '' : 's'} selected`);

  const listEl = document.getElementById('pb-basket-list');
  if (listEl) listEl.innerHTML = [..._basket].map(_basketChip).join('');

  const emptyMsg = document.getElementById('pb-basket-empty-msg');
  if (emptyMsg) emptyMsg.style.display = count === 0 ? '' : 'none';

  const buildBtn = document.getElementById('pb-basket-build-btn');
  if (buildBtn) buildBtn.disabled = count === 0;
}

// ── Collect all instruments flat ──────────────────────────────────────────────
function _allInstruments(geo) {
  return (geo.regions || []).flatMap(r => r.instruments || []);
}

// ── Render buckets view ───────────────────────────────────────────────────────
function _renderBuckets(geo) {
  const regionMap = { India: 'india', US: 'us', EU: 'europe', Other: 'other' };
  for (const region of (geo.regions || [])) {
    const key = regionMap[region.region] || region.region.toLowerCase();
    const container = document.getElementById(`pb-instruments-${key}`);
    if (!container) continue;
    container.innerHTML = region.instruments.map(inst => {
      const inBasket = _basket.has(inst.id);
      const ret = inst.daily_return_pct != null ? (inst.daily_return_pct >= 0 ? '+' : '') + inst.daily_return_pct.toFixed(2) + '% (est.)' : '—';
      const risk = inst.daily_return_pct != null ? `Risk ${_estRisk(inst.daily_return_pct)}/5` : '—';
      const accent = inBasket ? '#BE185D' : '#64748b';
      const bg     = inBasket ? 'rgba(190,24,93,.07)' : 'transparent';
      return `<div onclick="pbToggleInstrument('${inst.id}')" style="display:flex;align-items:center;gap:10px;padding:8px 10px;border-radius:6px;cursor:pointer;border:1px solid ${inBasket ? 'rgba(190,24,93,.3)' : 'rgba(0,0,0,.07)'};background:${bg};margin-bottom:6px;transition:background .15s" id="pb-inst-row-${inst.id}">
        <input type="checkbox" ${inBasket ? 'checked' : ''} onclick="event.stopPropagation();pbToggleInstrument('${inst.id}')" style="accent-color:#BE185D">
        <span style="flex:1;font-weight:600;font-size:13px;color:${accent}">${inst.flag || ''} ${inst.id}</span>
        <span style="font-size:11px;color:#64748b">${inst.name}</span>
        <span style="font-size:11px;color:${inst.daily_return_pct >= 0 ? '#16a34a' : '#dc2626'};font-family:'IBM Plex Mono',monospace">${ret}</span>
        <span style="font-size:10px;color:#64748b">${risk}</span>
        ${_signalBadge(inst.signal)}
      </div>`;
    }).join('') || '<div style="color:#94a3b8;font-size:12px;padding:8px">No instruments</div>';
  }
}

// ── Render scatter map ────────────────────────────────────────────────────────
function _renderMap(geo) {
  const instruments = _allInstruments(geo).filter(i => i.daily_return_pct != null && i.close != null);
  const mapNote = document.getElementById('pb-map-note');
  const mapEmpty = document.getElementById('pb-map-empty');

  if (instruments.length === 0) {
    _hide('pb-map-canvas');
    if (mapNote) mapNote.style.display = 'none';
    _show('pb-map-empty');
    return;
  }
  _show('pb-map-canvas');
  if (mapNote) mapNote.style.display = '';
  _hide('pb-map-empty');

  if (_mapChart) { _mapChart.destroy(); _mapChart = null; }

  const canvas = document.getElementById('pb-map-canvas');
  if (!canvas) return;

  const points = instruments.map(i => ({
    x: i.daily_return_pct,
    y: _estRisk(i.daily_return_pct),
    label: i.id,
    inBasket: _basket.has(i.id),
  }));

  requestAnimationFrame(() => {
    _mapChart = new Chart(canvas, {
      type: 'scatter',
      data: {
        datasets: [{
          label: 'Instruments',
          data: points.map(p => ({ x: p.x, y: p.y })),
          backgroundColor: points.map(p => p.inBasket ? 'rgba(190,24,93,.85)' : 'rgba(100,116,139,.55)'),
          pointRadius: 7,
          pointHoverRadius: 9,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: ctx => {
                const p = points[ctx.dataIndex];
                return `${p.label} — ret: ${ctx.parsed.x.toFixed(2)}% (est.) | risk: ${ctx.parsed.y}/5`;
              },
            },
          },
        },
        scales: {
          x: {
            title: { display: true, text: 'Daily Return % (est.)', font: { family: 'IBM Plex Mono', size: 10 } },
            grid: { color: 'rgba(0,0,0,.05)' },
            ticks: { font: { family: 'IBM Plex Mono', size: 10 } },
          },
          y: {
            title: { display: true, text: 'Risk Score (est.)', font: { family: 'IBM Plex Mono', size: 10 } },
            min: 0, max: 6,
            ticks: { stepSize: 1, font: { family: 'IBM Plex Mono', size: 10 }, callback: v => v > 0 && v < 6 ? `${v} ${_riskLabel(v)}` : '' },
            grid: { color: 'rgba(0,0,0,.05)' },
          },
        },
      },
    });
  });
}

// ── Render sortable table ─────────────────────────────────────────────────────
function _renderTable(geo) {
  let instruments = _allInstruments(geo);

  // Sort
  instruments = instruments.slice().sort((a, b) => {
    let av, bv;
    if (_sortCol === 'name')   { av = a.id; bv = b.id; }
    if (_sortCol === 'signal') { av = a.signal || ''; bv = b.signal || ''; }
    if (_sortCol === 'return') { av = a.daily_return_pct ?? -999; bv = b.daily_return_pct ?? -999; }
    if (_sortCol === 'risk')   { av = _estRisk(a.daily_return_pct); bv = _estRisk(b.daily_return_pct); }
    if (av === bv) return 0;
    const cmp = av < bv ? -1 : 1;
    return _sortAsc ? cmp : -cmp;
  });

  const wrap = document.getElementById('pb-table-wrap');
  const tableEmpty = document.getElementById('pb-table-empty');

  if (instruments.length === 0) {
    if (wrap) wrap.style.display = 'none';
    _show('pb-table-empty');
    return;
  }
  if (wrap) wrap.style.display = '';
  _hide('pb-table-empty');

  const table = document.getElementById('pb-table');
  if (!table) return;
  table.innerHTML = `
    <thead>
      <tr style="font-size:11px;color:#64748b;border-bottom:1px solid rgba(0,0,0,.1)">
        <th style="padding:6px 8px;text-align:left;font-weight:600">In</th>
        <th style="padding:6px 8px;text-align:left;font-weight:600;cursor:pointer" onclick="pbSortTable('name')">Ticker ${_sortCol==='name' ? (_sortAsc?'▲':'▼') : ''}</th>
        <th style="padding:6px 8px;text-align:left;font-weight:600">Name</th>
        <th style="padding:6px 8px;text-align:right;font-weight:600;cursor:pointer" onclick="pbSortTable('return')">Return (est.) ${_sortCol==='return' ? (_sortAsc?'▲':'▼') : ''}</th>
        <th style="padding:6px 8px;text-align:right;font-weight:600;cursor:pointer" onclick="pbSortTable('risk')">Risk (est.) ${_sortCol==='risk' ? (_sortAsc?'▲':'▼') : ''}</th>
        <th style="padding:6px 8px;text-align:center;font-weight:600;cursor:pointer" onclick="pbSortTable('signal')">Signal ${_sortCol==='signal' ? (_sortAsc?'▲':'▼') : ''}</th>
        <th style="padding:6px 8px;text-align:right;font-weight:600">Close</th>
      </tr>
    </thead>
    <tbody>
      ${instruments.map(i => {
        const inBasket = _basket.has(i.id);
        const ret = i.daily_return_pct != null ? (i.daily_return_pct >= 0 ? '+' : '') + i.daily_return_pct.toFixed(2) + '%' : '—';
        const retColor = i.daily_return_pct > 0 ? '#16a34a' : i.daily_return_pct < 0 ? '#dc2626' : '#64748b';
        const risk = i.daily_return_pct != null ? _estRisk(i.daily_return_pct) : '—';
        const close = i.close != null ? i.close.toLocaleString('en-IN', { maximumFractionDigits: 2 }) : '—';
        return `<tr onclick="pbToggleInstrument('${i.id}')" style="cursor:pointer;border-bottom:1px solid rgba(0,0,0,.05);background:${inBasket ? 'rgba(190,24,93,.05)' : 'transparent'}">
          <td style="padding:6px 8px;text-align:center"><input type="checkbox" ${inBasket ? 'checked' : ''} onclick="event.stopPropagation();pbToggleInstrument('${i.id}')" style="accent-color:#BE185D"></td>
          <td style="padding:6px 8px;font-weight:700;font-family:'IBM Plex Mono',monospace;color:${inBasket ? '#BE185D' : '#1e293b'}">${i.flag || ''} ${i.id}</td>
          <td style="padding:6px 8px;font-size:12px;color:#64748b">${i.name}</td>
          <td style="padding:6px 8px;text-align:right;font-family:'IBM Plex Mono',monospace;color:${retColor};font-size:12px">${ret}</td>
          <td style="padding:6px 8px;text-align:right;font-size:12px;color:#64748b">${risk !== '—' ? `${risk}/5 ${_riskLabel(risk)}` : '—'}</td>
          <td style="padding:6px 8px;text-align:center">${_signalBadge(i.signal)}</td>
          <td style="padding:6px 8px;text-align:right;font-family:'IBM Plex Mono',monospace;font-size:12px">${close}</td>
        </tr>`;
      }).join('')}
    </tbody>`;
}

// ── Render tabs ───────────────────────────────────────────────────────────────
function _showTab(tab) {
  ['buckets', 'map', 'table'].forEach(t => {
    const view = document.getElementById(`pb-view-${t}`);
    const btn  = document.getElementById(`pb-tab-${t}`);
    if (view) view.style.display = t === tab ? '' : 'none';
    if (btn) {
      btn.style.background    = t === tab ? '#BE185D' : 'transparent';
      btn.style.color         = t === tab ? '#fff' : '#64748b';
      btn.style.border        = t === tab ? '1px solid #BE185D' : '1px solid rgba(0,0,0,.12)';
    }
  });

  // Rebuild scatter on tab switch so canvas is visible (Chart.js needs visible canvas)
  if (tab === 'map' && _geoCache) _renderMap(_geoCache);
}

// ── Goal presets ──────────────────────────────────────────────────────────────
const _GOAL_PRESETS = {
  growth:    { label: 'Growth',    desc: 'High return, higher risk accepted',          signalFilter: ['bullish'],              riskMin: 3 },
  income:    { label: 'Income',    desc: 'Moderate return, lower risk preference',     signalFilter: ['neutral', 'bullish'],   riskMax: 3 },
  balanced:  { label: 'Balanced',  desc: 'Mix of growth and stability',                signalFilter: ['bullish', 'neutral'],   riskMin: 2, riskMax: 4 },
  defensive: { label: 'Defensive', desc: 'Capital preservation — low risk only',       signalFilter: ['neutral'],              riskMax: 2 },
};

function _applyPreset(presetKey, geo) {
  const preset = _GOAL_PRESETS[presetKey];
  if (!preset) return;

  const all = _allInstruments(geo);
  const draft = all.filter(i => {
    const r = _estRisk(i.daily_return_pct);
    if (preset.signalFilter && !preset.signalFilter.includes(i.signal)) return false;
    if (preset.riskMin != null && r < preset.riskMin) return false;
    if (preset.riskMax != null && r > preset.riskMax) return false;
    return true;
  });

  const draftEl = document.getElementById('pb-guided-draft');
  if (draftEl) {
    draftEl.innerHTML = draft.length === 0
      ? '<span style="color:#94a3b8;font-size:12px">No instruments match this goal with current market data.</span>'
      : draft.map(i => {
          const ret = i.daily_return_pct != null ? (i.daily_return_pct >= 0 ? '+' : '') + i.daily_return_pct.toFixed(2) + '% (est.)' : '—';
          return `<div style="display:flex;align-items:center;gap:8px;padding:5px 8px;border-radius:5px;border:1px solid rgba(0,0,0,.07);margin-bottom:4px;background:rgba(190,24,93,.04)">
            <input type="checkbox" id="pb-draft-cb-${i.id}" style="accent-color:#BE185D">
            <span style="font-weight:600;font-family:'IBM Plex Mono',monospace;font-size:12px">${i.flag || ''} ${i.id}</span>
            <span style="font-size:11px;color:#64748b;flex:1">${i.name}</span>
            <span style="font-size:11px;font-family:'IBM Plex Mono',monospace;color:${(i.daily_return_pct || 0) >= 0 ? '#16a34a' : '#dc2626'}">${ret}</span>
            ${_signalBadge(i.signal)}
          </div>`;
        }).join('');
  }

  const noteEl = document.getElementById('pb-guided-note');
  if (noteEl) noteEl.textContent = `${preset.label}: ${preset.desc}. ${draft.length} instrument${draft.length === 1 ? '' : 's'} matched.`;
}

// ── Section loader ────────────────────────────────────────────────────────────
export async function loadPortfolioBuilder() {
  _hide('pb-error');
  _hide('pb-empty');
  _show('pb-loading');
  _hide('pb-status-msg');

  // Show default tab
  _showTab('buckets');

  try {
    // Primary data: geography overview (no auth needed)
    const geo = await apiFetch('/api/v1/experience/rita/geography-overview');
    _hide('pb-loading');

    if (!geo || !geo.regions || geo.regions.length === 0) {
      _show('pb-empty');
      _renderBasket();
      return;
    }

    _geoCache = geo;

    // Pre-fill basket from user portfolio (JWT, silent on 404/401)
    try {
      const token = sessionStorage.getItem('auth_token');
      if (token) {
        const up = await apiFetch('/api/v1/experience/user-portfolio', {
          headers: { 'Authorization': `Bearer ${token}` },
        });
        if (up && Array.isArray(up.holdings)) {
          for (const h of up.holdings) {
            if (h.instrument_id) _basket.add(h.instrument_id.toUpperCase());
          }
        }
      }
    } catch (_) {
      // Silent — portfolio pre-fill is optional
    }

    // Render all views
    _renderBuckets(geo);
    _renderTable(geo);
    // Map rendered on demand when tab clicked
    _renderBasket();

  } catch (e) {
    _hide('pb-loading');
    _setText('pb-error-msg', e.message || 'Failed to load portfolio data');
    _show('pb-error');
    console.error('[PB] loadPortfolioBuilder error:', e);
  }
}

// ── Window-exported functions ─────────────────────────────────────────────────

export function pbToggleInstrument(id) {
  if (_basket.has(id)) {
    _basket.delete(id);
  } else {
    _basket.add(id);
  }
  _renderBasket();

  // Refresh all rendered views
  if (_geoCache) {
    _renderBuckets(_geoCache);
    _renderTable(_geoCache);
    // Only re-render map if map tab is active
    const mapView = document.getElementById('pb-view-map');
    if (mapView && mapView.style.display !== 'none') _renderMap(_geoCache);
  }
}

export function pbSelectAllRegion(regionKey) {
  if (!_geoCache) return;
  const regionMap = { india: 'India', us: 'US', europe: 'EU', other: 'Other' };
  const regionName = regionMap[regionKey] || regionKey;
  const region = (_geoCache.regions || []).find(r => r.region === regionName);
  if (!region) return;
  for (const i of region.instruments) _basket.add(i.id);
  _renderBasket();
  _renderBuckets(_geoCache);
  _renderTable(_geoCache);
}

export function pbClearAllRegion(regionKey) {
  if (!_geoCache) return;
  const regionMap = { india: 'India', us: 'US', europe: 'EU', other: 'Other' };
  const regionName = regionMap[regionKey] || regionKey;
  const region = (_geoCache.regions || []).find(r => r.region === regionName);
  if (!region) return;
  for (const i of region.instruments) _basket.delete(i.id);
  _renderBasket();
  _renderBuckets(_geoCache);
  _renderTable(_geoCache);
}

export function pbSortTable(col) {
  if (_sortCol === col) {
    _sortAsc = !_sortAsc;
  } else {
    _sortCol = col;
    _sortAsc = true;
  }
  if (_geoCache) _renderTable(_geoCache);
}

export function pbApplyGoalPreset(presetKey) {
  // Highlight active preset button
  ['growth', 'income', 'balanced', 'defensive'].forEach(k => {
    const btn = document.getElementById(`pb-preset-${k}`);
    if (btn) {
      btn.style.background = k === presetKey ? '#BE185D' : 'transparent';
      btn.style.color      = k === presetKey ? '#fff' : '#BE185D';
    }
  });
  if (_geoCache) _applyPreset(presetKey, _geoCache);
}

export function pbAddFromDraft() {
  // Add all checked draft items to basket
  const draftEl = document.getElementById('pb-guided-draft');
  if (!draftEl || !_geoCache) return;
  const checkboxes = draftEl.querySelectorAll('input[type=checkbox]:checked');
  for (const cb of checkboxes) {
    const id = cb.id.replace('pb-draft-cb-', '');
    if (id) _basket.add(id.toUpperCase());
  }
  _renderBasket();
  _renderBuckets(_geoCache);
  _renderTable(_geoCache);
}

export function pbClearBasket() {
  _basket.clear();
  _renderBasket();
  if (_geoCache) {
    _renderBuckets(_geoCache);
    _renderTable(_geoCache);
  }
}

export async function pbBuildPortfolio() {
  if (_basket.size === 0) {
    _setText('pb-status-msg', 'Add at least one instrument to the basket before building.');
    _show('pb-status-msg');
    return;
  }

  const token = sessionStorage.getItem('auth_token');
  if (!token) {
    _setText('pb-status-msg', 'Login required to build a portfolio. Please sign in.');
    _show('pb-status-msg');
    return;
  }

  const nameEl = document.getElementById('pb-portfolio-name');
  const name = (nameEl && nameEl.value.trim()) || `My Portfolio ${new Date().toLocaleDateString('en-IN')}`;

  const allocationPct = Math.floor(100 / _basket.size);
  const holdings = [..._basket].map(id => ({ instrument_id: id, allocation_pct: allocationPct }));

  // Adjust rounding — add remainder to first holding
  const remainder = 100 - allocationPct * _basket.size;
  if (remainder > 0 && holdings.length > 0) holdings[0].allocation_pct += remainder;

  const buildBtn = document.getElementById('pb-basket-build-btn');
  if (buildBtn) { buildBtn.disabled = true; buildBtn.textContent = 'Building…'; }
  _hide('pb-status-msg');

  try {
    await api('/api/v1/user-portfolio/', 'POST', { name, holdings });
    _setText('pb-status-msg', `Portfolio "${name}" built successfully with ${_basket.size} instruments.`);
    document.getElementById('pb-status-msg').style.color = '#16a34a';
    _show('pb-status-msg');
  } catch (e) {
    _setText('pb-status-msg', `Build failed: ${e.message || 'Unknown error'}`);
    document.getElementById('pb-status-msg').style.color = '#dc2626';
    _show('pb-status-msg');
  } finally {
    if (buildBtn) { buildBtn.disabled = _basket.size === 0; buildBtn.textContent = 'Build Portfolio'; }
  }
}

// ── Tab switcher (window-exported) ────────────────────────────────────────────
export function pbSwitchTab(tab) {
  _showTab(tab);
}
