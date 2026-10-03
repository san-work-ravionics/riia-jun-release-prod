// ── Hedge Workflow — shared geography-tile instrument picker (F39) ───────────
// One renderer for #hw-exp-instrument-select and #hw-rec-instrument-select.
// Mirrors the RITA App geography panels (one .card per region, .geo-kpi tiles).
// Click only calls window.hwSelectInstrument(id) — never setUnderlying() or
// /api/v1/instrument/select. Step modules import this; it imports no shell.

import { setEl } from '../shared/utils.js';

const REGION_ORDER = ['India', 'US', 'EU', 'Other'];
const REGION_LABELS = { India: 'India', US: 'United States', EU: 'Europe', Other: 'Other' };
const REGION_CUR = { India: '₹', US: '$', EU: '€', Other: '' };

function _esc(v) {
  return String(v ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function _fmtClose(close, region) {
  if (close == null || !Number.isFinite(Number(close))) return '—';
  const sym = REGION_CUR[region] ?? '';
  return sym + Number(close).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// RITA parity: price coloured by signal, signal label underneath (neutral = 'neu').
function _delta(inst) {
  if (inst?.signal) {
    const sig = String(inst.signal);
    return { text: sig.charAt(0).toUpperCase() + sig.slice(1), cls: sig === 'bullish' ? 'pos' : sig === 'bearish' ? 'neg' : 'neu' };
  }
  const r = inst?.daily_return_pct;
  if (r != null && Number.isFinite(Number(r))) {
    const n = Number(r);
    return { text: (n > 0 ? '+' : '') + n.toFixed(2) + '%', cls: n > 0 ? 'pos' : n < 0 ? 'neg' : 'neu' };
  }
  return { text: '—', cls: 'neu' };
}

const INST_NAMES = { 'Dow Jones Industrial Average': 'Dow Jones', 'Nasdaq Composite': 'Nasdaq' };

/** Pure: build the tile-panel HTML for known ids, grouped by region. */
export function buildInstrumentTilesHtml(known, instruments, activeId) {
  const map = instruments || {};
  const groups = {};
  for (const id of known || []) {
    const region = map[id]?.region || 'Other';
    (groups[region] = groups[region] || []).push(id);
  }
  const order = [...REGION_ORDER, ...Object.keys(groups).filter((r) => !REGION_ORDER.includes(r))];
  const cards = order
    .filter((r) => groups[r]?.length)
    .map((r) => {
      const tiles = groups[r].map((id) => {
        const inst = map[id] || {};
        const d = _delta(inst);
        const active = id === activeId ? ' geo-kpi-active' : '';
        return `<div class="kpi geo-kpi${active}" style="padding:5px 6px" data-id="${_esc(id)}"
            onclick="hwSelectInstrument(this.dataset.id)">
          <div class="kpi-label" style="font-size:10px;font-weight:600;line-height:1.3;min-height:2.6em">${_esc(INST_NAMES[inst.name] || inst.name || id)}</div>
          <div class="kpi-value ${d.cls}" style="font-size:13px">${_fmtClose(inst.close, r)}</div>
          <div class="kpi-delta ${d.cls}" style="font-size:10px">${_esc(d.text)}</div>
        </div>`;
      }).join('');
      return `<div class="card">
        <div class="card-hdr"><span class="card-title">${_esc(REGION_LABELS[r] || r)}</span></div>
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(80px,1fr));gap:6px;padding:4px 0">${tiles}</div>
      </div>`;
    }).join('');
  // Same wrapper RITA uses (#geo-panels is a .card-row): regions sit side by side.
  return `<div class="card-row" style="margin-bottom:0">${cards}</div>`;
}

/** Render the tile panel into the element with id `elId`. */
export function renderInstrumentTiles(elId, hw) {
  const known = hw.knownInstruments || [];
  if (!known.length) {
    setEl(elId, `<div class="kpi-sub">—</div>`);
    return;
  }
  setEl(elId, buildInstrumentTilesHtml(known, hw.instruments, hw.instrumentId));
}
