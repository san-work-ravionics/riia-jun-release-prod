// ── Audit ───────────────────────────────────────────────────
import { api } from './api.js';
import { fmt, fmtPct, setEl } from './utils.js';
import { createCache } from '../shared/api-cache.js';

const cachedApi = createCache(api);

export async function loadAudit() {
  try {
    const [history, stepLog] = await Promise.all([
      cachedApi('/api/v1/experience/rita/training-history', 120000).catch(() => []),
      api('/api/experience/ops/step-log').catch(() => []),
    ]);

    // ── KPIs ──────────────────────────────────────────────
    const rounds = history.length;
    setEl('audit-rounds', rounds || '0');

    if (rounds > 0) {
      const passed = history.filter(r => r.backtest_constraints_met).length;
      const passRate = ((passed / rounds) * 100).toFixed(0);
      const el = document.getElementById('audit-pass-rate');
      setEl('audit-pass-rate', passRate + '%');
      if (el) el.className = 'kpi-value ' + (passed === rounds ? 'pos' : passed > 0 ? 'neu' : 'neg');

      const bestSharpe = Math.max(...history.map(r => parseFloat(r.backtest_sharpe) || 0));
      const bestEl = document.getElementById('audit-best-sharpe');
      setEl('audit-best-sharpe', bestSharpe.toFixed(3));
      if (bestEl) bestEl.className = 'kpi-value ' + (bestSharpe >= 1 ? 'pos' : 'neg');

      const bestRound = history.reduce((a, b) =>
        (parseFloat(b.backtest_sharpe) || 0) > (parseFloat(a.backtest_sharpe) || 0) ? b : a, history[0]);
      setEl('audit-best-sharpe-sub', bestRound.timestamp ? `round on ${bestRound.timestamp.slice(0, 10)}` : 'across all rounds');
    }

    // ── Training history table ─────────────────────────────
    if (history.length === 0) {
      setEl('audit-history-wrap', '<div class="empty">No training history yet — run the full pipeline first.</div>');
    } else {
      const cols = ['round', 'timestamp', 'source', 'backtest_sharpe', 'backtest_mdd_pct', 'backtest_cagr_pct', 'backtest_constraints_met', 'notes'];
      const labels = ['#', 'Date', 'Source', 'Sharpe', 'Max DD%', 'CAGR%', 'Constraints', 'Notes'];
      const rows = [...history].reverse().map(r => `<tr>
        <td class="td-mono">${r.round ?? '—'}</td>
        <td class="td-mono" style="font-size:11px">${(r.timestamp || '—').slice(0, 16)}</td>
        <td>${r.source || '—'}</td>
        <td class="td-mono" style="color:${parseFloat(r.backtest_sharpe) >= 1 ? 'var(--build)' : 'var(--danger)'}">${fmt(r.backtest_sharpe, 3)}</td>
        <td class="td-mono" style="color:${Math.abs(parseFloat(r.backtest_mdd_pct)) < 10 ? 'var(--build)' : 'var(--danger)'}">${fmtPct(r.backtest_mdd_pct)}</td>
        <td class="td-mono">${fmtPct(r.backtest_cagr_pct)}</td>
        <td style="text-align:center">${r.backtest_constraints_met ? '<span class="badge ok">Pass</span>' : '<span class="badge err">Fail</span>'}</td>
        <td style="font-size:11px;color:var(--t3)">${r.notes || ''}</td>
      </tr>`).join('');
      setEl('audit-history-wrap', `<table><thead><tr>${labels.map(l => `<th>${l}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table>`);
    }

    // ── Step execution log ─────────────────────────────────
    const recent = stepLog.slice(0, 40);
    if (recent.length === 0) {
      setEl('audit-steplog-wrap', '<div class="empty">No step log entries yet.</div>');
    } else {
      const logCols = ['step_num', 'step_name', 'status', 'started_at', 'ended_at', 'duration_secs', 'notes'];
      const logLabels = ['Step', 'Name', 'Status', 'Started', 'Ended', 'Duration', 'Notes'];
      const logRows = recent.map(r => {
        const statusCls = r.status === 'completed' ? 'ok' : r.status === 'failed' ? 'err' : 'run';
        return `<tr>
          <td class="td-mono">${r.step_num ?? '—'}</td>
          <td style="font-size:11px">${r.step_name || '—'}</td>
          <td><span class="badge ${statusCls}">${r.status || '—'}</span></td>
          <td class="td-mono" style="font-size:11px">${(r.started_at || '—').slice(0, 16)}</td>
          <td class="td-mono" style="font-size:11px">${(r.ended_at || '—').slice(0, 16)}</td>
          <td class="td-mono">${r.duration_secs != null ? parseFloat(r.duration_secs).toFixed(1) + 's' : '—'}</td>
          <td style="font-size:11px;color:var(--t3)">${r.notes || ''}</td>
        </tr>`;
      }).join('');
      setEl('audit-steplog-wrap', `<table><thead><tr>${logLabels.map(l => `<th>${l}</th>`).join('')}</tr></thead><tbody>${logRows}</tbody></table>`);
    }
  } catch (e) {
    console.warn('loadAudit error', e);
    setEl('audit-history-wrap', `<div class="empty" style="color:var(--danger)">${e.message}</div>`);
  }
}
