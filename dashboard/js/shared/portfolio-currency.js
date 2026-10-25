// ── Portfolio currency helpers — F44 P2 (multi-currency portfolios) ───────────
// Pure module (no imports, no DOM): shared by RITA Portfolio Builder and the FnO consumers.
// A saved portfolio is held in `currency` (EUR / INR / USD, derived from its location
// server-side); legacy rows have only the EUR fields. Readers use the fallbacks below:
//   total = total_value ?? total_value_eur,  cash = cash ?? cash_eur,  currency default EUR.
// Portfolio-level amounts are formatted with the portfolio currency — never a hardcoded symbol.

export const CCY_SYMBOL = { EUR: '€', INR: '₹', USD: '$' };
// geography-overview region → instrument trading currency ('Other' → unknown)
export const REGION_CCY = { India: 'INR', US: 'USD', EU: 'EUR' };

export function portfolioTotal(p) { return p ? (p.total_value ?? p.total_value_eur ?? null) : null; }
export function holdingCash(h) { return h ? (h.cash ?? h.cash_eur ?? null) : null; }
export function portfolioCurrency(p) { return (p && p.currency) || 'EUR'; }
export function ccySymbol(ccy) { return CCY_SYMBOL[ccy] ?? ''; }
export function regionCurrency(region) { return REGION_CCY[region] ?? null; }

// Current portfolio currency for the page (set by whichever loader read the saved portfolio).
let _currency = 'EUR';
export function setPortfolioCurrency(ccy) { _currency = ccy || 'EUR'; }
export function getPortfolioCurrency() { return _currency; }
// Symbol of the current portfolio currency — use in place of a literal symbol.
export function pSym() { return ccySymbol(_currency); }

// Whole shares + leftover cash for one holding.
//   total     portfolio total in the portfolio currency
//   allocPct  allocation %
//   price     instrument price in the INSTRUMENT's currency
//   fx        instrument-currency units per 1 portfolio-currency unit (1 when the same currency)
// Returns amounts in the portfolio currency, or null when an input (or the FX rate) is missing.
// F44 P2 fix: the amount is converted to the instrument currency BEFORE the division (an EUR
// amount divided by an INR price gave share counts ~91x too low).
export function sharesAndCash(total, allocPct, price, fx = 1) {
  if (!total || !allocPct || !price || !fx) return null;
  const alloc   = total * allocPct / 100;     // portfolio currency
  const shares  = Math.floor((alloc * fx) / price);
  const actual  = (shares * price) / fx;      // back to the portfolio currency
  const cash    = alloc - actual;
  return { alloc, shares, actual, cash };
}
