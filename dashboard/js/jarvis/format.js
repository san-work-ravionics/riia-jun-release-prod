// Jarvis — number / date / location formatting (plain text; callers escape before innerHTML).

const DASH = '—';

export function isNum(v) {
  return typeof v === 'number' && Number.isFinite(v);
}

// Fraction → "7.7%" (rates, returns, distances).
export function fmtRate(v, digits = 1) {
  if (!isNum(v)) return DASH;
  return `${(v * 100).toFixed(digits)}%`;
}

// Gap in percentage points: "+1.2 pp" / "−0.4 pp".
export function fmtPp(v, digits = 1) {
  if (!isNum(v)) return DASH;
  const s = (v * 100).toFixed(digits);
  return `${v > 0 ? '+' : ''}${s} pp`;
}

// Already a percentage (geography-overview *_pct fields, ×100 server-side) → "+12.3%" / "−4.0%".
export function fmtPctPoint(v, digits = 1) {
  if (!isNum(v)) return DASH;
  return `${v > 0 ? '+' : ''}${v.toFixed(digits)}%`;
}

export function fmtMoney(v, ccy) {
  if (!isNum(v)) return DASH;
  try {
    return new Intl.NumberFormat(undefined, { style: 'currency', currency: ccy || 'EUR', maximumFractionDigits: 0 }).format(v);
  } catch {
    return `${ccy || ''} ${Math.round(v).toLocaleString()}`.trim();
  }
}

export function fmtNum(v, digits = 2) {
  if (!isNum(v)) return DASH;
  return v.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function fmtYears(v) {
  if (!isNum(v)) return DASH;
  return Number.isInteger(v) ? String(v) : v.toFixed(1);
}

// ISO date / datetime → "YYYY-MM-DD".
export function fmtDate(v) {
  if (!v) return DASH;
  return String(v).slice(0, 10);
}

// Location keys (journey/API) and region codes (geography, as portfolio-builder _regionDisplay).
const _LOC = { europe: 'Europe', india: 'India', us: 'US', EU: 'Europe', India: 'India', US: 'US', Other: 'Other' };

export function locationName(loc) {
  return _LOC[loc] || String(loc || '');
}
