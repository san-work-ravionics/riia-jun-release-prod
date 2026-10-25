// ── FX rates — F44 P2 ─────────────────────────────────────────────────────────
// Cached daily rates from GET /api/v1/experience/rita/fx (server reads market_data_cache only).
// Goes through api() (401 → ensureDevToken(true) → retry once on localhost). A missing rate
// (404 "no fx rate") resolves to null — callers show "FX rate unavailable", never a static rate.
import { api } from './api.js';
import { regionCurrency } from './portfolio-currency.js';

const _pending = new Map();   // 'EURINR' → Promise<number|null>
const _known   = new Map();   // 'EURINR' → number|null (resolved)

export function fxRate(base, quote) {
  if (!base || !quote) return Promise.resolve(null);
  if (base === quote) return Promise.resolve(1);
  const k = base + quote;
  if (!_pending.has(k)) {
    _pending.set(k, api(`/api/v1/experience/rita/fx?base=${base}&quote=${quote}`)
      .then(r => (r && typeof r.rate === 'number' ? r.rate : null))
      .catch(() => null)
      .then(rate => { _known.set(k, rate); return rate; }));
  }
  return _pending.get(k);
}

// Synchronous read of an already-loaded rate (1 for the same currency, null if not loaded / missing).
export function fxRateSync(base, quote) {
  if (!base || !quote) return null;
  if (base === quote) return 1;
  return _known.get(base + quote) ?? null;
}

// Load every base→quote rate needed before a synchronous render.
export function preloadFx(base, quotes) {
  return Promise.all([...new Set(quotes)].filter(q => q && q !== base).map(q => fxRate(base, q)));
}

// Instrument-currency units per 1 portfolio-currency unit for an instrument in a
// geography-overview `region` (null when the region's currency or the rate is unknown).
export function fxForRegion(portfolioCcy, region) {
  return fxRateSync(portfolioCcy, regionCurrency(region));
}
