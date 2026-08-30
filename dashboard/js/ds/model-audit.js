import { api } from './api.js';
import { DS_C, mkTbl } from './utils.js';

// ── Comparison table builder ─────────────────────────────────────────────────

const _COMPARE_COLS = [
  { key: '_date',              label: 'Date',           mono: true },
  { key: 'model_version',     label: 'Model',          mono: true },
  { key: '_feature_set',      label: 'Features' },
  { key: 'timesteps',         label: 'Steps',          mono: true, right: true, fmt: v => v ? (v/1000).toFixed(0)+'k' : '—' },
  { key: 'train_sharpe',      label: 'Tr Sharpe',      mono: true, right: true, higher: true },
  { key: 'train_return_pct',  label: 'Tr Ret%',        mono: true, right: true, higher: true },
  { key: 'train_mdd_pct',     label: 'Tr MDD%',        mono: true, right: true, higher: false },
  { key: 'val_sharpe',        label: 'Val Sharpe',     mono: true, right: true, higher: true },
  { key: 'val_return_pct',    label: 'Val Ret%',       mono: true, right: true, higher: true },
  { key: 'backtest_sharpe',   label: 'BT Sharpe',      mono: true, right: true, higher: true },
  { key: 'backtest_return_pct', label: 'BT Ret%',      mono: true, right: true, higher: true },
  { key: 'backtest_mdd_pct',  label: 'BT MDD%',       mono: true, right: true, higher: false },
  { key: 'backtest_constraints_met', label: 'Pass' },
];

function _buildCompareTable(runs) {
  if (!runs || !runs.length) return '<div class="empty">No training runs yet — run the pipeline first.</div>';

  const top10 = runs.slice(0, 10);

  top10.forEach(r => {
    r._date = r.timestamp ? r.timestamp.slice(0, 10) : '—';
    const mv = r.model_version || '';
    r._feature_set = mv.startsWith('rita_ddqn_asta') ? 'asta' : 'technical';
  });

  const numCols = _COMPARE_COLS.filter(c => c.higher !== undefined);
  const bestIdx = {};
  for (const col of numCols) {
    let bestVal = null;
    let bestI = -1;
    for (let i = 0; i < top10.length; i++) {
      const v = parseFloat(top10[i][col.key]);
      if (isNaN(v)) continue;
      const cmpVal = col.higher ? v : -Math.abs(v);
      if (bestVal === null || cmpVal > bestVal) {
        bestVal = cmpVal;
        bestI = i;
      }
    }
    if (bestI >= 0) bestIdx[col.key] = bestI;
  }

  const ths = _COMPARE_COLS.map(c =>
    `<th${c.right ? ' style="text-align:right"' : ''} style="white-space:nowrap;${c.right ? 'text-align:right;' : ''}font-size:10px">${c.label}</th>`
  ).join('');

  const trs = top10.map((r, ri) => {
    const tds = _COMPARE_COLS.map(c => {
      const raw = r[c.key] ?? '—';
      let v;

      if (c.key === '_feature_set') {
        const isAsta = raw === 'asta';
        v = `<span class="badge ${isAsta ? 'run' : 'neu'}" style="font-size:9px;${isAsta ? 'background:rgba(107,47,160,.15);color:#6B2FA0;border-color:#6B2FA0' : ''}">${isAsta ? 'ASTA' : 'Technical'}</span>`;
        return `<td>${v}</td>`;
      }

      if (c.key === 'backtest_constraints_met') {
        if (raw === true) v = '<span class="badge ok" style="font-size:9px">✓</span>';
        else if (raw === false) v = '<span class="badge err" style="font-size:9px">✗</span>';
        else v = '—';
        return `<td style="text-align:center">${v}</td>`;
      }

      if (c.key === 'model_version') {
        const short = String(raw).length > 22 ? raw.slice(0, 22) + '…' : raw;
        v = `<span title="${raw}">${short}</span>`;
      } else if (c.fmt) {
        v = c.fmt(raw);
      } else if (typeof raw === 'number') {
        v = raw.toFixed(2);
      } else {
        v = raw;
      }

      const isBest = bestIdx[c.key] === ri;
      const style = [
        c.mono ? 'font-family:var(--fm);font-size:11px' : '',
        c.right ? 'text-align:right' : '',
        isBest ? 'background:rgba(46,125,50,.12);font-weight:700' : '',
      ].filter(Boolean).join(';');

      return `<td${style ? ` style="${style}"` : ''}>${v}</td>`;
    }).join('');

    return `<tr>${tds}</tr>`;
  }).join('');

  return `<table style="font-size:11px"><thead><tr>${ths}</tr></thead><tbody>${trs}</tbody></table>`;
}

// ── Main loader ──────────────────────────────────────────────────────────────

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

    // ── Comparison table ──────────────────────────────────────────────────────
    const cmpWrap = document.getElementById('mau-compare-wrap');
    if (cmpWrap) {
      cmpWrap.innerHTML = _buildCompareTable(history);
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
