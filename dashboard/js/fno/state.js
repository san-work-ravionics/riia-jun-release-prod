// ── Shared mutable state for all fno modules ─────────────────────────────────
// All fields are exported as properties of a single `state` object.
// Modules mutate state in place (e.g. state.positions = [...]).
// Cross-module consumers import `state` and read from it directly.

export const state = {
  portfolioMeta: null,
  analyticsMode: 'mock',
  portfolioGeoInstruments: null,  // [{id, name, region, allocation_pct}] — built at init from DB
  marketData: {},
  positions: [],
  greeksData: [],
  closedPositions: [],
  realizedPnl: 0,
  portDelta: {},
  netGreeks: {},
  scenarioLevels: {},
  marginData: {},
  stressData: [],
  payoffData: {},
  hedgeQuality: {},
  equityHedgeData: null,

  // UI state
  riskSelectedInstrument: null,   // null = Portfolio (all), or instrument id string
  currentUnd: 'ALL',
  currentExpiry: 'ALL',
  currentPosFilter: 'ALL',
  paperMode: true,          // true = paper/dummy data, false = live broker data

  // Chart references (owned by the module that creates them)
  segChart: null,
  dpChart: null,
  marginChart: null,
  payoffChart: null,
  payoffChartBnkn: null,

  // ── Unified Hedge Workflow (F39 Phase 2) ───────────────────────────────────
  // Shared across hedge-workflow.js's shell + Exposure step this phase; the
  // Recommendation/What-if/Save fields (recommendation, selections, coverage,
  // duration, scenarioTab, payoff, marginImpact, hedgedIds) are populated by
  // the Phase 3 modules — declared here now so the shape is stable across phases.
  hedgeWorkflow: {
    instrumentId: null,
    exposureScope: 'PORTFOLIO',   // Exposure-step Greeks scope: 'PORTFOLIO' or an instrument id
    knownInstruments: [],
    shares: null,
    cashEur: null,
    holdings: [],                 // legacy (exposure holdings table removed); unused
    greeks: [],                   // analytics greeks list (und, allocation_pct, ann_vol_pct)
    priceHistory: {},             // id -> {daily, currency, holding} (equity-hedge-scenarios)
    positions: [],
    netGreeks: {},
    hedgeQuality: { positions: [] },
    recommendation: null,
    selections: {},
    coverage: 50,
    duration: '1y',
    scenarioTab: 'pp',            // DB column NOT NULL — never null
    payoff: null,                 // {moves, hedged, unhedged, aggregates} (What-if)
    marginImpact: null,           // {amount, currency, source:'kite'|'estimated', instrumentId, strategy}
    hedgedIds: [],
    // ── Phase 3 additions ────────────────────────────────────────────────────
    portfolioHoldings: [],        // user-portfolio holdings (instrument_id, allocation_pct, shares, cash_eur)
    instruments: {},              // id -> geography-overview instrument + region
    totalValueEur: null,
    apiHedge: null,               // GET portfolio-hedge response
    advisor: { key: null, data: null, error: null },  // key = `${instrumentId}|${nShares}`
    eqScenarios: {},              // `${id}|${nShares}` -> equity-hedge-scenarios response
    savedPlan: null,              // last hedge-plan row (GET / PUT response)
    saveStatus: 'idle',           // 'idle' | 'saving' | 'saved' | 'error'
    savedAt: null,
    history: { plan: null, actions: [] },
    dirty: false,                 // user changed coverage/toggle/tab since last PUT
    hedgedDefaulted: false,       // first-visit "all holdings hedged" default applied
    exposureLoadedAt: null,
    step: 'exposure',
    reached: new Set(['exposure']),
    // Addendum (F39 Phase 2 — Zerodha/fno-margin-fetch): best-effort live
    // overlay. Distinct from marginImpact (BSM/computed What-if figure) above —
    // liveData.margin is the live Kite margin figure. Do not conflate the two.
    liveData: {
      available: false,
      source: 'fallback',
      lotSize: null,
      quote: null,
      margin: null,
      fetchedAt: null,
    },
  },
};

// Derived helper: active positions filtered by currentUnd + currentExpiry
export function activePositions() {
  return state.positions.filter(p =>
    (state.currentUnd === 'ALL' || p.und === state.currentUnd) &&
    (state.currentExpiry === 'ALL' || p.exp === state.currentExpiry)
  );
}
