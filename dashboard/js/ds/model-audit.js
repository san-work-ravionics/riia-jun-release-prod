import { api } from './api.js';
import { DS_C, mkTbl } from './utils.js';

export async function loadModelAudit() {
  try {
    const [history, stepLog] = await Promise.all([
      api('/api/v1/experience/rita/training-history').catch(() => []),
      api('/api/experience/ops/step-log').catch(() => []),
    ]);

    const rounds = history.length;
    const elRounds = document.getElementById('mau-rounds');
    if (elRounds) elRounds.textContent = rounds || '0';

    if (rounds > 0) {
      const passed = history.filter(r => r.backtest_constraints_met).length;
      const passRate = ((passed / rounds) * 100).toFixed(0);
      const prEl = document.getElementById('mau-pass-rate');
      if (prEl) { prEl.textContent = passRate + '%'; prEl.className = 'kpi-value ' + (passed === rounds ? 'pos' : passed > 0 ? 'neu' : 'neg'); }

      const bestSharpe = Math.max(...history.map(r => parseFloat(r.backtest_sharpe) || 0));
      const bsEl = document.getElementById('mau-best-sharpe');
      if (bsEl) { bsEl.textContent = bestSharpe.toFixed(3); bsEl.className = 'kpi-value ' + (bestSharpe >= 1 ? 'pos' : 'neg'); }
      const bestRound = history.reduce((a, b) =>
        (parseFloat(b.backtest_sharpe) || 0) > (parseFloat(a.backtest_sharpe) || 0) ? b : a, history[0]);
      const subEl = document.getElementById('mau-best-sharpe-sub');
      if (subEl) subEl.textContent = bestRound.timestamp ? `round on ${bestRound.timestamp.slice(0, 10)}` : 'across all rounds';
    }

    if (history.length === 0) {
      document.getElementById('mau-history-wrap').innerHTML = '<div class="empty">No training history yet — run the full pipeline first.</div>';
    } else {
      document.getElementById('mau-history-wrap').innerHTML = mkTbl([...history].reverse(), [
        { key: 'round', label: '#', mono: true },
        { key: 'timestamp', label: 'Date', mono: true },
        { key: 'source', label: 'Source' },
        { key: 'backtest_sharpe', label: 'Sharpe', mono: true, right: true },
        { key: 'backtest_mdd_pct', label: 'Max DD%', mono: true, right: true },
        { key: 'backtest_cagr_pct', label: 'CAGR%', mono: true, right: true },
        { key: 'backtest_constraints_met', label: 'Constraints' },
        { key: 'notes', label: 'Notes' }
      ]);
    }

    const recent = stepLog.slice(0, 40);
    if (recent.length === 0) {
      document.getElementById('mau-steplog-wrap').innerHTML = '<div class="empty">No step log entries yet.</div>';
    } else {
      document.getElementById('mau-steplog-wrap').innerHTML = mkTbl(recent, [
        { key: 'step_num', label: 'Step', mono: true },
        { key: 'step_name', label: 'Name' },
        { key: 'status', label: 'Status', badge: true },
        { key: 'started_at', label: 'Started', mono: true },
        { key: 'ended_at', label: 'Ended', mono: true },
        { key: 'duration_secs', label: 'Duration', mono: true, right: true },
        { key: 'notes', label: 'Notes' }
      ]);
    }
  } catch (e) {
    console.warn('loadModelAudit error', e);
    document.getElementById('mau-history-wrap').innerHTML = `<div class="empty" style="color:var(--danger)">${e.message}</div>`;
  }
}
