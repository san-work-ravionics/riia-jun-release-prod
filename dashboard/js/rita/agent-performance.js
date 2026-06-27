// ── Agent Performance (Feature 32) ──────────────────────────
// Per-agent scorecards, KPI cards, invocation chart, and detail table for the
// 7 investment-workflow (RL trading-decision) agents. Visual language mirrors
// the Ops "Agent Builds" page: one scorecard panel per agent measured on four
// improvable parameters, plus a click-to-expand chart and a detail table.
//
// DEMO DATA: realized RL-agent scoring (Outcome Match, Avg RL Reward, Data
// Coverage) is produced by Phases 3–5, which are not yet built. Until then we
// render illustrative MOCK_AGENTS so the page conveys the intended view. The
// live endpoint is still queried and, where it already has rows, its real
// invocation count / outcome-match rate override the mock values per agent —
// so the page upgrades itself to live data as instrumentation accrues.
import { api } from './api.js';
import { setEl, badge } from './utils.js';
import { mkChart, C } from './charts.js';

// One stable colour per agent slot (same hue in chart + scorecards).
const AGENT_PALETTE = [C.run, C.build, C.mon, C.warn, '#0E7490', '#BE185D', C.danger];

// The 4 measurable / improvable parameters per RL agent:
//   outcome_match  — % of recommendations whose realized outcome matched the call (accuracy)
//   avg_reward     — mean RL reward signal per decision (the training target), 0–1 normalised
//   data_coverage  — % of invocations that had complete input features (grounding)
//   invocations    — activity count over the last 30 days
// trend = signed 30d-vs-prior-30d change in invocations.
const MOCK_AGENTS = [
  { agent_name: 'Financial Goal',    outcome_match: 0.82, avg_reward: 0.74, data_coverage: 0.98, invocations: 64, trend:  0.12 },
  { agent_name: 'Sentiment Analyst', outcome_match: 0.61, avg_reward: 0.48, data_coverage: 0.55, invocations: 38, trend: -0.06 },
  { agent_name: 'Technical Analyst', outcome_match: 0.78, avg_reward: 0.69, data_coverage: 0.95, invocations: 91, trend:  0.08 },
  { agent_name: 'Strategy Analyst',  outcome_match: 0.74, avg_reward: 0.71, data_coverage: 0.90, invocations: 57, trend:  0.03 },
  { agent_name: 'Scenario Analyst',  outcome_match: 0.69, avg_reward: 0.63, data_coverage: 0.88, invocations: 44, trend:  0.15 },
  { agent_name: 'Execution Analyst', outcome_match: 0.71, avg_reward: 0.66, data_coverage: 0.82, invocations: 29, trend:  0.21 },
  { agent_name: 'Outcome Analyst',   outcome_match: 0.85, avg_reward: 0.79, data_coverage: 0.93, invocations: 33, trend:  0.05 },
];

const pct = v => (v == null ? '—' : `${Math.round(v * 100)}%`);

// trend is a signed 0–1 ratio (or null) → coloured signed badge.
function fmtTrend(trend) {
  if (trend == null) return '<span class="badge neu">—</span>';
  const p = (trend * 100).toFixed(1);
  if (trend > 0) return `<span class="badge ok">▲ +${p}%</span>`;
  if (trend < 0) return `<span class="badge err">▼ ${p}%</span>`;
  return '<span class="badge neu">0.0%</span>';
}

// Merge any live rows from the endpoint over the mock baseline so the page
// becomes "real" agent-by-agent as instrumentation data accrues.
function _mergeLive(mock, liveAgents) {
  const byName = {};
  for (const a of (liveAgents || [])) byName[a.agent_name] = a;
  return mock.map(m => {
    const live = byName[m.agent_name];
    if (!live || (live.invocation_count_30d ?? 0) === 0) return m;
    return {
      ...m,
      invocations:   live.invocation_count_30d,
      outcome_match: live.outcome_match_rate != null ? live.outcome_match_rate : m.outcome_match,
      trend:         live.trend_vs_prior_30d != null ? live.trend_vs_prior_30d : m.trend,
    };
  });
}

export async function loadAgentPerformance() {
  let agents = MOCK_AGENTS;
  try {
    const data = await api('/api/v1/experience/rita/agent-performance');
    agents = _mergeLive(MOCK_AGENTS, data && data.agents);
  } catch (e) {
    // Endpoint unavailable — fall back to the illustrative baseline.
  }

  // ── Aggregate KPIs ──
  const avg = sel => agents.reduce((s, a) => s + sel(a), 0) / agents.length;
  setEl('agent-perf-total', String(agents.reduce((s, a) => s + a.invocations, 0)));
  setEl('agent-perf-match', pct(avg(a => a.outcome_match)));
  setEl('agent-perf-reward', avg(a => a.avg_reward).toFixed(2));
  setEl('agent-perf-coverage', pct(avg(a => a.data_coverage)));

  // ── Scorecards ──
  _renderScorecards(agents);

  // ── Invocation chart ──
  _renderChart(agents);

  // ── Detail table ──
  const rows = agents.map(a => `
    <tr>
      <td style="font-weight:600">${a.agent_name}</td>
      <td style="text-align:right;font-family:var(--fm)">${pct(a.outcome_match)}</td>
      <td style="text-align:right;font-family:var(--fm)">${a.avg_reward.toFixed(2)}</td>
      <td style="text-align:right;font-family:var(--fm)">${pct(a.data_coverage)}</td>
      <td style="text-align:right;font-family:var(--fm)">${a.invocations}</td>
      <td style="text-align:right">${fmtTrend(a.trend)}</td>
    </tr>`).join('');
  setEl('agent-perf-table', rows ||
    '<tr><td colspan="6" class="empty">No agent activity recorded yet.</td></tr>');

  setEl('agent-perf-updated', new Date().toLocaleString());
}

function _renderScorecards(agents) {
  const cards = agents.map((a, i) => {
    const barW = Math.round((a.outcome_match ?? 0) * 100);
    const covW = Math.round((a.data_coverage ?? 0) * 100);
    return `<div class="agp-sc">
      <div class="agp-sc-role">
        <span>${a.agent_name}</span>
        <span style="width:8px;height:8px;border-radius:50%;background:${AGENT_PALETTE[i % AGENT_PALETTE.length]};flex-shrink:0"></span>
      </div>
      <div class="agp-sc-row">
        <span class="agp-sc-lbl">Outcome Match</span>
        <span class="agp-sc-val"><span class="agp-bar-wrap"><span class="agp-bar" style="width:${barW}%"></span></span>&nbsp;${pct(a.outcome_match)}</span>
      </div>
      <div class="agp-sc-row">
        <span class="agp-sc-lbl">Avg RL Reward</span>
        <span class="agp-sc-val">${a.avg_reward.toFixed(2)}</span>
      </div>
      <div class="agp-sc-row">
        <span class="agp-sc-lbl">Data Coverage</span>
        <span class="agp-sc-val" style="color:var(${covW < 70 ? '--warn' : '--t2'})"><span class="agp-bar-wrap"><span class="agp-bar" style="width:${covW}%;background:var(${covW < 70 ? '--warn' : '--build'})"></span></span>&nbsp;${pct(a.data_coverage)}</span>
      </div>
      <div class="agp-sc-row">
        <span class="agp-sc-lbl">Invocations (30d)</span>
        <span class="agp-sc-val">${a.invocations} ${fmtTrend(a.trend)}</span>
      </div>
    </div>`;
  }).join('');
  setEl('agent-perf-scorecards', cards || '<div class="empty">No agents.</div>');
}

function _renderChart(agents) {
  mkChart('agent-perf-chart', {
    type: 'bar',
    data: {
      labels: agents.map(a => a.agent_name),
      datasets: [{
        label: 'Invocations (30d)',
        data: agents.map(a => a.invocations),
        backgroundColor: agents.map((_, i) => AGENT_PALETTE[i % AGENT_PALETTE.length]),
        borderRadius: 4,
        maxBarThickness: 26,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: {
          grid: { display: false },
          ticks: { font: { family: C.mono, size: 9 }, maxRotation: 50, minRotation: 30, autoSkip: false },
        },
        y: {
          beginAtZero: true,
          grid: { color: 'rgba(0,0,0,.035)' },
          ticks: { precision: 0, font: { family: C.mono, size: 10 } },
        },
      },
    },
  });
}
