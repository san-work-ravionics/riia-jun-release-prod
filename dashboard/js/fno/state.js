// ── Shared mutable state for all fno modules ─────────────────────────────────
// All fields are exported as properties of a single `state` object.
// Modules mutate state in place (e.g. state.positions = [...]).
// Cross-module consumers import `state` and read from it directly.

export const state = {
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
};

// Derived helper: active positions filtered by currentUnd + currentExpiry
export function activePositions() {
  return state.positions.filter(p =>
    (state.currentUnd === 'ALL' || p.und === state.currentUnd) &&
    (state.currentExpiry === 'ALL' || p.exp === state.currentExpiry)
  );
}
