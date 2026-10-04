// ── Exposure step — position value chart (F40 Phase 3) ───────────────────────
// Monthly OHLC of position value (stored shares × close, in the instrument's own currency,
// no FX) with ±1σ monthly lines, drawn into the existing hw-exp-candle-* card via the
// shared hedge-charts.js renderer. Data: GET /api/v1/experience/fno/position-value (one
// instrument). The ±1σ is the PRICE σ scaled by shares (constant shares => value σ == price
// σ); the caller passes the same vol the Monthly σ tiles use so tiles and lines agree.
//
// Reads from the response item: instrument_id, status, message, currency, currency_symbol,
// shares, last_value, bands{plus_1sigma_value, minus_1sigma_value, plus_1sigma_pct,
// minus_1sigma_pct}, daily[{date, value}].
import { api } from './api.js';
import { setEl } from '../shared/utils.js';
import { renderMonthlyCandles, BAND_COLORS } from './hedge-charts.js';
import { state } from './state.js';

const _MONTHS = 12;

function _esc(v) {
  return String(v ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function _cacheKey(id, volPct) {
  return `${id}|${volPct != null && volPct > 0 ? Number(volPct).toFixed(4) : ''}`;
}

// Cached per (instrument, vol) in state.hedgeWorkflow.positionValue; reset on a full
// Exposure reload. Throws on API failure (caller shows "Position value unavailable").
export async function loadPositionValue(id, volPct) {
  const cache = (state.hedgeWorkflow.positionValue ||= {});
  const key = _cacheKey(id, volPct);
  if (cache[key]) return cache[key];
  let path = `/api/v1/experience/fno/position-value?instrument=${encodeURIComponent(id)}&months=${_MONTHS}`;
  if (volPct != null && volPct > 0) path += `&ann_vol_pct=${encodeURIComponent(Number(volPct))}`;
  const res = await api(path);
  const item = res?.items?.[0];
  if (!item) throw new Error('empty position-value response');
  cache[key] = item;
  return item;
}

function _fmtInt(v) {
  return Number(v).toLocaleString('en-US', { maximumFractionDigits: 0 });
}

// Card title for an item (already HTML-escaped).
export function positionValueTitle(item) {
  const id = _esc(item?.instrument_id || '');
  if (!item || item.status !== 'ok') return `Position value — ${id}`;
  const ccy = item.currency ? `, ${_esc(item.currency)}` : '';
  return `Position value — ${id} (shares × price${ccy}), ${_fmtInt(item.shares)} shares`;
}

// ±1σ monthly lines on the value series (labels carry the % move); [] when bands unavailable.
export function positionValueBands(item) {
  const b = item?.bands;
  if (!b) return [];
  return [
    { label: `+1σ monthly (+${Number(b.plus_1sigma_pct).toFixed(1)}%)`, value: b.plus_1sigma_value, color: BAND_COLORS.up, dash: [3, 3] },
    { label: `−1σ monthly (−${Math.abs(Number(b.minus_1sigma_pct)).toFixed(1)}%)`, value: b.minus_1sigma_value, color: BAND_COLORS.down, dash: [3, 3] },
  ];
}

// Draws (or clears) the candle card; returns the Chart instance to pass back as prevChart.
export function renderPositionValue(id, item, prevChart) {
  if (!item || item.status !== 'ok' || !Array.isArray(item.daily) || item.daily.length < 2) {
    setEl('hw-exp-candle-title', positionValueTitle(item || { instrument_id: id }));
    setEl('hw-exp-candle-msg', _esc(item?.message || `Position value unavailable for ${id}.`));
    return renderMonthlyCandles('hw-exp-candle-chart', [], { prev: prevChart });
  }
  const sym = item.currency_symbol || '';
  const daily = item.daily.map((d) => ({ date: d.date, price: d.value }));
  const chart = renderMonthlyCandles('hw-exp-candle-chart', daily, {
    fmt: (v) => sym + Number(v).toLocaleString('en-US', { maximumFractionDigits: 0 }),
    bands: positionValueBands(item),
    beginAtZero: false,
    prev: prevChart,
  });
  setEl('hw-exp-candle-title', positionValueTitle(item));
  setEl('hw-exp-candle-msg', item.bands ? '' : 'Volatility unavailable; ±1σ lines hidden.');
  return chart;
}
