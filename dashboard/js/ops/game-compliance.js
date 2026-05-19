// ── Game AI Compliance ─────────────────────────────────────────────────────────
import { apiFetch } from './api.js';

function esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function statusBadge(s) {
  if (s === 'pass')               return '<span class="badge ok">Pass</span>';
  if (s === 'pass_with_warnings') return '<span class="badge warn">Warnings</span>';
  return '<span class="badge danger">Fail</span>';
}

function compBadge(s) {
  return s === 'pass'
    ? '<span class="badge ok">Pass</span>'
    : '<span class="badge danger">Flagged</span>';
}

function fmtRunId(id) {
  if (!id) return id;
  const m = id.match(/^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})$/);
  return m ? `${m[1]}-${m[2]}-${m[3]} ${m[4]}:${m[5]}` : id;
}

function panel(id, title, html) {
  return `<div class="ab-panel" id="gc-panel-${id}">
    <div class="c-ey"><div class="ey-d" style="background:var(--ok)"></div>${title}</div>
    ${html}
  </div>`;
}

function kpi(label, value) {
  return `<div class="ab-sc" style="min-width:130px">
    <div class="ab-sc-role">${label}</div>
    <div style="font-size:20px;font-weight:700;color:var(--t1);margin-top:4px">${value}</div>
  </div>`;
}

export async function loadGameCompliance() {
  const grid = document.getElementById('gc-grid');
  if (!grid) return;
  grid.innerHTML = '<div class="loading">Loading…</div>';

  const m = await apiFetch('/agent-ops-data/metrics.json');
  if (!m || !m.game_sessions?.length) {
    grid.innerHTML = '<div class="empty">No game sessions found. Play a game first to populate compliance data.</div>';
    return;
  }

  // Fetch individual run JSONs for day_log detail
  const runResults = await Promise.all(
    m.game_sessions.map(s => apiFetch(`/agent-ops-data/runs/run-${s.run_id}.json`))
  );
  const runs = runResults.filter(Boolean);

  // KPI aggregates
  const total       = runs.length;
  const flaggedRuns = runs.filter(r => r.overall_status === 'pass_with_warnings').length;
  const passRate    = total > 0 ? Math.round((total - flaggedRuns) / total * 100) : 0;
  const totalFlagged = runs.reduce(
    (acc, r) => acc + (r.day_log || []).filter(d => d.compliance_status === 'flagged').length, 0
  );

  const kpiRow = `<div class="ab-sc-grid" style="margin-bottom:8px">
    ${kpi('Sessions Played', total)}
    ${kpi('Pass Rate', passRate + '%')}
    ${kpi('Total Flagged Days', totalFlagged)}
    ${kpi('Latest Status', statusBadge(runs[0]?.overall_status ?? 'pass'))}
  </div>`;

  // Session table rows with expandable per-day detail
  const tableRows = runs.map(r => {
    const dayLog      = r.day_log || [];
    const flaggedDays = dayLog.filter(d => d.compliance_status === 'flagged').length;
    const instrument  = (r.request || '').match(/:\s*(\w+)\s+over/)?.[1] ?? '—';

    const detailRows = dayLog.map((d, i) => `<tr>
      <td style="font-family:var(--fm);text-align:center">${i + 1}</td>
      <td style="font-family:var(--fm)">${esc(d.date)}</td>
      <td><span class="badge neutral">${esc(d.user_action)}</span></td>
      <td><span class="badge neutral">${esc(d.ai_action)}</span></td>
      <td>${compBadge(d.compliance_status)}</td>
      <td style="color:var(--t3);font-size:10px;max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(d.compliance_rule)}">${esc(d.compliance_rule || '—')}</td>
    </tr>`).join('');

    const detailTbl = dayLog.length ? `
      <tr id="gc-detail-${r.run_id}" style="display:none">
        <td colspan="6" style="padding:0 0 8px 0">
          <table style="width:100%;font-size:11px;border-top:1px solid var(--border)">
            <thead><tr>
              <th>Day</th><th>Date</th><th>You</th><th>AI</th><th>Compliance</th><th>Rule</th>
            </tr></thead>
            <tbody>${detailRows}</tbody>
          </table>
        </td>
      </tr>` : '';

    const flagColor = flaggedDays > 0 ? 'var(--warn)' : 'var(--ok)';
    return `
      <tr style="cursor:pointer" onclick="toggleGcDetail('${r.run_id}')">
        <td style="font-family:var(--fm);white-space:nowrap">${fmtRunId(r.run_id)}</td>
        <td><span class="badge neutral" style="text-transform:uppercase">${esc(instrument)}</span></td>
        <td style="font-family:var(--fm)">${r.duration_minutes ?? '—'} min</td>
        <td>${statusBadge(r.overall_status)}</td>
        <td style="font-family:var(--fm);color:${flagColor}">${flaggedDays} / ${dayLog.length || '—'}</td>
        <td style="color:var(--t3);font-size:10px">${dayLog.length ? '▶ details' : '—'}</td>
      </tr>${detailTbl}`;
  }).join('');

  const tbl = `<div class="tbl-wrap"><table>
    <thead><tr>
      <th>Session</th><th>Instrument</th><th>Duration</th><th>Status</th><th>Flagged Days</th><th></th>
    </tr></thead>
    <tbody>${tableRows}</tbody>
  </table></div>`;

  grid.innerHTML = kpiRow + panel('sessions', 'Game Sessions — Compliance History', tbl);
}

export function toggleGcDetail(runId) {
  const row = document.getElementById('gc-detail-' + runId);
  if (row) row.style.display = row.style.display === 'none' ? 'table-row' : 'none';
}
