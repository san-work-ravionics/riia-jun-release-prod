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
  hedgeHistory: {},
  hedgeHistoryLoaded: false,
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
  hedgeTimelineChart: null,

  // ── Unified Hedge Workflow (F39 Phase 2) ───────────────────────────────────
  // Shared across hedge-workflow.js's shell + Exposure step this phase; the
  // Recommendation/What-if/Save fields (recommendation, selections, coverage,
  // duration, scenarioTab, payoff, marginImpact, hedgedIds) are populated by
  // the Phase 3 modules — declared here now so the shape is stable across phases.
  hedgeWorkflow: {
    instrumentId: null,
    knownInstruments: [],
    shares: null,
    cashEur: null,
    holdings: [],
    positions: [],
    netGreeks: {},
    hedgeQuality: { positions: [] },
    recommendation: null,
    selections: {},
    coverage: 50,
    duration: '1y',
    scenarioTab: null,
    payoff: null,
    marginImpact: null,
    hedgedIds: [],
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
