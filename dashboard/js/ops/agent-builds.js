// ── Agent Builds ──────────────────────────────────────────────────────────────
import { apiFetch } from './api.js';

const ROLES = ['pm', 'architect', 'engineer', 'qa', 'techwriter'];
const ROLE_LABEL = { pm: 'PM', architect: 'Architect', engineer: 'Engineer', qa: 'QA', techwriter: 'TechWriter' };
const PALETTE = ['#6B2FA0', '#0056B8', '#1A6B3C', '#92480A', '#BE185D'];

// Chart instances — destroy before recreating to avoid Canvas reuse errors
let _chartGrounding = null;
let _chartTokens    = null;

// New chart instances for performance metrics panels
window._chartForecast = null;
window._chartTrends   = null;

/* ── Helpers ──────────────────────────────────────────────────────────────── */

function esc(s) {
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function pct(v) { return v != null ? Math.round(v * 100) + '%' : '—'; }

function fmtRunId(id) {
  if (!id || id === 'sample') return id;
  const m = id.match(/^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})$/);
  return m ? `${m[2]}/${m[3]} ${m[4]}:${m[5]}` : id;
}

function fmtDate(v) {
  if (v == null || v === '') return '—';
  const n = Number(v);
  if (!isNaN(n)) {
    const ms = n > 1e12 ? n : n * 1000;
    return new Date(ms).toISOString().slice(0, 10);
  }
  return String(v);
}

function roleColour(i, alpha = 1) {
  const hex = PALETTE[i % PALETTE.length];
  if (alpha === 1) return hex;
  const r = parseInt(hex.slice(1,3),16), g = parseInt(hex.slice(3,5),16), b = parseInt(hex.slice(5,7),16);
  return `rgba(${r},${g},${b},${alpha})`;
}

function statusBadge(s) {
  if (s === 'pass')               return '<span class="badge ok">Pass</span>';
  if (s === 'pass_with_warnings') return '<span class="badge warn">Warnings</span>';
  return '<span class="badge danger">Fail</span>';
}

function panel(id, title, html) {
  return `<div class="ab-panel" id="ab-panel-${id}">
    <div class="c-ey"><div class="ey-d" style="background:var(--accelerate)"></div>${title}</div>
    ${html}
  </div>`;
}

function chartOpts({ yMax, yLabel = '', suffix = '' }) {
  const cs = getComputedStyle(document.documentElement);
  const gridCol   = cs.getPropertyValue('--border').trim()  || '#E4E0D8';
  const tickCol   = cs.getPropertyValue('--t3').trim()      || '#8C877A';
  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { labels: { color: tickCol, font: { size: 11 }, boxWidth: 10 } },
      tooltip: { callbacks: { label: ctx => ` ${ctx.dataset.label}: ${ctx.parsed.y}${suffix}` } }
    },
    scales: {
      x: { ticks: { color: tickCol, font: { size: 10 } }, grid: { color: gridCol } },
      y: {
        ticks: { color: tickCol, font: { size: 10 }, callback: v => v + suffix },
        grid:  { color: gridCol },
        ...(yMax != null ? { max: yMax } : {}),
        title: { display: !!yLabel, text: yLabel, color: tickCol, font: { size: 10 } }
      }
    }
  };
}

/* ── Panel 1: Run History ─────────────────────────────────────────────────── */

function renderRunHistory(runs) {
  if (!runs.length) {
    return panel('runs', 'Pipeline Run History', '<div class="empty">No run data found</div>');
  }
  const rows = runs.map(r => {
    const est = r.total_tokens_estimated ?? 0;
    const actualSum = (r.agents ?? []).reduce((acc, a) => acc + (a.actual_tokens?.total_tokens ?? 0), 0);
    const hasActual = (r.agents ?? []).some(a => a.actual_tokens?.total_tokens != null);
    let estActualCol = `${est.toLocaleString()} / —`;
    if (hasActual) {
      let tokenColor = 'var(--ok)';
      if (actualSum > est * 1.25) tokenColor = 'var(--danger)';
      else if (actualSum > est) tokenColor = 'var(--warn)';
      estActualCol = `${est.toLocaleString()} / <span style="color:${tokenColor};font-family:var(--fm)">${actualSum.toLocaleString()}</span>`;
    }
    return `<tr>
      <td style="max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--t3)" title="${esc(r.request)}">${esc(r.request ?? '—')}</td>
      <td>${statusBadge(r.overall_status)}</td>
      <td style="font-family:var(--fm)">${r.duration_minutes ?? '—'} min</td>
      <td style="font-family:var(--fm);color:var(--t3);font-size:10px">${esc(r.branch ?? '—')}</td>
      <td style="font-family:var(--fm);font-size:11px">${estActualCol}</td>
      <td style="font-family:var(--fm);white-space:nowrap;color:var(--t3);font-size:10px">${fmtRunId(r.run_id)}</td>
    </tr>`;
  }).join('');
  const tbl = `<div class="tbl-wrap"><table>
    <thead><tr>
      <th>Request</th><th>Status</th><th>Duration</th><th>Branch</th><th>Est / Actual</th><th>Run</th>
    </tr></thead>
    <tbody>${rows}</tbody>
  </table></div>`;
  return panel('runs', 'Pipeline Run History', tbl);
}

/* ── Panel 2: Agent Scorecards ───────────────────────────────────────────── */

function renderScorecards(m) {
  const pr = m.per_role || {};
  if (!Object.keys(pr).length) {
    return panel('scorecards', 'Agent Scorecards', '<div class="empty">No metrics data</div>');
  }
  const cards = ROLES.map(role => {
    const d = pr[role];
    if (!d) return '';
    const barW = Math.round((d.avg_adherence_score ?? 0) * 100);
    const fprOk = (d.first_pass_rate ?? 0) >= 1;
    return `<div class="ab-sc">
      <div class="ab-sc-role">${ROLE_LABEL[role]}</div>
      <div class="ab-sc-row">
        <span class="ab-sc-lbl">Adherence</span>
        <span class="ab-sc-val">
          <span class="ab-bar-wrap"><span class="ab-bar" style="width:${barW}%"></span></span>
          &nbsp;${pct(d.avg_adherence_score)}
        </span>
      </div>
      <div class="ab-sc-row">
        <span class="ab-sc-lbl">1st pass</span>
        <span class="ab-sc-val" style="color:var(${fprOk ? '--ok' : '--warn'})">${pct(d.first_pass_rate)}</span>
      </div>
      <div class="ab-sc-row">
        <span class="ab-sc-lbl">Avg tokens</span>
        <span class="ab-sc-val">${d.avg_token_cost?.toLocaleString() ?? '—'}</span>
      </div>
      <div class="ab-sc-row">
        <span class="ab-sc-lbl">Runs</span>
        <span class="ab-sc-val">${d.run_count ?? '—'}</span>
      </div>
    </div>`;
  }).join('');
  return panel('scorecards', 'Agent Scorecards', `<div class="ab-sc-grid">${cards}</div>`);
}

/* ── Panel 3: Grounding Score Trend ─────────────────────────────────────── */

function renderGroundingPanel(m) {
  return panel('grounding', 'Grounding Score Trend',
    `<div class="ab-chart-wrap"><canvas id="ab-chart-grounding"></canvas></div>`);
}

function mountGroundingChart(m) {
  const trend  = m.grounding_trend ?? [];
  const labels = trend.map(r => fmtRunId(r.run_id));
  const data   = trend.map(r => +(r.grounding_score * 100).toFixed(1));
  if (_chartGrounding) { _chartGrounding.destroy(); _chartGrounding = null; }
  const ctx = document.getElementById('ab-chart-grounding');
  if (!ctx) return;
  _chartGrounding = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [{
        label: '% Grounding Checks Passed',
        data,
        borderColor: '#6B2FA0',
        backgroundColor: 'rgba(107,47,160,0.10)',
        pointBackgroundColor: '#6B2FA0',
        fill: true,
        tension: 0.35,
      }]
    },
    options: chartOpts({ yMax: 100, yLabel: '%', suffix: '%' })
  });
  bindChartExpand('ab-chart-grounding', 'Grounding Score Trend');
}

/* ── Panel 4: Failure Heatmap ────────────────────────────────────────────── */

function renderFailureHeatmap(m) {
  const fm = m.failure_modes || {};
  const fcodes = Object.keys(fm);
  if (!fcodes.length) {
    return panel('failures', 'Failure Mode Heatmap', '<div class="empty">No failure modes recorded</div>');
  }
  const bd  = 'border-bottom:1px solid var(--border);';
  const hdr = `font-family:var(--fm);font-size:9px;text-transform:uppercase;letter-spacing:.1em;color:var(--t4);padding:5px 8px;text-align:center;border-bottom:1.5px solid var(--border);`;
  const cod = `font-family:var(--fm);font-size:10px;color:var(--accelerate);padding:5px 8px;${bd}display:flex;align-items:center;white-space:nowrap;`;
  const cel = `font-size:11px;font-family:var(--fm);padding:5px 8px;${bd}display:flex;align-items:center;justify-content:center;`;

  const headers = `<div style="${hdr};text-align:left">FC Code</div>` +
    ROLES.map(r => `<div style="${hdr}">${ROLE_LABEL[r]}</div>`).join('');

  const rows = fcodes.map(code => {
    const entry = fm[code];
    const cells = ROLES.map(role => {
      const count = entry.by_role?.[role] ?? 0;
      const cls = count === 0 ? 'heat-0' : count === 1 ? 'heat-1' : count <= 2 ? 'heat-2' : 'heat-3';
      return `<div class="${cls}" style="${cel}">${count || '—'}</div>`;
    }).join('');
    return `<div style="${cod}">${esc(code)}</div>${cells}`;
  }).join('');

  return panel('failures', 'Failure Mode Heatmap',
    `<div class="ab-hm-grid">${headers}${rows}</div>`
  );
}

/* ── Panel 5: Token Cost Trend ───────────────────────────────────────────── */

function renderTokenPanel(runs) {
  return panel('tokens', 'Token Cost Trend',
    `<div class="ab-chart-wrap"><canvas id="ab-chart-tokens"></canvas></div>`);
}

function mountTokenChart(runs) {
  const labels   = runs.map(r => fmtRunId(r.run_id));
  // Estimate datasets (solid lines, one per role)
  const estimateDatasets = ROLES.map((role, i) => ({
    label: ROLE_LABEL[role],
    data: runs.map(r => (r.agents ?? []).find(a => a.role === role)?.token_estimate ?? 0),
    borderColor: roleColour(i),
    backgroundColor: roleColour(i, 0.08),
    fill: false,
    tension: 0.3,
    pointRadius: 4,
  }));
  // Actual datasets (dashed lines, one per role)
  const actualDatasets = ROLES.map((role, i) => ({
    label: `${ROLE_LABEL[role]} (actual)`,
    data: runs.map(r => (r.agents ?? []).find(a => a.role === role)?.actual_tokens?.total_tokens ?? null),
    borderColor: roleColour(i, 0.55),
    backgroundColor: roleColour(i, 0.04),
    borderDash: [4, 4],
    fill: false,
    tension: 0.3,
    pointRadius: 3,
    spanGaps: false,
  }));
  const datasets = [...estimateDatasets, ...actualDatasets];
  if (_chartTokens) { _chartTokens.destroy(); _chartTokens = null; }
  const ctx = document.getElementById('ab-chart-tokens');
  if (!ctx) return;
  _chartTokens = new Chart(ctx, {
    type: 'line',
    data: { labels, datasets },
    options: chartOpts({ yLabel: 'Tokens' })
  });
  bindChartExpand('ab-chart-tokens', 'Token Cost Trend');
}

/* ── Panel 6: Skill Version History ─────────────────────────────────────── */

function renderSkillVersions(m) {
  const hist = m.skill_version_history ?? [];
  if (!hist.length) {
    return panel('skills', 'Skill File Versions', '<div class="empty">No skill history</div>');
  }
  const rows = hist.map(s => {
    const commits = (s.recent_commits ?? []).slice(0, 2)
      .map(c => `<code style="font-size:10px;font-family:var(--fm);color:var(--t3)">${esc(c.hash)} — ${esc(c.message)}</code>`)
      .join('<br>');
    const improvement = esc(s.improvement_applied ?? '—');
    let rateDelta = '—';
    if (s.before_first_pass_rate != null && s.after_first_pass_rate != null) {
      rateDelta = `${Math.round(s.before_first_pass_rate * 100)}% → ${Math.round(s.after_first_pass_rate * 100)}%`;
    }
    return `<tr>
      <td style="font-family:var(--fm);font-size:10px;color:var(--accelerate)">${esc(s.skill_file)}</td>
      <td style="font-family:var(--fm);font-size:11px">${fmtDate(s.last_updated)}</td>
      <td style="font-size:11px">${improvement}</td>
      <td style="font-family:var(--fm);font-size:11px">${rateDelta}</td>
      <td>${commits || '<span style="color:var(--t4)">—</span>'}</td>
    </tr>`;
  }).join('');
  const tbl = `<div class="tbl-wrap"><table>
    <thead><tr><th>Skill File</th><th>Last Updated</th><th>Improvement</th><th>Rate Δ</th><th>Recent Commits</th></tr></thead>
    <tbody>${rows}</tbody>
  </table></div>`;
  return panel('skills', 'Skill File Versions', tbl);
}

/* ── Panel A: KPI Cards ──────────────────────────────────────────────────── */

function renderKpiCards(metrics, runs) {
  try {
    const tc  = metrics?.task_completion;
    const q   = metrics?.quality;
    const tf  = metrics?.token_forecasting;
    const h   = metrics?.hitl;

    const tsrEl = document.getElementById('ab-kpi-tsr');
    const csatEl = document.getElementById('ab-kpi-csat');
    const forecastEl = document.getElementById('ab-kpi-forecast-err');
    const hitlEl = document.getElementById('ab-kpi-hitl');
    const cacheHitEl = document.getElementById('ab-kpi-cache-hit');

    if (tsrEl) tsrEl.innerHTML = tc?.tsr != null
      ? `<span class="ab-kpi-val">${(tc.tsr * 100).toFixed(1)}%</span><span class="ab-kpi-lbl">Task Success Rate</span>`
      : `<span class="ab-kpi-val">—</span><span class="ab-kpi-lbl">Task Success Rate</span>`;

    if (csatEl) csatEl.innerHTML = q?.avg_csat != null
      ? `<span class="ab-kpi-val">${q.avg_csat.toFixed(1)} / 5</span><span class="ab-kpi-lbl">Avg CSAT</span>`
      : `<span class="ab-kpi-val">—</span><span class="ab-kpi-lbl">Avg CSAT</span>`;

    if (forecastEl) forecastEl.innerHTML = tf?.avg_forecast_error_pct != null
      ? `<span class="ab-kpi-val">±${tf.avg_forecast_error_pct.toFixed(0)}%</span><span class="ab-kpi-lbl">Avg Forecast Error</span>`
      : `<span class="ab-kpi-val">—</span><span class="ab-kpi-lbl">Avg Forecast Error</span>`;

    if (hitlEl) hitlEl.innerHTML = h != null
      ? `<span class="ab-kpi-val">${((h.escalation_rate || 0) * 100).toFixed(0)}%</span><span class="ab-kpi-lbl">HITL Escalation Rate</span>`
      : `<span class="ab-kpi-val">—</span><span class="ab-kpi-lbl">HITL Escalation Rate</span>`;

    // Cache hit rate: avg(cache_read_input_tokens / input_tokens) across all agents with actual_tokens
    if (cacheHitEl) {
      const cacheRates = [];
      for (const r of (runs ?? [])) {
        for (const a of (r.agents ?? [])) {
          const at = a.actual_tokens;
          if (at && at.input_tokens > 0) {
            cacheRates.push((at.cache_read_input_tokens ?? 0) / at.input_tokens);
          }
        }
      }
      const cacheHitDisplay = cacheRates.length > 0
        ? `${Math.round(cacheRates.reduce((s, v) => s + v, 0) / cacheRates.length * 100)}%`
        : '—';
      cacheHitEl.innerHTML = `<span class="ab-kpi-val">${cacheHitDisplay}</span><span class="ab-kpi-lbl">Cache Hit Rate</span>`;
    }
  } catch (e) {
    // silently ignore — KPI cards show — by default
  }
}

/* ── Panel B: Forecast vs Actual Chart ───────────────────────────────────── */

function renderForecastPanel(runs) {
  try {
    const el = document.getElementById('ab-panel-forecast');
    if (!el) return;
    mountForecastChart(runs);
  } catch (e) {
    // silently ignore
  }
}

function mountForecastChart(runs) {
  try {
    const slice  = (runs ?? []).slice(-10);
    const labels = slice.map(r => fmtRunId(r.run_id));
    const forecasts = slice.map(r => (r.token_forecast?.total_forecast ?? 0) / 1000);
    const actuals   = slice.map(r => {
      const sum = (r.agents ?? []).reduce((acc, a) => acc + (a.actual_tokens?.total_tokens ?? 0), 0);
      return sum > 0 ? sum / 1000 : null;
    });

    if (window._chartForecast) { window._chartForecast.destroy(); window._chartForecast = null; }

    const ctx = document.getElementById('ab-chart-forecast');
    if (!ctx) return;

    const cs = getComputedStyle(document.documentElement);
    const gridCol = cs.getPropertyValue('--border').trim() || '#E4E0D8';
    const tickCol = cs.getPropertyValue('--t3').trim()     || '#8C877A';

    window._chartForecast = new Chart(ctx, {
      type: 'bar',
      data: {
        labels,
        datasets: [
          {
            label: 'Forecast',
            data: forecasts,
            backgroundColor: '#8C877A',
            borderColor: '#8C877A',
            borderWidth: 1,
          },
          {
            label: 'Actual',
            data: actuals,
            backgroundColor: '#0056B8',
            borderColor: '#0056B8',
            borderWidth: 1,
          },
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { labels: { color: tickCol, font: { size: 11 }, boxWidth: 10 } },
          tooltip: {
            callbacks: {
              label: ctx => ` ${ctx.dataset.label}: ${ctx.parsed.y.toFixed(1)}k`,
              afterBody: (items) => {
                const idx = items[0]?.dataIndex;
                if (idx == null) return [];
                const r = slice[idx];
                if (!r?.agents?.length) return [];
                return (r.agents || []).map(a =>
                  `  ${a.role ?? '?'}: ${(a.token_estimate ?? 0).toLocaleString()}`
                );
              }
            }
          }
        },
        scales: {
          x: { ticks: { color: tickCol, font: { size: 10 } }, grid: { color: gridCol } },
          y: {
            ticks: { color: tickCol, font: { size: 10 }, callback: v => v + 'k' },
            grid:  { color: gridCol },
            title: { display: true, text: 'Tokens (k)', color: tickCol, font: { size: 10 } }
          }
        }
      }
    });
    bindChartExpand('ab-chart-forecast', 'Token Forecast vs Actual');
  } catch (e) {
    // silently ignore
  }
}

/* ── Panel C: Metric Trend Lines ─────────────────────────────────────────── */

function renderTrendPanel(m, runs) {
  try {
    const el = document.getElementById('ab-panel-trends');
    if (!el) return;
    mountTrendChart(m, runs);
  } catch (e) {
    // silently ignore
  }
}

function mountTrendChart(m, runs) {
  try {
    const trend = m?.grounding_trend ?? [];
    const labels = trend.map(r => fmtRunId(r.run_id));

    // Build a lookup from run_id -> run object for fast access
    const runsById = {};
    for (const r of (runs ?? [])) {
      runsById[r.run_id] = r;
    }

    // TSR per run: find matching run by run_id, 1 if pass else 0, null if not found
    const tsrData = trend.map(t => {
      const r = runsById[t.run_id];
      if (!r) return null;
      return r.overall_status === 'pass' ? 1 : 0;
    });

    // Grounding score (already 0-1, from grounding_trend)
    const groundingData = trend.map(r => r.grounding_score ?? null);

    // CSAT: from matching run's human_score_csat (normalised 0-1), null if missing
    const csatData = trend.map(t => {
      const r = runsById[t.run_id];
      return (r?.human_score_csat != null) ? r.human_score_csat / 5 : null;
    });

    // Context adherence: pm.grounding_checks.plan_status_read AND
    // architect.grounding_checks.spec_reference_valid → 1; else 0; null if agents missing
    const adherenceData = trend.map(t => {
      const r = runsById[t.run_id];
      if (!r?.agents?.length) return null;
      const pm = r.agents.find(a => a.role === 'pm');
      const arch = r.agents.find(a => a.role === 'architect');
      if (!pm && !arch) return null;
      const planOk = pm?.grounding_checks?.plan_status_read === true;
      const specOk = arch?.grounding_checks?.spec_reference_valid === true;
      return (planOk && specOk) ? 1 : 0;
    });

    if (window._chartTrends) { window._chartTrends.destroy(); window._chartTrends = null; }

    const ctx = document.getElementById('ab-chart-trends');
    if (!ctx) return;

    const cs = getComputedStyle(document.documentElement);
    const gridCol = cs.getPropertyValue('--border').trim() || '#E4E0D8';
    const tickCol = cs.getPropertyValue('--t3').trim()     || '#8C877A';

    window._chartTrends = new Chart(ctx, {
      type: 'line',
      data: {
        labels,
        datasets: [
          {
            label: 'TSR',
            data: tsrData,
            borderColor: '#0056B8',
            backgroundColor: 'rgba(0,86,184,0.07)',
            pointBackgroundColor: '#0056B8',
            fill: false,
            tension: 0.3,
            spanGaps: false,
          },
          {
            label: 'Grounding',
            data: groundingData,
            borderColor: '#6B2FA0',
            backgroundColor: 'rgba(107,47,160,0.07)',
            pointBackgroundColor: '#6B2FA0',
            fill: false,
            tension: 0.3,
            spanGaps: false,
          },
          {
            label: 'CSAT',
            data: csatData,
            borderColor: '#1A6B3C',
            backgroundColor: 'rgba(26,107,60,0.07)',
            pointBackgroundColor: '#1A6B3C',
            fill: false,
            tension: 0.3,
            spanGaps: false,
          },
          {
            label: 'Context Adherence',
            data: adherenceData,
            borderColor: '#92480A',
            backgroundColor: 'rgba(146,72,10,0.07)',
            pointBackgroundColor: '#92480A',
            fill: false,
            tension: 0.3,
            spanGaps: false,
          },
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { labels: { color: tickCol, font: { size: 11 }, boxWidth: 10 } },
          tooltip: { callbacks: { label: ctx => ` ${ctx.dataset.label}: ${ctx.parsed.y?.toFixed(2) ?? '—'}` } }
        },
        scales: {
          x: { ticks: { color: tickCol, font: { size: 10 } }, grid: { color: gridCol } },
          y: {
            min: 0,
            max: 1,
            ticks: { color: tickCol, font: { size: 10 }, stepSize: 0.25 },
            grid:  { color: gridCol },
            title: { display: true, text: 'Score (0–1)', color: tickCol, font: { size: 10 } }
          }
        }
      }
    });
    bindChartExpand('ab-chart-trends', 'Metric Trend Lines');
  } catch (e) {
    // silently ignore
  }
}

/* ── Chart expand modal ──────────────────────────────────────────────────── */

function openChartModal(canvasId, title) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  document.getElementById('ab-chart-modal-title').textContent = title || '';
  document.getElementById('ab-chart-modal-img').src = canvas.toDataURL('image/png');
  document.getElementById('ab-chart-modal').style.display = 'flex';
}

export function closeChartModal() {
  const m = document.getElementById('ab-chart-modal');
  if (m) m.style.display = 'none';
}

function bindChartExpand(canvasId, title) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const wrap = canvas.closest('.ab-chart-wrap');
  if (!wrap || wrap.dataset.expandBound) return;
  wrap.dataset.expandBound = '1';
  wrap.style.cursor = 'zoom-in';
  wrap.title = 'Click to expand';
  wrap.addEventListener('click', () => openChartModal(canvasId, title));
}

/* ── Token Estimate Widget ───────────────────────────────────────────────── */

export function renderTokenEstimateWidget() {
  try {
    const form = document.getElementById('ab-estimate-form');
    if (!form) return;

    const sel = 'width:100%;font-size:11px;padding:4px 6px;background:var(--bg2);color:var(--t1);border:1px solid var(--border);border-radius:4px;box-sizing:border-box';
    const lbl = 'display:block;font-size:10px;color:var(--t3);margin-bottom:3px;font-weight:500';
    const cell = 'background:var(--bg2);border:1px solid var(--border);border-radius:4px;padding:8px 10px;min-height:52px;display:flex;flex-direction:column;justify-content:center';
    form.innerHTML = `
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px">
        <div style="${cell}">
          <label style="${lbl}">Feature type</label>
          <select id="ab-estimate-feature-type" style="${sel}">
            <option value="rita">RITA</option>
            <option value="ops">Ops</option>
            <option value="fno">FnO</option>
            <option value="invest-game">Invest Game</option>
          </select>
        </div>
        <div style="${cell}">
          <label style="${lbl}">Files to change</label>
          <select id="ab-estimate-files" style="${sel}">
            <option value="small">Small (1–3 files)</option>
            <option value="medium">Medium (4–8 files)</option>
            <option value="large">Large (9+ files)</option>
          </select>
        </div>
        <div style="${cell}">
          <label style="${lbl}">Endpoint / model</label>
          <select id="ab-estimate-endpoint" style="${sel}">
            <option value="none">None</option>
            <option value="one">One</option>
            <option value="both">Both</option>
          </select>
        </div>
        <div style="${cell}">
          <label style="${lbl}">Frontend scope</label>
          <select id="ab-estimate-frontend" style="${sel}">
            <option value="none">None</option>
            <option value="panel">Panel</option>
            <option value="page">Page</option>
          </select>
        </div>
        <div style="${cell}">
          <label style="${lbl}">Integration</label>
          <select id="ab-estimate-integration" style="${sel}">
            <option value="additive">Additive</option>
            <option value="extends">Extends existing</option>
            <option value="cross-cutting">Cross-cutting</option>
          </select>
        </div>
        <div style="${cell};justify-content:flex-end">
          <button id="ab-estimate-btn" onclick="submitTokenEstimate()"
            style="width:100%;padding:6px 0;font-size:11px;background:var(--accelerate);color:#fff;border:none;border-radius:4px;cursor:pointer;font-weight:600;margin-top:auto">
            Estimate
          </button>
        </div>
        <div id="ab-res-complexity" style="${cell};border-color:var(--accelerate)"></div>
        <div id="ab-res-total"      style="${cell};border-color:var(--accelerate)"></div>
        <div id="ab-res-confidence" style="${cell};border-color:var(--accelerate)"></div>
      </div>
    `;
  } catch (e) {
    // silently ignore
  }
}

export function toggleEstimateWidget() {
  try {
    const form = document.getElementById('ab-estimate-form');
    if (!form) return;
    form.style.display = form.style.display === 'none' ? 'block' : 'none';
  } catch (e) {
    // silently ignore
  }
}

export async function submitTokenEstimate() {
  try {
    const btn = document.getElementById('ab-estimate-btn');
    const result = document.getElementById('ab-estimate-result');

    const featureType   = document.getElementById('ab-estimate-feature-type')?.value ?? 'rita';
    const filesToChange = document.getElementById('ab-estimate-files')?.value ?? 'small';
    const endpoint      = document.getElementById('ab-estimate-endpoint')?.value ?? 'none';
    const frontend      = document.getElementById('ab-estimate-frontend')?.value ?? 'none';
    const integration   = document.getElementById('ab-estimate-integration')?.value ?? 'additive';

    if (btn) { btn.disabled = true; btn.textContent = 'Estimating…'; }
    if (result) result.innerHTML = '';

    const params = new URLSearchParams({
      feature_type:           featureType,
      files_to_change:        filesToChange,
      new_endpoint_or_model:  endpoint,
      frontend_scope:         frontend,
      integration_type:       integration,
    });

    const base = window.RITA_API_BASE || '';
    const resp = await apiFetch(`/api/experience/ops/token-forecast?${params}`);

    if (!result) return;

    const ROLE_LABELS = { pm: 'PM', architect: 'Architect', engineer: 'Engineer', qa: 'QA', techwriter: 'TechWriter' };
    const perRoleRows = Object.entries(resp.per_role || {})
      .map(([role, tokens]) =>
        `<tr><td style="padding:2px 10px 2px 0;color:var(--t3)">${ROLE_LABELS[role] ?? role}</td><td style="font-family:var(--fm)">${(tokens ?? 0).toLocaleString()}</td></tr>`
      ).join('');

    const noHistNote = resp.basis_runs === 0
      ? `<div style="margin-top:8px;font-size:11px;color:var(--warn)">(no historical data for this type — using global averages)</div>`
      : '';

    result.innerHTML = `
      <table style="width:100%;border-collapse:collapse;font-size:12px">
        ${perRoleRows}
        <tr style="border-top:1px solid var(--border)">
          <td style="padding:4px 10px 2px 0;font-weight:600">Total</td>
          <td style="font-family:var(--fm);font-weight:600">${(resp.total_forecast ?? 0).toLocaleString()}</td>
        </tr>
      </table>
      <div style="margin-top:6px;font-size:11px;color:var(--t3)">
        Complexity: <strong>${esc(resp.complexity ?? '—')}</strong> &nbsp;|&nbsp;
        Confidence: <strong>${esc(resp.confidence ?? '—')}</strong> &nbsp;|&nbsp;
        Basis runs: <strong>${resp.basis_runs ?? 0}</strong>
      </div>
      ${noHistNote}
    `;

    // Populate the three result KPI cards in the form grid
    const resComplexity = document.getElementById('ab-res-complexity');
    if (resComplexity) resComplexity.innerHTML = `<span class="ab-kpi-lbl">Complexity</span><span class="ab-kpi-val">${esc(resp.complexity ?? '—')}</span>`;
    const resTotal = document.getElementById('ab-res-total');
    if (resTotal) resTotal.innerHTML = `<span class="ab-kpi-lbl">Total tokens</span><span class="ab-kpi-val">${resp.total_forecast != null ? resp.total_forecast.toLocaleString() : '—'}</span>`;
    const resConfidence = document.getElementById('ab-res-confidence');
    if (resConfidence) resConfidence.innerHTML = `<span class="ab-kpi-lbl">Confidence</span><span class="ab-kpi-val">${esc(resp.confidence ?? '—')}</span>`;
  } catch (e) {
    const result = document.getElementById('ab-estimate-result');
    if (result) result.innerHTML = '<span style="color:var(--danger)">—</span>';
  } finally {
    const btn = document.getElementById('ab-estimate-btn');
    if (btn) { btn.disabled = false; btn.textContent = 'Estimate'; }
  }
}

/* ── Main loader ─────────────────────────────────────────────────────────── */

export async function loadAgentBuilds() {
  const grid = document.getElementById('ab-grid');
  if (!grid) return;
  grid.innerHTML = '<div class="loading">Loading…</div>';

  try {
    const data = await apiFetch('/api/experience/ops/agent-builds');
    const runs = data.runs;
    const m = data.metrics;

    if (!data) {
      grid.innerHTML = '<div class="empty">Could not load agent-ops metrics</div>';
      return;
    }

    // Render HTML panels (charts need canvas in DOM first)
    grid.innerHTML = [
      // Row 1: Agent Scorecards — full width
      renderScorecards(m),
      // Row 2: Pipeline Run History (50%) + Skill File Versions (50%)
      `<div class="ab-row ab-row-2">${renderRunHistory(runs)}${renderSkillVersions(m)}</div>`,
      // Row 3: Token Forecast + Grounding Score Trend + Metric Trend Lines
      `<div class="ab-row ab-row-3">
        ${panel('forecast', 'Token Forecast vs Actual', `<div class="ab-chart-wrap"><canvas id="ab-chart-forecast"></canvas></div>`)}
        ${renderGroundingPanel(m)}
        ${panel('trends', 'Metric Trend Lines', `<div class="ab-chart-wrap"><canvas id="ab-chart-trends"></canvas></div>`)}
      </div>`,
      // Row 4: Token Cost Trend + Failure Heatmap stacked on left (50%) | Estimate Token Budget on right (50%)
      `<div class="ab-row ab-row-2">
        <div style="display:flex;flex-direction:column;gap:16px">
          ${renderTokenPanel(runs)}
          ${renderFailureHeatmap(m)}
        </div>
        ${panel('estimate', 'Estimate Token Budget', `<div id="ab-estimate-form"></div><div id="ab-estimate-result" style="margin-top:8px"></div>`)}
      </div>`,
    ].join('');

    // Mount Chart.js after DOM is ready
    if (window.Chart) {
      mountGroundingChart(m);
      mountTokenChart(runs);
      renderForecastPanel(runs);
      renderTrendPanel(m, runs);
    }

    renderTokenEstimateWidget();
  } catch (e) {
    grid.innerHTML = '<div class="empty">Could not load agent-ops metrics</div>';
  }
}
