// ── Invest Game App — Agent Performance ──────────────────────────────────────
// Full port of rita/agent-performance.js (Feature 32) — same markup IDs, same
// visual language: per-agent scorecards, KPI cards, invocation chart, detail
// table, and the Performance Over Period timeline.
//
// DEMO DATA: realized RL-agent scoring (Outcome Match, Avg RL Reward, Data
// Coverage) is produced by Phases 3–5, which are not yet built. Until then we
// render illustrative MOCK_AGENTS so the page conveys the intended view. The
// live endpoint is still queried and, where it already has rows, its real
// invocation count / outcome-match rate override the mock values per agent —
// so the page upgrades itself to live data as instrumentation accrues.
import { api } from '../shared/api.js';
import { setEl } from '../shared/utils.js';
import { mkChart, C } from '../shared/charts.js';

// One stable colour per agent slot (same hue in chart + scorecards).
const AGENT_PALETTE = [C.run, C.build, C.mon, C.warn, '#0E7490', '#BE185D', C.danger];

// The 4 measurable / improvable parameters per RL agent:
//   outcome_match  — % of recommendations whose realized outcome matched the call (accuracy)
//   avg_reward     — mean RL reward signal per decision (the training target); a per-step
//                    quantity, NOT 0–1 bounded. Mock baselines are illustrative only —
//                    aggregate KPIs average live (trained-RL) agents only so the headline
//                    reward is never a blend of real per-decision reward and mock values.
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

// avg_reward is a per-decision reward (a daily portfolio return), NOT 0–1 bounded.
// Real RL values are small (~0.007); show extra precision for those so they stay
// legible, while illustrative 0–1 mock baselines render cleanly at 2 decimals.
const fmtReward = v =>
  v == null ? '—' : (Math.abs(v) < 0.1 ? v.toFixed(4) : v.toFixed(2));

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
    if (!live) return m;
    // A trained V2 policy (Phase 3) surfaces real RL metrics; otherwise we only
    // upgrade from chat-instrumentation once an agent has real invocations.
    const isRL = live.gap_status === 'live-rl' || live.avg_reward != null;
    if (!isRL && (live.invocation_count_30d ?? 0) === 0) return m;
    return {
      ...m,
      invocations:   live.invocation_count_30d ?? m.invocations,
      outcome_match: live.outcome_match_rate != null ? live.outcome_match_rate : m.outcome_match,
      trend:         live.trend_vs_prior_30d != null ? live.trend_vs_prior_30d : m.trend,
      avg_reward:    live.avg_reward != null ? live.avg_reward : m.avg_reward,
      data_coverage: live.data_coverage != null ? live.data_coverage : m.data_coverage,
      live:          isRL,
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

  // ── Header mode badge — reflect how many agents have a trained RL policy ──
  const liveCount = agents.filter(a => a.live).length;
  const modeEl = document.getElementById('agent-perf-mode');
  if (modeEl) {
    if (liveCount === 0) {
      modeEl.className = 'badge warn';
      modeEl.textContent = 'Demo data';
    } else if (liveCount === agents.length) {
      modeEl.className = 'badge ok';
      modeEl.textContent = 'Live RL data';
    } else {
      modeEl.className = 'badge run';
      modeEl.textContent = `${liveCount}/${agents.length} live · rest demo`;
    }
  }

  // ── Aggregate KPIs ──
  // Average over LIVE (trained-RL) agents only so the headline reward / outcome /
  // coverage reflect real instrumentation, never a blend with illustrative mock
  // values. Invocations still sum across all agents (raw activity count). Before
  // any agent is live we fall back to the full mock set so the page isn't blank.
  const liveAgents = agents.filter(a => a.live);
  const aggBase = liveAgents.length ? liveAgents : agents;
  const avg = sel => {
    const vals = aggBase.map(sel).filter(v => v != null);
    return vals.length ? vals.reduce((s, v) => s + v, 0) / vals.length : null;
  };
  setEl('agent-perf-total', String(agents.reduce((s, a) => s + (a.invocations || 0), 0)));
  setEl('agent-perf-match', pct(avg(a => a.outcome_match)));
  setEl('agent-perf-reward', fmtReward(avg(a => a.avg_reward)));
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
      <td style="text-align:right;font-family:var(--fm)">${fmtReward(a.avg_reward)}</td>
      <td style="text-align:right;font-family:var(--fm)">${pct(a.data_coverage)}</td>
      <td style="text-align:right;font-family:var(--fm)">${a.invocations}</td>
      <td style="text-align:right">${fmtTrend(a.trend)}</td>
    </tr>`).join('');
  setEl('agent-perf-table', rows ||
    '<tr><td colspan="6" class="empty">No agent activity recorded yet.</td></tr>');

  setEl('agent-perf-updated', new Date().toLocaleString());

  // Load the performance-over-period timeline with the current selector values.
  loadAgentPerfTimeline();
}

// ── Performance over a custom period (timeline) ─────────────────────────────
// Reuses the Scenarios-page date-selector pattern; plots team invocations (bars)
// and outcome-match rate (line) over the chosen range.

export function setAgentPerfPeriod(from, to) {
  const f = document.getElementById('inp-ap-from');
  const t = document.getElementById('inp-ap-to');
  if (f) f.value = from;
  if (t) t.value = to;
  loadAgentPerfTimeline();
}

export async function loadAgentPerfTimeline() {
  const from = document.getElementById('inp-ap-from')?.value;
  const to = document.getElementById('inp-ap-to')?.value;
  const emptyEl = document.getElementById('agent-perf-timeline-empty');
  if (!from || !to) return;

  let data;
  try {
    data = await api(`/api/v1/experience/rita/agent-performance-timeline`
      + `?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`);
  } catch (e) {
    setEl('agent-perf-timeline-summary', 'Timeline unavailable.');
    return;
  }

  const buckets = (data && data.buckets) || [];
  const hasActivity = buckets.some(b => b.invocations > 0);
  if (emptyEl) emptyEl.style.display = hasActivity ? 'none' : 'block';

  const t = data.totals || {};
  const rate = t.match_rate == null ? '—' : `${Math.round(t.match_rate * 100)}%`;
  const sortinoStr = t.sortino == null ? '—' : t.sortino.toFixed(2);
  setEl('agent-perf-timeline-summary',
    `${t.invocations || 0} invocations · ${t.evaluated || 0} scored · match ${rate} · `
    + `Sortino ${sortinoStr} · ${data.bucket_days || 7}-day buckets`);

  mkChart('agent-perf-timeline-chart', {
    type: 'bar',
    data: {
      labels: buckets.map(b => b.bucket),
      datasets: [
        {
          label: 'Invocations', type: 'bar', yAxisID: 'y',
          data: buckets.map(b => b.invocations),
          backgroundColor: C.run, borderRadius: 3, maxBarThickness: 22,
        },
        {
          label: 'Outcome Match %', type: 'line', yAxisID: 'y1',
          data: buckets.map(b => (b.match_rate == null ? null : Math.round(b.match_rate * 100))),
          borderColor: C.build, backgroundColor: C.build,
          tension: 0.3, spanGaps: true, pointRadius: 3, borderWidth: 2,
        },
        {
          label: 'Sortino (risk-adj, cumulative)', type: 'line', yAxisID: 'y2',
          data: buckets.map(b => (b.sortino == null ? null : Number(b.sortino.toFixed(3)))),
          borderColor: C.warn, backgroundColor: C.warn,
          borderDash: [5, 4], tension: 0.3, spanGaps: true, pointRadius: 2, borderWidth: 2,
        },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: true, position: 'top', labels: { boxWidth: 12, font: { size: 10 } } } },
      scales: {
        x: { grid: { display: false }, ticks: { font: { family: C.mono, size: 9 }, maxRotation: 50, minRotation: 30, autoSkip: true, maxTicksLimit: 16 } },
        y: { beginAtZero: true, position: 'left', title: { display: true, text: 'Invocations' }, ticks: { precision: 0, font: { family: C.mono, size: 10 } }, grid: { color: 'rgba(0,0,0,.035)' } },
        y1: { beginAtZero: true, max: 100, position: 'right', title: { display: true, text: 'Match %' }, grid: { drawOnChartArea: false }, ticks: { font: { family: C.mono, size: 10 } } },
        y2: { position: 'right', title: { display: true, text: 'Sortino' }, grid: { drawOnChartArea: false }, ticks: { font: { family: C.mono, size: 10 } } },
      },
    },
  });
}

function _renderScorecards(agents) {
  const cards = agents.map((a, i) => {
    const barW = Math.round((a.outcome_match ?? 0) * 100);
    const covW = Math.round((a.data_coverage ?? 0) * 100);
    return `<div class="agp-sc">
      <div class="agp-sc-role">
        <span>${a.agent_name}${a.live ? ' <span class="badge ok" style="font-size:8px;vertical-align:middle">LIVE RL</span>' : ''}</span>
        <span style="width:8px;height:8px;border-radius:50%;background:${AGENT_PALETTE[i % AGENT_PALETTE.length]};flex-shrink:0"></span>
      </div>
      <div class="agp-sc-row">
        <span class="agp-sc-lbl">Outcome Match</span>
        <span class="agp-sc-val"><span class="agp-bar-wrap"><span class="agp-bar" style="width:${barW}%"></span></span>&nbsp;${pct(a.outcome_match)}</span>
      </div>
      <div class="agp-sc-row">
        <span class="agp-sc-lbl">Avg RL Reward</span>
        <span class="agp-sc-val">${fmtReward(a.avg_reward)}</span>
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
