// ── Learnings ───────────────────────────────────────────────
import { t } from '../shared/i18n.js';
import { api } from './api.js';
import { mkChart, C } from './charts.js';

export function toggleLearnCard(id) {
  const body = document.getElementById('learn-body-' + id);
  const chev = document.getElementById('learn-chevron-' + id);
  if (!body) return;
  const open = body.style.display !== 'none';
  body.style.display = open ? 'none' : 'block';
  if (chev) chev.textContent = open ? '▶' : '▼';
}

export async function loadLearnings() {
  // Cards 1–3: placeholder only — content added by user separately
  // (no dynamic rendering needed; HTML is static in rita.html)

  // Card 4: Market Trends — live charts
  try {
    const rows = await api('/api/v1/market-signals?timeframe=daily&periods=252&instrument=NIFTY');
    if (!rows || !rows.length) {
      const c4 = document.getElementById('learn-body-trends');
      if (c4) c4.innerHTML = `<div class="empty">${t('learnings.no_data')}</div>`;
      return;
    }
    const dates = rows.map(r => r.date);
    const _xFmt = v => typeof v === 'string' ? v.slice(5) : v;

    mkChart('chart-learn-price', {
      type: 'line',
      data: {
        labels: dates,
        datasets: [{
          label: t('learnings.label_nifty_close'), data: rows.map(r => r.Close),
          borderColor: C.run, backgroundColor: 'rgba(0,86,184,0.07)',
          fill: true, tension: 0.2, pointRadius: 0, borderWidth: 2
        }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { position: 'top', labels: { font: { size: 11 } } } },
        scales: {
          x: { grid: { display: false }, ticks: { maxTicksLimit: 12, callback: _xFmt, font: { size: 10 } } },
          y: { grid: { color: 'rgba(0,0,0,.04)' }, ticks: { font: { size: 10 } } }
        }
      }
    });

    mkChart('chart-learn-rsi', {
      type: 'line',
      data: {
        labels: dates,
        datasets: [
          {
            label: 'RSI-14', data: rows.map(r => parseFloat(r.rsi_14)),
            borderColor: C.warn, backgroundColor: 'transparent',
            fill: false, tension: 0.2, pointRadius: 0, borderWidth: 2
          },
          {
            label: t('learnings.label_overbought'), data: rows.map(() => 60),
            borderColor: 'rgba(155,28,28,0.35)', borderDash: [4, 3],
            fill: false, pointRadius: 0, borderWidth: 1
          },
          {
            label: t('learnings.label_oversold'), data: rows.map(() => 30),
            borderColor: 'rgba(0,128,0,0.35)', borderDash: [4, 3],
            fill: false, pointRadius: 0, borderWidth: 1
          }
        ]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { position: 'top', labels: { font: { size: 11 } } } },
        scales: {
          x: { grid: { display: false }, ticks: { maxTicksLimit: 12, callback: _xFmt, font: { size: 10 } } },
          y: { min: 0, max: 100, grid: { color: 'rgba(0,0,0,.04)' }, ticks: { font: { size: 10 } } }
        }
      }
    });

  } catch (e) {
    console.warn('learnings chart error', e);
  }

  // ── Investment Workflow & Agents — tabbed agent block ──────
  // Reuses existing endpoints only (no new path). One render error must
  // never break the Concepts page, so the whole block is wrapped in try/catch.
  try {
    await loadAgentWorkflow();
  } catch (e) {
    console.warn('agent-workflow render error', e);
  }
}

// ── Investment Workflow & Agents ─────────────────────────────
// Mirrors the DS Lab CRISP-DM tab pattern (switchConceptTab / _noData),
// but targets the `aw-` prefixed panels inside #sec-learnings.

export function switchAgentTab(agentKey, el) {
  document.querySelectorAll('.concept-tab').forEach(t => t.classList.remove('active'));
  el?.classList.add('active');
  document.querySelectorAll('.concept-panel').forEach(p => p.classList.add('hidden'));
  const panel = document.getElementById('aw-' + agentKey);
  if (panel) panel.classList.remove('hidden');
}

const _LEG = { position: 'top', labels: { font: { size: 10 } } };
const _xFmtShort = v => typeof v === 'string' ? v.slice(5) : v;

function _scales(extraX = {}, extraY = {}) {
  return {
    x: { grid: { display: false }, ticks: { maxTicksLimit: 12, font: { size: 10 } }, ...extraX },
    y: { grid: { color: 'rgba(0,0,0,.04)' }, ticks: { font: { size: 10 } }, ...extraY },
  };
}

// Defensive numeric coalescing: returns null (not 0) for missing/blank so
// Chart.js renders gaps when spanGaps:false.
function _num(v) {
  if (v == null || v === '') return null;
  const n = parseFloat(v);
  return isNaN(n) ? null : n;
}

async function loadAgentWorkflow() {
  const statusEl = document.getElementById('aw-status');
  if (statusEl) statusEl.textContent = 'Loading…';

  const [perfRes, sigRes, btdRes, shapRes, histRes] = await Promise.allSettled([
    api('/api/v1/performance-summary'),
    api('/api/v1/market-signals?timeframe=daily&periods=252&instrument=NIFTY'),
    api('/api/v1/experience/rita/backtest-daily?instrument=NIFTY'),
    api('/api/v1/shap'),
    api('/api/v1/experience/rita/training-history?instrument=NIFTY'),
  ]);

  const perf = perfRes.status === 'fulfilled' ? perfRes.value : null;
  const sig  = sigRes.status === 'fulfilled' && Array.isArray(sigRes.value) ? sigRes.value : [];
  const btd  = btdRes.status === 'fulfilled' ? btdRes.value : null;
  const shap = shapRes.status === 'fulfilled' ? shapRes.value : null;
  const hist = histRes.status === 'fulfilled' && Array.isArray(histRes.value) ? histRes.value : [];

  if (statusEl) statusEl.textContent = '';

  renderGoal(perf);
  renderResearch(sig);
  renderSentiment(sig);
  renderTechnical(sig);
  renderStrategy(sig);
  renderScenario(btd);
  renderExecution(shap);
  renderOutcome(hist);
}

// a1 — Initiation / Financial Goal: achieved Sharpe & Max DD vs targets
function renderGoal(perf) {
  const p = perf?.performance || perf || {};
  const sharpe = _num(p.sharpe_ratio ?? p.sharpe) ?? 0;
  const mdd    = Math.abs(_num(p.max_drawdown_pct ?? p.max_drawdown) ?? 0);
  const ret    = _num(p.portfolio_total_return_pct ?? p.total_return_pct ?? p.total_return) ?? 0;
  const winRt  = _num(p.win_rate_pct ?? p.win_rate) ?? 0;
  if (!perf) { _noData('aw-a1-c1'); return; }
  mkChart('aw-a1-c1', {
    type: 'bar',
    data: {
      labels: ['Sharpe', 'Max DD %', 'Win Rate %', 'Return %'],
      datasets: [
        { label: 'Target',   data: [1.0, 10, 50, 12], backgroundColor: 'rgba(140,135,122,.18)', borderColor: C.t3, borderWidth: 1.5, borderRadius: 3 },
        { label: 'Achieved', data: [sharpe, mdd, winRt, ret], backgroundColor: 'rgba(26,107,60,.12)', borderColor: C.build, borderWidth: 1.5, borderRadius: 3 },
      ]
    },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: _LEG }, scales: _scales() }
  });
}

// a2 — Research Analyst: instrument close price trend
function renderResearch(sig) {
  if (!sig.length) { _noData('aw-a2-c1'); return; }
  const labels = sig.map(r => r.date);
  const close  = sig.map(r => _num(r.Close));
  mkChart('aw-a2-c1', {
    type: 'line',
    data: {
      labels,
      datasets: [{ label: 'NIFTY Close', data: close, borderColor: C.run, backgroundColor: 'rgba(0,86,184,.07)', fill: true, tension: 0.2, pointRadius: 0, borderWidth: 2, spanGaps: false }]
    },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: _LEG }, scales: _scales({ ticks: { maxTicksLimit: 12, callback: _xFmtShort, font: { size: 10 } } }) }
  });
}

// a3 — Sentiment Analyst: market regime via trend_score
function renderSentiment(sig) {
  if (!sig.length) { _noData('aw-a3-c1'); return; }
  const labels = sig.map(r => r.date);
  const trend  = sig.map(r => _num(r.trend_score));
  mkChart('aw-a3-c1', {
    type: 'line',
    data: {
      labels,
      datasets: [{ label: 'Trend / Regime Score', data: trend, borderColor: C.mon, backgroundColor: 'rgba(107,47,160,.08)', fill: true, tension: 0.2, pointRadius: 0, borderWidth: 2, spanGaps: false }]
    },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: _LEG }, scales: _scales({ ticks: { maxTicksLimit: 12, callback: _xFmtShort, font: { size: 10 } } }) }
  });
}

// a4 — Technical Analyst: RSI(14) with 60/30 bands + MACD line
function renderTechnical(sig) {
  if (!sig.length) { _noData('aw-a4-c1'); _noData('aw-a4-c2'); return; }
  const labels = sig.map(r => r.date);
  const rsi    = sig.map(r => _num(r.rsi_14));
  const macd   = sig.map(r => _num(r.macd));
  mkChart('aw-a4-c1', {
    type: 'line',
    data: {
      labels,
      datasets: [
        { label: 'RSI-14', data: rsi, borderColor: C.warn, backgroundColor: 'transparent', fill: false, tension: 0.2, pointRadius: 0, borderWidth: 2, spanGaps: false },
        { label: 'Overbought 60', data: sig.map(() => 60), borderColor: 'rgba(155,28,28,.35)', borderDash: [4, 3], fill: false, pointRadius: 0, borderWidth: 1 },
        { label: 'Oversold 30', data: sig.map(() => 30), borderColor: 'rgba(0,128,0,.35)', borderDash: [4, 3], fill: false, pointRadius: 0, borderWidth: 1 },
      ]
    },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: _LEG }, scales: _scales({ ticks: { maxTicksLimit: 12, callback: _xFmtShort, font: { size: 10 } } }, { min: 0, max: 100 }) }
  });
  mkChart('aw-a4-c2', {
    type: 'line',
    data: {
      labels,
      datasets: [{ label: 'MACD (12/26)', data: macd, borderColor: C.run, backgroundColor: 'transparent', fill: false, tension: 0.2, pointRadius: 0, borderWidth: 1.5, spanGaps: false }]
    },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: _LEG }, scales: _scales({ ticks: { maxTicksLimit: 12, callback: _xFmtShort, font: { size: 10 } } }) }
  });
}

// a5 — Strategy Analyst: EMA crossover signal
function renderStrategy(sig) {
  if (!sig.length) { _noData('aw-a5-c1'); return; }
  const labels = sig.map(r => r.date);
  const close  = sig.map(r => _num(r.Close));
  const ema5   = sig.map(r => _num(r.ema_5));
  const ema13  = sig.map(r => _num(r.ema_13));
  const ema26  = sig.map(r => _num(r.ema_26));
  const ema50  = sig.map(r => _num(r.ema_50));
  mkChart('aw-a5-c1', {
    type: 'line',
    data: {
      labels,
      datasets: [
        { label: 'Close', data: close, borderColor: 'rgba(140,135,122,.55)', backgroundColor: 'transparent', fill: false, tension: 0.2, pointRadius: 0, borderWidth: 1, spanGaps: false },
        { label: 'EMA-5', data: ema5, borderColor: C.build, backgroundColor: 'transparent', fill: false, tension: 0.2, pointRadius: 0, borderWidth: 1.5, spanGaps: false },
        { label: 'EMA-13', data: ema13, borderColor: C.run, backgroundColor: 'transparent', fill: false, tension: 0.2, pointRadius: 0, borderWidth: 1.5, spanGaps: false },
        { label: 'EMA-26', data: ema26, borderColor: C.warn, backgroundColor: 'transparent', fill: false, tension: 0.2, pointRadius: 0, borderWidth: 1.5, spanGaps: false },
        { label: 'EMA-50', data: ema50, borderColor: C.danger, backgroundColor: 'transparent', fill: false, tension: 0.2, pointRadius: 0, borderWidth: 1.5, spanGaps: false },
      ]
    },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: _LEG }, scales: _scales({ ticks: { maxTicksLimit: 12, callback: _xFmtShort, font: { size: 10 } } }) }
  });
}

// a6 — Scenario Analyst: DDQN strategy vs Buy & Hold cumulative (MDD trigger)
function renderScenario(btd) {
  const days = Array.isArray(btd) ? btd : (btd?.daily ?? []);
  if (!days.length) { _noData('aw-a6-c1'); return; }
  const labels = days.map(d => d.date ?? d.Date ?? '');
  const ddqn   = days.map(d => _num(d.strategy_value ?? d.portfolio_value ?? d.cum_return_pct));
  const bh     = days.map(d => _num(d.bh_value ?? d.benchmark_value ?? d.bh_cum_return_pct));
  mkChart('aw-a6-c1', {
    type: 'line',
    data: {
      labels,
      datasets: [
        { label: 'DDQN Strategy', data: ddqn, borderColor: C.build, backgroundColor: 'rgba(26,107,60,.10)', borderWidth: 2, pointRadius: 0, fill: true, tension: 0.2, spanGaps: false },
        { label: 'Buy & Hold', data: bh, borderColor: C.run, backgroundColor: 'transparent', borderWidth: 1.5, pointRadius: 0, borderDash: [5, 3], tension: 0.2, spanGaps: false },
      ]
    },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: _LEG }, scales: _scales({ ticks: { maxTicksLimit: 12, callback: _xFmtShort, font: { size: 10 } } }) }
  });
}

// a7 — Execution Analyst: feature importance (SHAP |Overall|)
function renderExecution(shap) {
  const rows = Array.isArray(shap) ? shap : (shap?.features ?? shap?.shap_values ?? []);
  if (!rows.length) { _noData('aw-a7-c1'); return; }
  const top = [...rows]
    .sort((a, b) => Math.abs(_num(b.Overall ?? b.importance ?? b.mean_abs ?? b.value) ?? 0)
                  - Math.abs(_num(a.Overall ?? a.importance ?? a.mean_abs ?? a.value) ?? 0))
    .slice(0, 8);
  const fLabels = top.map(r => r.feature ?? r.name ?? String(r));
  const fVals   = top.map(r => Math.abs(_num(r.Overall ?? r.importance ?? r.mean_abs ?? r.value) ?? 0));
  mkChart('aw-a7-c1', {
    type: 'bar',
    data: {
      labels: fLabels,
      datasets: [{ label: 'SHAP |Overall|', data: fVals, backgroundColor: 'rgba(0,86,184,.12)', borderColor: C.run, borderWidth: 1.5, borderRadius: 3 }]
    },
    options: {
      indexAxis: 'y',
      responsive: true, maintainAspectRatio: false, plugins: { legend: _LEG },
      scales: { x: { grid: { color: 'rgba(0,0,0,.04)' }, ticks: { font: { size: 10 } } }, y: { grid: { display: false }, ticks: { font: { size: 10 } } } }
    }
  });
}

// a8 — Outcome Analyst: closed-loop backtest Sharpe/return across rounds
function renderOutcome(hist) {
  if (!hist.length) { _noData('aw-a8-c1'); return; }
  const labels = hist.map((r, i) => `R${r.round ?? i + 1}`);
  const ret    = hist.map(r => _num(r.backtest_return_pct));
  const sharpe = hist.map(r => _num(r.backtest_sharpe));
  mkChart('aw-a8-c1', {
    type: 'line',
    data: {
      labels,
      datasets: [
        { label: 'Backtest Return %', data: ret, borderColor: C.build, backgroundColor: 'rgba(26,107,60,.10)', borderWidth: 2, pointRadius: 5, fill: true, spanGaps: false, yAxisID: 'y' },
        { label: 'Backtest Sharpe', data: sharpe, borderColor: C.run, backgroundColor: 'transparent', borderWidth: 1.5, pointRadius: 5, borderDash: [4, 2], spanGaps: false, yAxisID: 'y1' },
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false, plugins: { legend: _LEG },
      scales: {
        x:  { grid: { display: false }, ticks: { font: { size: 10 } } },
        y:  { position: 'left', grid: { color: 'rgba(0,0,0,.04)' }, ticks: { font: { size: 10 } }, title: { display: true, text: 'Return %' } },
        y1: { position: 'right', grid: { drawOnChartArea: false }, ticks: { font: { size: 10 } }, title: { display: true, text: 'Sharpe' } },
      }
    }
  });
}

// ── Empty-state placeholder (ported from ds/concepts.js) ─────
function _noData(canvasId) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = 'rgba(0,0,0,.04)';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = '#8C877A';
  ctx.font = "11px 'IBM Plex Mono', monospace";
  ctx.textAlign = 'center';
  ctx.fillText('No data — run the NIFTY pipeline first', canvas.width / 2, canvas.height / 2);
}
