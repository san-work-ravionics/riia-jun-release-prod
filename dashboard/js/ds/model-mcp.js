import { api } from './api.js';
import { DS_C, mkTbl } from './utils.js';
import { mkChart } from '../shared/charts.js';

const C = DS_C;

export async function loadModelMcp() {
  try {
    const rows = await api('/api/v1/mcp-calls?limit=100');
    if (!rows || !rows.length) {
      document.getElementById('mmcp-table-wrap').innerHTML = '<div class="empty">No MCP call log entries found.</div>';
      return;
    }

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

    mkChart('ch-mmcp-tools', {
      type: 'bar',
      data: {
        labels: tools,
        datasets: [{ label: 'Calls', data: counts, backgroundColor: tools.map((_, i) => palette[i % palette.length] + 'CC'), borderRadius: 3 }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { labels: { font: { family: "'IBM Plex Mono'", size: 10 } } } },
        scales: { x: { grid: { display: false } }, y: { grid: { color: 'rgba(0,0,0,.04)' } } }
      }
    });

    mkChart('ch-mmcp-duration', {
      type: 'bar',
      data: {
        labels: tools,
        datasets: [{ label: 'Avg ms', data: avgDur.map(v => Math.round(v)), backgroundColor: tools.map((_, i) => palette[i % palette.length] + '88'), borderRadius: 3 }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { labels: { font: { family: "'IBM Plex Mono'", size: 10 } } } },
        scales: { x: { grid: { display: false } }, y: { grid: { color: 'rgba(0,0,0,.04)' }, ticks: { callback: v => v + 'ms' } } }
      }
    });

    const total = counts.reduce((a, b) => a + b, 0);
    mkChart('ch-mmcp-share', {
      type: 'bar',
      data: {
        labels: tools,
        datasets: [{ label: 'Calls', data: counts, backgroundColor: tools.map((_, i) => palette[i % palette.length] + 'AA'), borderRadius: 3 }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { labels: { font: { family: "'IBM Plex Mono'", size: 10 } } },
          tooltip: { callbacks: { label: ctx => ` ${ctx.parsed.y} (${total ? Math.round(ctx.parsed.y / total * 100) : 0}%)` } }
        },
        scales: { x: { grid: { display: false } }, y: { grid: { color: 'rgba(0,0,0,.04)' } } }
      }
    });

    document.getElementById('mmcp-table-wrap').innerHTML = mkTbl(rows.slice(0, 50), [
      { key: 'timestamp', label: 'Timestamp', mono: true },
      { key: 'tool_name', label: 'Tool' },
      { key: 'status', label: 'Status', badge: true },
      { key: 'duration_ms', label: 'Duration', mono: true, right: true },
      { key: 'args_summary', label: 'Args' },
      { key: 'result_summary', label: 'Result' }
    ]);
  } catch (e) {
    document.getElementById('mmcp-table-wrap').innerHTML = '<div class="empty">Error loading MCP call log.</div>';
  }
}
