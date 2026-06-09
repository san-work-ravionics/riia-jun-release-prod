export const MOCK_MODE = false;

// ── Volatile mock data (used regardless of MOCK_MODE) ──────────────────────────
const MOCK_VOLATILE = {
  ASML: {
    select: {
      game_id: 'volatile-asml-001', instrument: 'ASML', currency: 'EUR', starting_capital: 5000,
      warmup_days: [
        { date: '2025-07-11', close: 679.98 },
        { date: '2025-07-14', close: 683.36 }
      ],
      game_days: [
        { date: '2025-07-15', close: 702.05 },
        { date: '2025-07-16', close: 622.21 },
        { date: '2025-07-17', close: 646.47 },
        { date: '2025-07-18', close: 629.87 },
        { date: '2025-07-21', close: 620.52 },
        { date: '2025-07-22', close: 598.94 },
        { date: '2025-07-23', close: 603.12 },
        { date: '2025-07-24', close: 612.37 }
      ]
    },
    ai: [
      { ai_action:'HOLD', compliance_status:'pass',    compliance_rule:'Pre-earnings caution gate',   ai_insight:'Earnings due after close — holding position ahead of release.' },
      { ai_action:'SELL', compliance_status:'flagged', compliance_rule:'Extreme volatility threshold', ai_insight:'Earnings shock: guidance cut confirmed — exiting on extreme volatility flag.' },
      { ai_action:'HOLD', compliance_status:'pass',    compliance_rule:'Drawdown gate',               ai_insight:'Relief bounce — monitoring for confirmation before re-entry.' },
      { ai_action:'HOLD', compliance_status:'pass',    compliance_rule:'Sector exposure check',       ai_insight:'Bounce fading — standing aside, no clear signal.' },
      { ai_action:'HOLD', compliance_status:'pass',    compliance_rule:'Drawdown gate',               ai_insight:'Selling pressure continues — maintaining cash position.' },
      { ai_action:'BUY',  compliance_status:'pass',    compliance_rule:'Position limit check',        ai_insight:'Oversold at -14% off pre-earnings high — initiating position near support.' },
      { ai_action:'HOLD', compliance_status:'pass',    compliance_rule:'Sector exposure check',       ai_insight:'Stabilising — holding and monitoring for recovery signal.' },
      { ai_action:'SELL', compliance_status:'pass',    compliance_rule:'End-of-period gate',          ai_insight:'Period close — liquidating position at market.' }
    ]
  },
  NVIDIA: {
    select: {
      game_id: 'volatile-nvidia-001', instrument: 'NVIDIA', currency: 'USD', starting_capital: 5000,
      warmup_days: [
        { date: '2025-02-06', close: 128.40 },
        { date: '2025-02-07', close: 131.20 }
      ],
      game_days: [
        { date: '2025-02-10', close: 124.80 },
        { date: '2025-02-11', close: 120.30 },
        { date: '2025-02-12', close: 117.60 },
        { date: '2025-02-13', close: 124.10 },
        { date: '2025-02-14', close: 121.50 },
        { date: '2025-02-18', close: 116.20 },
        { date: '2025-02-19', close: 111.80 },
        { date: '2025-02-20', close: 108.40 }
      ]
    },
    ai: [
      { ai_action:'SELL', compliance_status:'pass',    compliance_rule:'Volatility gate',       ai_insight:'DeepSeek shock continuing — exiting AI exposure.' },
      { ai_action:'HOLD', compliance_status:'pass',    compliance_rule:'Drawdown gate',         ai_insight:'Further downside possible — holding cash.' },
      { ai_action:'BUY',  compliance_status:'pass',    compliance_rule:'Position limit check',  ai_insight:'Oversold — partial entry at technical support.' },
      { ai_action:'SELL', compliance_status:'flagged', compliance_rule:'Consecutive loss gate', ai_insight:'Support broken — flagging and exiting to protect capital.' },
      { ai_action:'HOLD', compliance_status:'pass',    compliance_rule:'Drawdown gate',         ai_insight:'Consolidating — no clear entry signal yet.' },
      { ai_action:'BUY',  compliance_status:'pass',    compliance_rule:'Position limit check',  ai_insight:'Base forming — re-entering with tighter stop.' },
      { ai_action:'HOLD', compliance_status:'pass',    compliance_rule:'Sector exposure check', ai_insight:'Holding — monitoring for recovery confirmation.' },
      { ai_action:'SELL', compliance_status:'pass',    compliance_rule:'End-of-period gate',    ai_insight:'Period close — liquidating all positions at market.' }
    ]
  }
};

export function selectVolatileDays(instrument) {
  const key = instrument === 'NVIDIA' ? 'NVIDIA' : 'ASML';
  return { ...MOCK_VOLATILE[key].select };
}

export function runDayVolatile(instrument, day_index) {
  const key = instrument === 'NVIDIA' ? 'NVIDIA' : 'ASML';
  return { ...MOCK_VOLATILE[key].ai[day_index] };
}

function apiBase() {
  return window.location.origin;
}

const MOCK_DAYS = {
  game_id: 'mock-game-001',
  instrument: 'ASML',
  currency: 'EUR',
  starting_capital: 5000,
  warmup_days: [
    { date: '2025-01-06', close: 678.50 },
    { date: '2025-01-07', close: 682.10 }
  ],
  game_days: [
    { date: '2025-01-08', close: 675.30 },
    { date: '2025-01-09', close: 671.80 },
    { date: '2025-01-10', close: 680.00 },
    { date: '2025-01-13', close: 685.40 },
    { date: '2025-01-14', close: 679.90 },
    { date: '2025-01-15', close: 692.20 },
    { date: '2025-01-16', close: 688.70 },
    { date: '2025-01-17', close: 695.00 },
    { date: '2025-01-20', close: 701.50 },
    { date: '2025-01-21', close: 698.30 }
  ]
};

const MOCK_AI = [
  { ai_action: 'BUY',  compliance_status: 'pass',    compliance_rule: 'Position limit check',  ai_insight: 'Bull momentum confirmed — entering long at day close.' },
  { ai_action: 'SELL', compliance_status: 'pass',    compliance_rule: 'Drawdown gate',         ai_insight: 'Short-term reversal signal — taking profit.' },
  { ai_action: 'BUY',  compliance_status: 'pass',    compliance_rule: 'Position limit check',  ai_insight: 'Momentum recovering — re-entering long.' },
  { ai_action: 'HOLD', compliance_status: 'pass',    compliance_rule: 'Sector exposure check', ai_insight: 'No new signal — holding current position.' },
  { ai_action: 'SELL', compliance_status: 'pass',    compliance_rule: 'Drawdown gate',         ai_insight: 'Profit target reached — exiting position.' },
  { ai_action: 'BUY',  compliance_status: 'pass',    compliance_rule: 'Position limit check',  ai_insight: 'New breakout signal — entering long.' },
  { ai_action: 'HOLD', compliance_status: 'flagged', compliance_rule: 'Consecutive loss gate', ai_insight: 'Signal strength marginal — flagged for review but action recorded.' },
  { ai_action: 'SELL', compliance_status: 'pass',    compliance_rule: 'Drawdown gate',         ai_insight: 'Volatility spike detected — reducing exposure.' },
  { ai_action: 'SELL', compliance_status: 'pass',    compliance_rule: 'Position limit check',  ai_insight: 'Trend weakening — taking defensive position.' },
  { ai_action: 'SELL', compliance_status: 'pass',    compliance_rule: 'End-of-period gate',    ai_insight: 'Final day — closing all positions at market.' }
];

export async function selectDays(instrument, start_date, end_date) {
  if (MOCK_MODE) return { ...MOCK_DAYS, instrument, currency: instrument === 'NVIDIA' ? 'USD' : 'EUR' };
  const res = await fetch(`${apiBase()}/api/experience/invest-game/select-days`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ instrument, start_date, end_date })
  });
  if (!res.ok) throw new Error(`select-days failed: ${res.status}`);
  return res.json();
}

export async function runDay(game_id, day_index, user_action) {
  if (MOCK_MODE) return { ...MOCK_AI[day_index] };
  const res = await fetch(`${apiBase()}/api/experience/invest-game/run-day`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ game_id, day_index, user_action })
  });
  if (!res.ok) throw new Error(`run-day failed: ${res.status}`);
  return res.json();
}

export async function getResult(game_id) {
  if (MOCK_MODE) return { winner: 'tbd' };
  const res = await fetch(`${apiBase()}/api/experience/invest-game/${game_id}/result`);
  if (!res.ok) throw new Error(`result failed: ${res.status}`);
  return res.json();
}
