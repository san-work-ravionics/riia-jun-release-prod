import { api } from './api.js';
import { DS_C, mkTbl, fmtPctRaw, fmtDT } from './utils.js';
import { mkChart } from '../shared/charts.js';

const C = DS_C;

export async function loadMCP() {
  try {
    const data = await api('/api/v1/mcp-calls');
    const calls = Array.isArray(data) ? data : (data.calls || []);

    // ── KPIs ──────────────────────────────────────────────────────────────────
    const success = calls.filter(c => c.status === 'success' || c.status === 'ok').length;
    const tools   = [...new Set(calls.map(c => c.tool_name || c.tool || c.function))].length;
    const lats    = calls.map(c => parseFloat(c.latency_ms ?? c.duration_ms ?? 0)).filter(v => v > 0);
    const avgLat  = lats.length ? lats.reduce((a, b) => a + b, 0) / lats.length : 0;
    const errors  = calls.filter(c => c.status === 'error' || c.status === 'fail').length;
    const last    = calls.length ? (calls[calls.length - 1].timestamp || calls[calls.length - 1].date || '—') : '—';

    const e = id => document.getElementById(id);
    if (e('mc-total'))   e('mc-total').textContent   = calls.length;
    if (e('mc-success')) e('mc-success').textContent = calls.length ? fmtPctRaw(success / calls.length * 100, 0) : '—';
    if (e('mc-tools'))   e('mc-tools').textContent   = tools;
    if (e('mc-latency')) e('mc-latency').textContent = avgLat > 0 ? `${avgLat.toFixed(0)}ms` : '—';
    if (e('mc-errors'))  { e('mc-errors').textContent = errors; e('mc-errors').className = `kpi-value ${errors > 0 ? 'neg' : 'pos'}`; }
    if (e('mc-last'))    e('mc-last').textContent = String(last).slice(0, 10);

    if (!calls.length) {
      if (e('mmcp-table-wrap')) e('mmcp-table-wrap').innerHTML = '<div class="empty">No MCP calls logged yet. Connect Claude Desktop and invoke a RITA tool.</div>';
      return;
    }

    // ── Charts ────────────────────────────────────────────────────────────────
    const byTool = {};
    calls.forEach(r => {
      const t = r.tool_name || r.tool || r.function || 'unknown';
      if (!byTool[t]) byTool[t] = { count: 0, dur_sum: 0 };
      byTool[t].count++;
      byTool[t].dur_sum += parseFloat(r.duration_ms ?? r.latency_ms ?? 0);
    });
    const toolNames = Object.keys(byTool).sort((a, b) => byTool[b].count - byTool[a].count);
    const counts    = toolNames.map(t => byTool[t].count);
    const avgDur    = toolNames.map(t => byTool[t].dur_sum / byTool[t].count);
    const total     = counts.reduce((a, b) => a + b, 0);
    const palette   = [C.run, C.build, C.mon, C.warn, C.danger, '#5B6FA0', '#8B6914', '#3D7A6B'];

    mkChart('ch-mmcp-tools', {
      type: 'bar',
      data: {
        labels: toolNames,
        datasets: [{ label: 'Calls', data: counts, backgroundColor: toolNames.map((_, i) => palette[i % palette.length] + 'CC'), borderRadius: 3 }]
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
        labels: toolNames,
        datasets: [{ label: 'Avg ms', data: avgDur.map(v => Math.round(v)), backgroundColor: toolNames.map((_, i) => palette[i % palette.length] + '88'), borderRadius: 3 }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { labels: { font: { family: "'IBM Plex Mono'", size: 10 } } } },
        scales: { x: { grid: { display: false } }, y: { grid: { color: 'rgba(0,0,0,.04)' }, ticks: { callback: v => v + 'ms' } } }
      }
    });

    mkChart('ch-mmcp-share', {
      type: 'bar',
      data: {
        labels: toolNames,
        datasets: [{ label: 'Calls', data: counts, backgroundColor: toolNames.map((_, i) => palette[i % palette.length] + 'AA'), borderRadius: 3 }]
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

    // ── Table ─────────────────────────────────────────────────────────────────
    if (e('mmcp-table-wrap')) {
      e('mmcp-table-wrap').innerHTML = mkTbl(calls.slice(0, 100), [
        { key: 'timestamp',     label: 'Time',     mono: true, fmt: fmtDT },
        { key: 'tool_name',     label: 'Tool' },
        { key: 'status',        label: 'Status',   badge: true },
        { key: 'duration_ms',   label: 'Duration', mono: true, right: true },
        { key: 'args_summary',  label: 'Args' },
        { key: 'result_summary',label: 'Result' }
      ]);
    }
  } catch (err) {
    console.warn('MCP:', err);
  }
}
