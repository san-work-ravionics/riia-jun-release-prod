export const MOCK_MODE = false;

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
