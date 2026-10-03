// ── Hedge calculations — shared, pure, DOM-free (F39 Phase 3) ────────────────
// Extracted verbatim from portfolio-hedge.js (_estRisk, _hedgeType, _hedgeLabel,
// _isProxy, _rowParams, _buildRows, _aggregates, _hedgedPL, payoff/scenario moves)
// and equity_hedge.js (_computeNShares, covered-call margin factors) so the old
// Portfolio Hedge / Equity Hedge pages and the unified hedge workflow produce
// identical numbers. No DOM, no window, no imports — importable from node.

export const FNO_ELIGIBLE = new Set([
  'RELIANCE','TATAMOTOR','TCS','INFY','HDFCBANK','WIPRO','BAJFINANCE',
  'TATASTEEL','SBIN','ICICIBANK','KOTAKBANK','AXISBANK','SUNPHARMA','HCLTECH','LT',
  'ONGC','NTPC','POWERGRID','BPCL',
]);

// Payoff chart x-axis (-25..15) and scenario-table moves.
export const PAYOFF_MOVES = Array.from({ length: 41 }, (_, i) => i - 25);
export const SCENARIO_MOVES = [-20, -10, 0, 10];

export function estRisk(daily_return_pct) {
  const abs = Math.abs(daily_return_pct || 0);
  if (abs < 0.3) return 1;
  if (abs < 0.7) return 2;
  if (abs < 1.2) return 3;
  if (abs < 2.0) return 4;
  return 5;
}

export function hedgeType(id, region, alloc_pct) {
  if (FNO_ELIGIBLE.has(id)) return alloc_pct >= 20 ? 'put_spread' : 'protective_put';
  if (region === 'US' || region === 'EU') return 'ndx_proxy';
  return 'nifty_proxy';
}

export function hedgeLabel(type) {
  return {
    protective_put: 'Protective put',
    put_spread:     'Put spread',
    ndx_proxy:      'NDX put proxy',
    nifty_proxy:    'NIFTY put proxy',
  }[type] || type;
}

export function isProxy(type) { return type === 'ndx_proxy' || type === 'nifty_proxy'; }

export function rowParams(type, risk, coverage) {
  const c = coverage / 100;
  const strikePct = -(12 - c * 10);
  let strikeLabel;
  if (type === 'put_spread') {
    const lo = Math.round(strikePct);
    const hi = Math.round(strikePct - 6);
    strikeLabel = `${lo}/${hi}%`;
  } else {
    strikeLabel = `${Math.round(strikePct)}% OTM`;
  }
  const baseVol    = risk * 0.065;
  const costPct    = isProxy(type)
    ? baseVol * 0.28 * (0.4 + c * 0.6)
    : baseVol * 0.40 * (0.4 + c * 0.6);
  const protectedPct = Math.round((30 + c * 50) * (isProxy(type) ? 0.85 : 1));
  return { strikePct, strikeLabel, costPct, protectedPct };
}

// portfolioHoldings: user-portfolio holdings; instruments: id -> {..geo instrument, region};
// apiHedge: GET portfolio-hedge response (or null); checkedSet: Set of hedged ids.
export function buildRows(portfolioHoldings, instruments, apiHedge, checkedSet, coverage) {
  const apiMap = {};
  if (apiHedge && Array.isArray(apiHedge.holdings)) {
    for (const h of apiHedge.holdings) apiMap[h.instrument_id] = h;
  }

  return (portfolioHoldings || [])
    .filter(h => checkedSet.has(h.instrument_id))
    .map(h => {
      const inst   = (instruments || {})[h.instrument_id] || {};
      const region = inst.region || 'Other';
      const api    = apiMap[h.instrument_id];

      if (api) {
        return {
          id:           h.instrument_id,
          weight:       h.allocation_pct,
          ret:          api.return_1y_pct ?? inst.daily_return_pct,
          risk:         api.risk_score ?? estRisk(inst.daily_return_pct),
          region,
          type:         api.hedge_type,
          label:        hedgeLabel(api.hedge_type),
          proxy:        isProxy(api.hedge_type),
          strikePct:    api.strike_pct,
          strikeLabel:  api.strike_label,
          costPct:      api.cost_pct,
          protectedPct: api.protected_pct,
        };
      }

      const risk   = estRisk(inst.daily_return_pct);
      const ret    = inst.return_1y_pct ?? inst.daily_return_pct;
      const type   = hedgeType(h.instrument_id, region, h.allocation_pct);
      const params = rowParams(type, risk, coverage);
      return {
        id: h.instrument_id, weight: h.allocation_pct, ret, risk, region,
        type, label: hedgeLabel(type), proxy: isProxy(type), ...params,
      };
    });
}

export function aggregates(rows, apiHedge) {
  if (!rows.length) return { totalCost: 0, avgStrike: 0, maxDdHedged: 0, maxDdUnhedged: -22 };
  const totalCost     = rows.reduce((s, r) => s + r.costPct * (r.weight / 100), 0);
  const avgStrike     = rows.reduce((s, r) => s + r.strikePct * (r.weight / 100), 0);
  const maxDdHedged   = Math.max(avgStrike - totalCost, -25);
  const maxDdUnhedged = apiHedge?.aggregate?.max_dd_unhedged_pct ?? -22;
  return { totalCost, avgStrike, maxDdHedged, maxDdUnhedged };
}

// tab: 'pp' protective put | 'ps' put spread | anything else = collar
export function hedgedPL(m, tab, avgStrike, totalCost) {
  if (tab === 'pp') return Math.max(m, avgStrike) - totalCost;
  if (tab === 'ps') {
    const lo = avgStrike;
    const hi = avgStrike - 5;
    if (m > lo) return m - totalCost * 0.65;
    if (m > hi) return lo - totalCost * 0.65;
    return m + (lo - hi) - totalCost * 0.65;
  }
  return Math.max(Math.min(m, 5), avgStrike) - totalCost;
}

// Whole-number shares: pre-computed integer shares from the portfolio builder, else
// floor(allocation value / price). holding = {shares, allocation_pct}; inst = {close}.
// Returns 10 when allocation/price cannot be derived (same as old Equity Hedge).
export function computeNShares(holding, inst, totalValueEur) {
  if (holding?.shares != null && holding.shares > 0) return holding.shares;
  const total    = parseFloat(totalValueEur || 0);
  const allocPct = parseFloat(holding?.allocation_pct || 0);
  if (!total || !allocPct) return 10;
  const allocEur = total * allocPct / 100;
  const price    = parseFloat(inst?.close || 0);
  if (!price) return 10;
  return Math.floor(allocEur / price) || 1;
}

// Covered-call margin split. Moved verbatim from equity_hedge.js injectAsmlToState
// (ccMarginSpan = max_value_eur * 0.12, ccMarginExp = max_value_eur * 0.08).
export function coveredCallMargin(mb) {
  const span     = mb.max_value_eur * 0.12;
  const exposure = mb.max_value_eur * 0.08;
  return { span, exposure, total: span + exposure };
}

// Estimated (BSM) margin for the chosen equity hedge — exact injectAsmlToState formula:
// covered call needs margin; a long put is just the premium paid.
export function estimateEquityHedgeMargin(eqScenarios, strategy) {
  const hs = eqScenarios?.hedge_scenarios;
  if (!hs) return null;
  if (strategy === 'call_sell') {
    if (!hs.mild_bearish) return null;
    return coveredCallMargin(hs.mild_bearish).total;
  }
  if (!hs.strong_bearish) return null;
  return Math.abs(hs.strong_bearish.total_premium_eur);
}
