// ── Invest Game App — Concepts (Investment Workflow & Agents) ─────────────────
// Ported from rita/learnings.js — agent workflow section (8 tabs, 2 charts each).
import { api } from '../shared/api.js';
import { mkChart, C } from '../shared/charts.js';

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

function _num(v) {
  if (v == null || v === '') return null;
  const n = parseFloat(v);
  return isNaN(n) ? null : n;
}

function _drawdown(values) {
  let peak = -Infinity;
  return values.map(v => {
    if (v == null) return null;
    if (v > peak) peak = v;
    return peak > 0 ? ((v - peak) / peak) * 100 : 0;
  });
}

function _histogram(vals, nBins) {
  if (!vals.length) return { labels: [], counts: [] };
  const mn = Math.min(...vals), mx = Math.max(...vals);
  const w = (mx - mn) / nBins || 1;
  const counts = new Array(nBins).fill(0);
  vals.forEach(v => { const i = Math.min(Math.floor((v - mn) / w), nBins - 1); counts[i]++; });
  const labels = counts.map((_, i) => (mn + w * (i + 0.5)).toFixed(3));
  return { labels, counts };
}

export async function loadConcepts() {
  const statusEl = document.getElementById('aw-status');
  if (statusEl) statusEl.textContent = 'Loading...';

  try {
    const inst = (localStorage.getItem('ritaInstrument') || 'ASML').toUpperCase();
    const [perfRes, sigRes, btdRes, shapRes, histRes] = await Promise.allSettled([
      api('/api/v1/performance-summary'),
      api(`/api/v1/market-signals?timeframe=daily&periods=252&instrument=${inst}`),
      api(`/api/v1/experience/rita/backtest-daily?instrument=${inst}`),
      api('/api/v1/shap'),
      api(`/api/v1/experience/rita/training-history?instrument=${inst}`),
    ]);

    const perf = perfRes.status === 'fulfilled' ? perfRes.value : null;
    const sig  = sigRes.status === 'fulfilled' && Array.isArray(sigRes.value) ? sigRes.value : [];
    const btd  = btdRes.status === 'fulfilled' ? btdRes.value : null;
    const shap = shapRes.status === 'fulfilled' ? shapRes.value : null;
    const hist = histRes.status === 'fulfilled' && Array.isArray(histRes.value) ? histRes.value : [];

    if (statusEl) statusEl.textContent = '';

    renderGoal(perf, sig);
    renderResearch(sig);
    renderSentiment(sig);
    renderTechnical(sig);
    renderStrategy(sig);
    renderScenario(btd);
    renderExecution(shap, btd);
    renderOutcome(hist);
  } catch (e) {
    if (statusEl) statusEl.textContent = 'Failed to load data';
  }
}

// a1 — Initiation / Financial Goal
function renderGoal(perf, sig) {
  const p = perf?.performance || perf || {};
  const sharpe = _num(p.sharpe_ratio ?? p.sharpe) ?? 0;
  const mdd    = Math.abs(_num(p.max_drawdown_pct ?? p.max_drawdown) ?? 0);
  const ret    = _num(p.portfolio_total_return_pct ?? p.total_return_pct ?? p.total_return) ?? 0;
  const winRt  = _num(p.win_rate_pct ?? p.win_rate) ?? 0;
  if (!perf) { _noData('aw-a1-c1'); _noData('aw-a1-c2'); return; }
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
  if (!sig.length) { _noData('aw-a1-c2'); return; }
  const closes = sig.map(r => _num(r.Close));
  const rets = closes.slice(1).map((c, i) => (c != null && closes[i] != null && closes[i] !== 0) ? (c - closes[i]) / closes[i] : null).filter(v => v != null);
  const bins = _histogram(rets, 20);
  mkChart('aw-a1-c2', {
    type: 'bar',
    data: {
      labels: bins.labels,
      datasets: [{ label: 'Frequency', data: bins.counts, backgroundColor: 'rgba(0,86,184,.15)', borderColor: C.run, borderWidth: 1, borderRadius: 2 }]
    },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: _LEG }, scales: _scales() }
  });
}

// a2 — Research Analyst
function renderResearch(sig) {
  if (!sig.length) { _noData('aw-a2-c1'); _noData('aw-a2-c2'); return; }
  const labels = sig.map(r => r.date);
  const close  = sig.map(r => _num(r.Close));
  mkChart('aw-a2-c1', {
    type: 'line',
    data: {
      labels,
      datasets: [{ label: 'Close', data: close, borderColor: C.run, backgroundColor: 'rgba(0,86,184,.07)', fill: true, tension: 0.2, pointRadius: 0, borderWidth: 2, spanGaps: false }]
    },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: _LEG }, scales: _scales({ ticks: { maxTicksLimit: 12, callback: _xFmtShort, font: { size: 10 } } }) }
  });
  const vol = sig.map(r => _num(r.Volume));
  mkChart('aw-a2-c2', {
    type: 'bar',
    data: {
      labels,
      datasets: [{ label: 'Volume', data: vol, backgroundColor: 'rgba(107,47,160,.12)', borderColor: C.mon, borderWidth: 1, borderRadius: 1 }]
    },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: _LEG }, scales: _scales({ ticks: { maxTicksLimit: 12, callback: _xFmtShort, font: { size: 10 } } }) }
  });
}

// a3 — Sentiment Analyst
function renderSentiment(sig) {
  if (!sig.length) { _noData('aw-a3-c1'); _noData('aw-a3-c2'); return; }
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
  const bbPctB = sig.map(r => _num(r.bb_pct_b));
  mkChart('aw-a3-c2', {
    type: 'line',
    data: {
      labels,
      datasets: [
        { label: 'BB %B', data: bbPctB, borderColor: C.warn, backgroundColor: 'rgba(181,120,33,.08)', fill: true, tension: 0.2, pointRadius: 0, borderWidth: 2, spanGaps: false },
        { label: 'Overbought 1.0', data: sig.map(() => 1.0), borderColor: 'rgba(155,28,28,.30)', borderDash: [4, 3], fill: false, pointRadius: 0, borderWidth: 1 },
        { label: 'Oversold 0.0', data: sig.map(() => 0.0), borderColor: 'rgba(0,128,0,.30)', borderDash: [4, 3], fill: false, pointRadius: 0, borderWidth: 1 },
      ]
    },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: _LEG }, scales: _scales({ ticks: { maxTicksLimit: 12, callback: _xFmtShort, font: { size: 10 } } }) }
  });
}

// a4 — Technical Analyst
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

// a5 — Strategy Analyst
function renderStrategy(sig) {
  if (!sig.length) { _noData('aw-a5-c1'); _noData('aw-a5-c2'); return; }
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
  const atr = sig.map(r => { const a = _num(r.atr_14); const c = _num(r.Close); return (a != null && c) ? (a / c) * 100 : null; });
  mkChart('aw-a5-c2', {
    type: 'line',
    data: {
      labels,
      datasets: [{ label: 'ATR %', data: atr, borderColor: C.danger, backgroundColor: 'rgba(185,28,28,.06)', fill: true, tension: 0.2, pointRadius: 0, borderWidth: 2, spanGaps: false }]
    },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: _LEG }, scales: _scales({ ticks: { maxTicksLimit: 12, callback: _xFmtShort, font: { size: 10 } } }) }
  });
}

// a6 — Scenario Analyst
function renderScenario(btd) {
  const days = Array.isArray(btd) ? btd : (btd?.daily ?? []);
  if (!days.length) { _noData('aw-a6-c1'); _noData('aw-a6-c2'); return; }
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
  const dd = _drawdown(ddqn);
  mkChart('aw-a6-c2', {
    type: 'line',
    data: {
      labels,
      datasets: [{ label: 'Drawdown %', data: dd, borderColor: C.danger, backgroundColor: 'rgba(185,28,28,.08)', fill: true, tension: 0.2, pointRadius: 0, borderWidth: 2, spanGaps: false }]
    },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: _LEG }, scales: _scales({ ticks: { maxTicksLimit: 12, callback: _xFmtShort, font: { size: 10 } } }) }
  });
}

// a7 — Execution Analyst
function renderExecution(shap, btd) {
  const rows = Array.isArray(shap) ? shap : (shap?.features ?? shap?.shap_values ?? []);
  if (!rows.length) { _noData('aw-a7-c1'); } else {
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
  const days = Array.isArray(btd) ? btd : (btd?.daily ?? []);
  if (!days.length) { _noData('aw-a7-c2'); return; }
  const labels = days.map(d => d.date ?? d.Date ?? '');
  const rawAlloc = days.map(d => _num(d.allocation ?? d.position ?? d.action));
  const alloc  = rawAlloc.map(v => v != null ? v * 100 : null);
  mkChart('aw-a7-c2', {
    type: 'line',
    data: {
      labels,
      datasets: [{ label: 'Allocation %', data: alloc, borderColor: C.build, backgroundColor: 'rgba(26,107,60,.08)', fill: true, tension: 0, pointRadius: 0, borderWidth: 1.5, spanGaps: false }]
    },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: _LEG }, scales: _scales({ ticks: { maxTicksLimit: 12, callback: _xFmtShort, font: { size: 10 } } }) }
  });
}

// a8 — Outcome Analyst
function renderOutcome(hist) {
  if (!hist.length) { _noData('aw-a8-c1'); _noData('aw-a8-c2'); return; }
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
  const winRt = hist.map(r => _num(r.win_rate_pct ?? r.win_rate));
  mkChart('aw-a8-c2', {
    type: 'bar',
    data: {
      labels,
      datasets: [{ label: 'Win Rate %', data: winRt, backgroundColor: 'rgba(26,107,60,.15)', borderColor: C.build, borderWidth: 1.5, borderRadius: 3 }]
    },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: _LEG }, scales: _scales() }
  });
}

// Empty-state placeholder
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
  ctx.fillText('No data — run the pipeline first', canvas.width / 2, canvas.height / 2);
}
