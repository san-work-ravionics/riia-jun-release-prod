// ── MCP Calls ──────────────────────────────────────────────
import { api } from './api.js';
import { badge, fmtMs, setEl } from './utils.js';
import { mkChart, C } from './charts.js';

export async function loadMcp() {
  try {
    const rows = await api('/api/v1/mcp-calls?limit=100');
    if (!rows || !rows.length) {
      setEl('mcp-table-wrap', '<div class="empty">No MCP call log entries found.</div>');
      return;
    }

    // Aggregate by tool
    const byTool = {};
    rows.forEach(r => {
      const t = r.tool_name || 'unknown';
      if (!byTool[t]) byTool[t] = { count: 0, dur_sum: 0, ok: 0 };
      byTool[t].count++;
      byTool[t].dur_sum += parseFloat(r.duration_ms || 0);
      if ((r.status || '').toLowerCase() === 'ok') byTool[t].ok++;
    });
    const tools = Object.keys(byTool);
    const counts = tools.map(t => byTool[t].count);
    const avgDur = tools.map(t => byTool[t].dur_sum / byTool[t].count);

    const palette = [C.run, C.build, C.mon, C.warn, C.danger, '#5B6FA0', '#8B6914', '#3D7A6B'];

    mkChart('chart-mcp-tools', {
      type: 'bar',
      data: { labels: tools, datasets: [{ label: 'Calls', data: counts, backgroundColor: tools.map((_, i) => palette[i % palette.length] + 'CC'), borderRadius: 3 }] },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { grid: { display: false }, ticks: { font: { size: 9 } } },
          y: { grid: { color: 'rgba(0,0,0,.04)' }, ticks: { font: { family: C.mono, size: 10 } } }
        }
      }
    });

    mkChart('chart-mcp-duration', {
      type: 'bar',
      data: { labels: tools, datasets: [{ label: 'Avg ms', data: avgDur.map(v => Math.round(v)), backgroundColor: tools.map((_, i) => palette[i % palette.length] + '88'), borderRadius: 3 }] },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { grid: { display: false }, ticks: { font: { size: 9 } } },
          y: { grid: { color: 'rgba(0,0,0,.04)' }, ticks: { callback: v => v + 'ms', font: { family: C.mono, size: 10 } } }
        }
      }
    });

    const total = counts.reduce((a, b) => a + b, 0);
    mkChart('chart-mcp-share', {
      type: 'bar',
      data: { labels: tools, datasets: [{ label: 'Calls', data: counts, backgroundColor: tools.map((_, i) => palette[i % palette.length] + 'AA'), borderRadius: 3 }] },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: ctx => ` ${ctx.parsed.y} (${total ? Math.round(ctx.parsed.y / total * 100) : 0}%)` } }
        },
        scales: {
          x: { grid: { display: false }, ticks: { font: { size: 9 } } },
          y: { grid: { color: 'rgba(0,0,0,.04)' }, ticks: { font: { family: C.mono, size: 10 } } }
        }
      }
    });

    setEl('mcp-table-wrap', `
      <table>
        <thead><tr><th>Timestamp</th><th>Tool</th><th>Status</th><th>Duration</th><th>Args</th><th>Result</th></tr></thead>
        <tbody>${rows.slice(0, 50).map(r => `
          <tr>
            <td class="td-mono" style="font-size:11px">${r.timestamp || '—'}</td>
            <td style="font-weight:500">${r.tool_name || '—'}</td>
            <td>${badge(r.status)}</td>
            <td class="td-mono">${fmtMs(r.duration_ms)}</td>
            <td style="font-size:11px;color:var(--t3);max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${r.args_summary || '—'}</td>
            <td style="font-size:11px;color:var(--t3);max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${r.result_summary || '—'}</td>
          </tr>`).join('')}
        </tbody>
      </table>`);
  } catch (e) {
    setEl('mcp-table-wrap', '<div class="empty">Error loading MCP call log.</div>');
  }
}
