// ── Chat Analytics ────────────────────────────────────────────────────────────
import { apiFetch } from './api.js';

// Maps handler name → Python function signature for transparency display
export const HANDLER_FN = {
  'market_sentiment':        'get_market_sentiment(df)',
  'strategy_recommendation': 'get_strategy_recommendation(df)',
  'return_estimates':        'get_period_return_estimates(df, period)',
  'stress_scenarios':        'simulate_stress_scenarios(df, portfolio_inr)',
  'performance_feedback':    'get_performance_feedback(perf_summary)',
  'portfolio_comparison':    'build_portfolio_comparison(backtest_daily)',
};

export async function loadChat() {
  const data = await apiFetch('/api/v1/chat/monitor');
  if (!data) {
    ['chat-kpis','chat-intents','chat-recent','chat-commentary'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.innerHTML = '<div class="empty">No chat data yet — use the RITA Agent chat first</div>';
    });
    return;
  }

  const s = data.summary || {};

  // KPI strip
  const confColour = (s.avg_confidence || 0) >= 0.6 ? 'ok' : (s.avg_confidence || 0) >= 0.42 ? 'ops' : 'warn';
  document.getElementById('chat-kpis').innerHTML = `
    <div class="kpi"><div class="kpi-ey">Total Queries</div><div class="kpi-val ops">${s.total_queries ?? 0}</div><div class="kpi-sub">all time</div></div>
    <div class="kpi"><div class="kpi-ey">Avg Confidence</div><div class="kpi-val ${confColour}">${s.avg_confidence != null ? (s.avg_confidence*100).toFixed(0)+'%' : '—'}</div><div class="kpi-sub">cosine similarity</div></div>
    <div class="kpi"><div class="kpi-ey">Avg Latency</div><div class="kpi-val ops">${s.avg_latency_ms != null ? s.avg_latency_ms.toFixed(0)+'ms' : '—'}</div><div class="kpi-sub">classify + dispatch</div></div>
    <div class="kpi"><div class="kpi-ey">Unique Intents</div><div class="kpi-val ops">${(data.intents||[]).length}</div><div class="kpi-sub">used this session</div></div>
    <div class="kpi"><div class="kpi-ey">Queries Today</div><div class="kpi-val ops">${s.queries_today ?? 0}</div><div class="kpi-sub">UTC day</div></div>
  `;

  // Recent queries
  const recent = data.recent || [];
  document.getElementById('chat-recent').innerHTML = recent.length
    ? `<div class="tbl-wrap" style="max-height:222px">
        <table>
          <thead><tr><th>Query</th><th>Intent</th><th>Handler</th><th>Confidence</th><th>Latency</th><th>Time</th></tr></thead>
          <tbody>${recent.map(r => `<tr>
            <td style="max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${r.query_text ?? ''}">${r.query_text ?? '—'}</td>
            <td style="font-family:var(--fm);white-space:nowrap">${(r.intent_name ?? '—').replace(/_/g,' ')}</td>
            <td style="font-family:var(--fm);color:var(--t3);white-space:nowrap">${r.handler ?? '—'}</td>
            <td style="font-family:var(--fm);color:${parseFloat(r.confidence||0)>=0.6?'var(--ok)':parseFloat(r.confidence||0)>=0.42?'var(--info)':'var(--warn)'}">${r.confidence != null ? (parseFloat(r.confidence)*100).toFixed(0)+'%' : '—'}</td>
            <td style="font-family:var(--fm)">${r.latency_ms != null ? parseFloat(r.latency_ms).toFixed(0)+'ms' : '—'}</td>
            <td style="font-family:var(--fm);color:var(--t3);white-space:nowrap">${(r.timestamp||'').slice(0,16)}</td>
          </tr>`).join('')}</tbody>
        </table>
      </div>`
    : '<div class="empty">No queries logged yet</div>';

  // Commentary metrics
  const cCount   = s.commentary_count ?? 0;
  const cLatency = s.commentary_avg_latency_ms;
  const cErrors  = s.commentary_error_count ?? 0;
  const errColour = cErrors === 0 ? 'ok' : cErrors < 3 ? 'ops' : 'warn';
  document.getElementById('chat-commentary').innerHTML = `
    <div class="kpi-strip" style="margin-bottom:12px">
      <div class="kpi"><div class="kpi-ey">Generated</div><div class="kpi-val ops">${cCount}</div><div class="kpi-sub">total commentaries</div></div>
      <div class="kpi"><div class="kpi-ey">Avg Latency</div><div class="kpi-val ops">${cLatency != null ? cLatency.toFixed(0)+'ms' : '—'}</div><div class="kpi-sub">end-to-end</div></div>
      <div class="kpi"><div class="kpi-ey">Errors</div><div class="kpi-val ${errColour}">${cErrors}</div><div class="kpi-sub">status=error rows</div></div>
    </div>
    <div style="font-size:11px;color:var(--t3);line-height:1.7">
      <div><span style="color:var(--t2);font-weight:600">Endpoint:</span> POST /api/v1/commentary</div>
      <div><span style="color:var(--t2);font-weight:600">Pages:</span> Overview (auto-load) · Strategy (on button click)</div>
      <div><span style="color:var(--t2);font-weight:600">Engine:</span> Deterministic rule-based · <span style="font-style:italic">LLM swap point: _build_narrative()</span></div>
      <div><span style="color:var(--t2);font-weight:600">Instruments:</span> NVIDIA · ASML · NIFTY · BANKNIFTY</div>
    </div>`;

  // Intent distribution with Python function column
  const intents = data.intents || [];
  document.getElementById('chat-intents').innerHTML = intents.length
    ? `<table>
        <thead><tr><th>Intent</th><th>Count</th><th>Avg Confidence</th><th>Python Function Called</th></tr></thead>
        <tbody>${intents.map(r => {
          const fn = HANDLER_FN[r.handler] || (r.handler ? r.handler + '(...)' : '—');
          return `<tr>
            <td style="font-family:var(--fm)">${(r.intent_name ?? '—').replace(/_/g,' ')}</td>
            <td>${r.count ?? 0}</td>
            <td style="color:${(r.avg_confidence||0)>=0.6?'var(--ok)':(r.avg_confidence||0)>=0.42?'var(--info)':'var(--warn)'};font-family:var(--fm)">${r.avg_confidence != null ? (r.avg_confidence*100).toFixed(0)+'%' : '—'}</td>
            <td style="font-family:var(--fm);color:var(--t3);font-size:11px">${fn}</td>
          </tr>`;
        }).join('')}</tbody>
      </table>`
    : '<div class="empty">No intents logged yet</div>';
}
