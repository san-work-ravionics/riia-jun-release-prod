// ── Formatting helpers ────────────────────────────────────────────────────────

export function fmt(n) {
  return Math.abs(n).toLocaleString('en-IN', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
}

export function fmtPnl(n) {
  return n >= 0 ? `+₹${fmt(n)}` : `−₹${fmt(Math.abs(n))}`;
}

export function pnlClass(n) {
  return n >= 0 ? 'pos' : 'neg';
}
