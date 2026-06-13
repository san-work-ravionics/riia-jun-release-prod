import { api } from './api.js';
import { DS_C, fmtPctRaw } from './utils.js';
import { mkChart } from '../shared/charts.js';

const C = DS_C;

// ── Tab switching ─────────────────────────────────────────────────────────────
export function switchConceptTab(phase, el) {
  document.querySelectorAll('.concept-tab').forEach(t => t.classList.remove('active'));
  el?.classList.add('active');
  document.querySelectorAll('.concept-panel').forEach(p => p.classList.add('hidden'));
  const panel = document.getElementById('cp-' + phase);
  if (panel) panel.classList.remove('hidden');
}

// ── Main loader ───────────────────────────────────────────────────────────────
export async function loadConcepts() {
  const statusEl = document.getElementById('concepts-status');
  if (statusEl) statusEl.innerHTML = '<span class="spinner"></span>Loading ASML…';

  const [perfRes, dataRes, dsRes, progRes, histRes, stepRes, btdRes, shapRes, metricsRes, sigRes] = await Promise.allSettled([
    api('/api/v1/performance-summary'),
    api('/api/v1/data-understanding?instrument_id=ASML'),
    api('/api/experience/ds/?instrument=ASML'),
    api('/api/v1/training-progress').catch(() => []),
    api('/api/v1/experience/rita/training-history?instrument=ASML'),
    api('/api/experience/ops/step-log').catch(() => []),
    api('/api/v1/experience/rita/backtest-daily?instrument=ASML').catch(() => null),
    api('/api/v1/shap').catch(() => null),
    api('/api/v1/training-metrics?instrument=ASML').catch(() => []),
    api('/api/v1/market-signals?instrument=ASML&timeframe=daily&periods=0').catch(() => []),
  ]);

  const perf    = perfRes.status    === 'fulfilled' ? perfRes.value    : null;
  const dataUnd = dataRes.status    === 'fulfilled' ? dataRes.value    : null;
  const dsData  = dsRes.status      === 'fulfilled' ? dsRes.value      : null;
  const prog    = progRes.status    === 'fulfilled' && Array.isArray(progRes.value)    ? progRes.value    : [];
  const hist    = histRes.status    === 'fulfilled' && Array.isArray(histRes.value)    ? histRes.value    : [];
  const steps   = stepRes.status    === 'fulfilled' && Array.isArray(stepRes.value)    ? stepRes.value    : [];
  const btd     = btdRes.status     === 'fulfilled' ? btdRes.value     : null;
  const shap    = shapRes.status    === 'fulfilled' ? shapRes.value    : null;
  const metrics = metricsRes.status === 'fulfilled' && Array.isArray(metricsRes.value) ? metricsRes.value : [];
  const sigRows = sigRes.status     === 'fulfilled' && Array.isArray(sigRes.value)     ? sigRes.value     : [];

  if (statusEl) statusEl.textContent = '';

  renderPhase1(perf, btd);
  renderPhase2(dataUnd);
  renderPhase3(dataUnd, dsData, sigRows);
  renderPhase4(prog, shap, hist, metrics);
  renderPhase5(hist, btd);
  renderPhase6(steps, hist);
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function fmt(v, dec = 2) {
  if (v == null || v === '') return '—';
  const n = parseFloat(v);
  return isNaN(n) ? String(v) : n.toFixed(dec);
}

function set(id, v) {
  const e = document.getElementById(id);
  if (e) e.textContent = v;
}

function mkScales(extraX = {}, extraY = {}) {
  return {
    x: { grid: { color: C.grid }, ticks: { font: { family: "'IBM Plex Mono'", size: 9 }, color: C.t3, maxTicksLimit: 10 }, ...extraX },
    y: { grid: { color: C.grid }, ticks: { font: { family: "'IBM Plex Mono'", size: 9 }, color: C.t3 }, ...extraY }
  };
}

const LEG  = { labels: { font: { family: "'IBM Plex Mono'", size: 10 }, color: C.t2 } };
const M9   = { font: { family: "'IBM Plex Mono'", size: 9 } };

// Thin down long timeseries to at most maxPts for rendering performance
function thin(arr, maxPts = 300) {
  if (!arr || arr.length <= maxPts) return arr;
  const step = Math.ceil(arr.length / maxPts);
  return arr.filter((_, i) => i % step === 0);
}

function thinLabeled(labels, ...arrays) {
  const n = labels.length;
  const maxPts = 300;
  if (n <= maxPts) return [labels, ...arrays];
  const step = Math.ceil(n / maxPts);
  const idx = labels.map((_, i) => i).filter(i => i % step === 0);
  return [idx.map(i => labels[i]), ...arrays.map(a => idx.map(i => a[i]))];
}

// ── Phase 1: Business Understanding ──────────────────────────────────────────
function renderPhase1(perf, btd) {
  const p      = perf?.performance || perf || {};
  const sharpe = parseFloat(p.sharpe_ratio ?? p.sharpe ?? 0) || 0;
  const mdd    = Math.abs(parseFloat(p.max_drawdown_pct ?? p.max_drawdown ?? 0)) || 0;
  const ret    = parseFloat(p.portfolio_total_return_pct ?? p.total_return_pct ?? p.total_return ?? 0) || 0;
  const winRt  = parseFloat(p.win_rate_pct ?? p.win_rate ?? 0) || 0;
  const cagr   = parseFloat(p.portfolio_cagr_pct ?? p.cagr_pct ?? p.cagr ?? 0) || 0;

  set('cp1-sharpe-val', fmt(sharpe, 2));
  set('cp1-mdd-val',    fmt(mdd, 1) + '%');
  set('cp1-ret-val',    fmtPctRaw(ret, 1));
  set('cp1-wr-val',     fmtPctRaw(winRt, 1));

  // Chart 1a — Sharpe Ratio vs target ≥ 1.0
  mkChart('cp1-c1', {
    type: 'bar',
    data: {
      labels: ['Achieved', 'Target'],
      datasets: [
        { label: 'Sharpe Ratio', data: [sharpe, 1.0],
          backgroundColor: [sharpe >= 1.0 ? C.buildBg : C.dangerBg, C.dsBg],
          borderColor:     [sharpe >= 1.0 ? C.build   : C.danger,   C.ds],
          borderWidth: 1.5, borderRadius: 4 }
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false },
        annotation: { annotations: {
          goal: { type: 'line', yMin: 1.0, yMax: 1.0, borderColor: C.ds, borderWidth: 1.5, borderDash: [5, 3],
                  label: { content: 'Goal ≥ 1.0', display: true, position: 'end',
                           font: { family: "'IBM Plex Mono'", size: 9 }, backgroundColor: 'rgba(0,0,0,0)', color: C.ds } }
        }}
      },
      scales: { ...mkScales(), y: { ...mkScales().y, min: 0, suggestedMax: Math.max(sharpe, 1.0) * 1.3 } }
    }
  });

  // Chart 1b — Max Drawdown % vs limit ≤ 10%
  mkChart('cp1-c1b', {
    type: 'bar',
    data: {
      labels: ['Achieved', 'Limit'],
      datasets: [
        { label: 'Max Drawdown %', data: [mdd, 10],
          backgroundColor: [mdd <= 10 ? C.buildBg : C.dangerBg, C.dsBg],
          borderColor:     [mdd <= 10 ? C.build   : C.danger,   C.ds],
          borderWidth: 1.5, borderRadius: 4 }
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false },
        annotation: { annotations: {
          limit: { type: 'line', yMin: 10, yMax: 10, borderColor: C.danger, borderWidth: 1.5, borderDash: [5, 3],
                   label: { content: 'Limit ≤ 10%', display: true, position: 'end',
                            font: { family: "'IBM Plex Mono'", size: 9 }, backgroundColor: 'rgba(0,0,0,0)', color: C.danger } }
        }}
      },
      scales: { ...mkScales(), y: { ...mkScales().y, min: 0, suggestedMax: Math.max(mdd, 10) * 1.3,
                ticks: { ...mkScales().y.ticks, callback: v => v + '%' } } }
    }
  });

  // Chart 2 — DDQN vs Buy & Hold cumulative returns
  const days  = Array.isArray(btd) ? btd : (btd?.daily ?? []);
  if (days.length) {
    const labels  = days.map(d => d.date ?? d.Date ?? '');
    const ddqn    = days.map(d => parseFloat(d.strategy_value ?? d.portfolio_value ?? d.cum_return_pct ?? 0) || null);
    const bh      = days.map(d => parseFloat(d.bh_value ?? d.benchmark_value ?? d.bh_cum_return_pct ?? 0) || null);
    const [tl, td, tb] = thinLabeled(labels, ddqn, bh);
    mkChart('cp1-c2', {
      type: 'line',
      data: {
        labels: tl,
        datasets: [
          { label: 'DDQN Strategy', data: td, borderColor: C.build, backgroundColor: C.buildBg, borderWidth: 2, pointRadius: 0, fill: true, tension: 0.2, spanGaps: false },
          { label: 'Buy & Hold',    data: tb, borderColor: C.run,   backgroundColor: 'transparent', borderWidth: 1.5, pointRadius: 0, borderDash: [5, 3], tension: 0.2, spanGaps: false },
        ]
      },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: LEG }, scales: mkScales() }
    });

    // Chart 3 — Rolling 63d Sharpe (RL model decision plot)
    const pv       = days.map(d => parseFloat(d.strategy_value ?? d.portfolio_value ?? 1) || 1);
    const pvRets   = pv.map((v, i) => i === 0 ? 0 : (pv[i - 1] > 0 ? (v - pv[i - 1]) / pv[i - 1] : 0));
    const rollSharpe = pvRets.map((_, i) => {
      if (i < 2) return null;
      const sl = pvRets.slice(Math.max(0, i - 63), i);
      const mn = sl.reduce((a, b) => a + b, 0) / sl.length;
      const sd = Math.sqrt(sl.map(x => (x - mn) ** 2).reduce((a, b) => a + b, 0) / sl.length);
      return sd > 0 ? (mn / sd) * Math.sqrt(252) : null;
    });
    const [tl3, ts3] = thinLabeled(labels, rollSharpe);
    mkChart('cp1-c3', {
      type: 'line',
      data: {
        labels: tl3,
        datasets: [{ label: 'Rolling 63d Sharpe', data: ts3, borderColor: C.ds, backgroundColor: C.dsBg, borderWidth: 1.5, pointRadius: 0, fill: true, tension: 0.2, spanGaps: false }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: LEG },
        scales: {
          ...mkScales(),
          y: { grid: { color: C.grid }, ticks: { font: { family: "'IBM Plex Mono'", size: 9 }, color: C.t3 },
               title: { display: true, text: 'Sharpe Ratio', color: C.ds, font: { size: 9, family: "'IBM Plex Mono'" } } }
        }
      }
    });
  } else {
    _noData('cp1-c2'); _noData('cp1-c3');
  }
}

// ── Phase 2: Data Understanding ───────────────────────────────────────────────
function renderPhase2(dataUnd) {
  const ts = dataUnd?.timeseries;
  const s  = dataUnd?.summary || {};

  set('cp2-rows',  s.rows?.toLocaleString() ?? '—');
  set('cp2-feats', s.features ?? '—');
  set('cp2-from',  s.date_from ?? '—');
  set('cp2-to',    s.date_to   ?? '—');

  if (!ts?.dates?.length) { _noData('cp2-c1'); _noData('cp2-c2'); _noData('cp2-c3'); return; }

  const [tl, tc, tr, tm] = thinLabeled(ts.dates, ts.close, ts.rsi, ts.macd);

  // Chart 1 — Close price
  mkChart('cp2-c1', {
    type: 'line',
    data: {
      labels: tl,
      datasets: [{ label: 'ASML Close (€)', data: tc, borderColor: C.ds, backgroundColor: C.dsBg, borderWidth: 1.5, pointRadius: 0, fill: true, tension: 0.2 }]
    },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: LEG }, scales: mkScales() }
  });

  // Chart 2 — RSI(14) with 70/30 bands
  const rsiAnnotations = {
    ob: { type: 'line', yMin: 70, yMax: 70, borderColor: 'rgba(155,28,28,.5)', borderWidth: 1.5, borderDash: [4, 3],
          label: { content: 'Overbought 70', display: true, position: 'end', font: M9, backgroundColor: 'rgba(155,28,28,.08)', color: C.danger } },
    os: { type: 'line', yMin: 30, yMax: 30, borderColor: 'rgba(0,86,184,.5)', borderWidth: 1.5, borderDash: [4, 3],
          label: { content: 'Oversold 30', display: true, position: 'end', font: M9, backgroundColor: 'rgba(0,86,184,.08)', color: C.run } },
  };
  mkChart('cp2-c2', {
    type: 'line',
    data: {
      labels: tl,
      datasets: [{ label: 'RSI (14)', data: tr, borderColor: C.warn, backgroundColor: 'transparent', borderWidth: 1.5, pointRadius: 0, tension: 0.2 }]
    },
    options: {
      responsive: true, maintainAspectRatio: false, plugins: { legend: LEG, annotation: { annotations: rsiAnnotations } },
      scales: mkScales({}, { min: 0, max: 100 })
    }
  });

  // Chart 3 — MACD line
  mkChart('cp2-c3', {
    type: 'line',
    data: {
      labels: tl,
      datasets: [{ label: 'MACD (12/26)', data: tm, borderColor: C.ds, backgroundColor: 'transparent', borderWidth: 1.5, pointRadius: 0, tension: 0.2 }]
    },
    options: {
      responsive: true, maintainAspectRatio: false, plugins: { legend: LEG },
      scales: mkScales({}, {
        ticks: { font: M9.font, color: C.t3, callback: v => v?.toFixed(2) }
      })
    }
  });
}

// ── Phase 3: Data Preparation ─────────────────────────────────────────────────
function renderPhase3(dataUnd, dsData, sigRows = []) {
  const ts     = dataUnd?.timeseries;
  const split  = dsData?.training_context?.split || {};
  const trainEnd = split.train_end;

  if (ts?.dates) set('cp3-rows', ts.dates.length.toLocaleString());
  set('cp3-train-end', trainEnd ?? '—');
  set('cp3-val-start', split.val_start ?? '—');

  // Charts 4-6 — Engineered feature indicators from market signals
  if (!sigRows.length) { _noData('cp3-c4'); _noData('cp3-c5'); _noData('cp3-c6'); return; }

  const [sDates, sTrend, sAtrPct, sClose, sEma5, sEma13, sEma26, sEma50] = thinLabeled(
    sigRows.map(r => r.date),
    sigRows.map(r => r.trend_score != null ? +parseFloat(r.trend_score).toFixed(3) : null),
    sigRows.map(r => { const a = parseFloat(r.atr_14), c = parseFloat(r.Close); return (!isNaN(a) && !isNaN(c) && c) ? +(a / c * 100).toFixed(3) : null; }),
    sigRows.map(r => r.Close),
    sigRows.map(r => r.ema_5),
    sigRows.map(r => r.ema_13),
    sigRows.map(r => r.ema_26),
    sigRows.map(r => r.ema_50),
  );

  // Chart 4 — Trend Score [-1, +1]
  mkChart('cp3-c4', {
    type: 'line',
    data: {
      labels: sDates,
      datasets: [{ label: 'Trend Score', data: sTrend, borderColor: '#7b3fb8', backgroundColor: 'rgba(107,47,160,0.07)', fill: 'origin', tension: 0.25, pointRadius: 0, borderWidth: 1.5 }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: LEG, annotation: { annotations: {
        zero:  { type: 'line', yMin: 0,    yMax: 0,    borderColor: 'rgba(0,0,0,0.3)',      borderWidth: 1.5 },
        upStr: { type: 'line', yMin: 0.5,  yMax: 0.5,  borderColor: 'rgba(26,107,60,0.6)',  borderWidth: 1, borderDash: [4, 3] },
        dnStr: { type: 'line', yMin: -0.5, yMax: -0.5, borderColor: 'rgba(155,28,28,0.6)',  borderWidth: 1, borderDash: [4, 3] },
      }}},
      scales: mkScales({}, { min: -1, max: 1 })
    }
  });

  // Chart 5 — ATR%
  mkChart('cp3-c5', {
    type: 'line',
    data: {
      labels: sDates,
      datasets: [{ label: 'ATR%', data: sAtrPct, borderColor: C.warn, backgroundColor: 'rgba(146,72,10,0.07)', fill: true, tension: 0.2, pointRadius: 0, borderWidth: 1.5 }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: LEG, annotation: { annotations: {
        hi: { type: 'line', yMin: 1.5, yMax: 1.5, borderColor: 'rgba(155,28,28,0.55)', borderWidth: 1, borderDash: [4, 3] },
        lo: { type: 'line', yMin: 0.8, yMax: 0.8, borderColor: 'rgba(26,107,60,0.45)', borderWidth: 1, borderDash: [4, 3] },
      }}},
      scales: mkScales({}, { ticks: { callback: v => v.toFixed(1) + '%' } })
    }
  });

  // Chart 6 — EMA crossover (compute crosses on full rows, then thin alongside EMA series)
  const crossUpFull = new Array(sigRows.length).fill(null);
  const crossDownFull = new Array(sigRows.length).fill(null);
  for (let i = 1; i < sigRows.length; i++) {
    const p = sigRows[i - 1], c = sigRows[i];
    if (p.ema_5 != null && p.ema_13 != null && c.ema_5 != null && c.ema_13 != null) {
      if (p.ema_5 <= p.ema_13 && c.ema_5 > c.ema_13)      crossUpFull[i]   = (c.ema_5 + c.ema_13) / 2;
      else if (p.ema_5 >= p.ema_13 && c.ema_5 < c.ema_13) crossDownFull[i] = (c.ema_5 + c.ema_13) / 2;
    }
  }
  const [, sCrossUp, sCrossDown] = thinLabeled(sigRows.map(r => r.date), crossUpFull, crossDownFull);
  mkChart('cp3-c6', {
    type: 'line',
    data: {
      labels: sDates,
      datasets: [
        { label: 'Close',    data: sClose,     borderColor: 'rgba(100,181,246,0.7)', backgroundColor: 'transparent', pointRadius: 0, borderWidth: 1.5, borderDash: [3, 3] },
        { label: 'EMA-5',   data: sEma5,      borderColor: '#9C27B0',               backgroundColor: 'transparent', pointRadius: 0, borderWidth: 1.2, borderDash: [2, 2] },
        { label: 'EMA-13',  data: sEma13,     borderColor: C.build,                 backgroundColor: 'transparent', pointRadius: 0, borderWidth: 1.2, borderDash: [4, 2] },
        { label: 'EMA-26',  data: sEma26,     borderColor: 'rgba(0,150,136,0.85)',  backgroundColor: 'transparent', pointRadius: 0, borderWidth: 1.5, borderDash: [4, 3] },
        { label: 'EMA-50',  data: sEma50,     borderColor: C.warn,                  backgroundColor: 'transparent', pointRadius: 0, borderWidth: 1.5, borderDash: [6, 3] },
        { label: '▲ Bull',  data: sCrossUp,   type: 'line', showLine: false, spanGaps: false, pointStyle: 'triangle', pointRadius: 5, rotation: 0,   borderColor: '#1a6b3c', backgroundColor: '#1a6b3c' },
        { label: '▼ Bear',  data: sCrossDown, type: 'line', showLine: false, spanGaps: false, pointStyle: 'triangle', pointRadius: 5, rotation: 180, borderColor: '#9b1c1c', backgroundColor: '#9b1c1c' },
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { ...LEG, position: 'top' } },
      scales: mkScales()
    }
  });
}

// ── Phase 4: Modeling ─────────────────────────────────────────────────────────
function renderPhase4(prog, shap, hist, metrics) {
  // Chart 1 — TD Loss
  // Prefer live progress (during active training); fall back to persisted training_metrics from DB.
  const lossSource = prog.length ? prog : metrics;
  if (!lossSource.length) {
    _noData('cp4-c1');
  } else {
    const labels = lossSource.map((r, i) => r.timestep != null ? String(r.timestep) : String((i + 1) * 1000));
    const loss   = lossSource.map(r => { const v = parseFloat(r.loss ?? r.td_loss ?? r.mean_loss ?? 0); return isNaN(v) || v === 0 ? null : v; });
    const [tl, tLoss] = thinLabeled(labels, loss);
    mkChart('cp4-c1', {
      type: 'line',
      data: {
        labels: tl,
        datasets: [{ label: 'TD Loss', data: tLoss, borderColor: C.danger, backgroundColor: 'transparent', borderWidth: 1.5, pointRadius: 0, spanGaps: false }]
      },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: LEG }, scales: mkScales({}, { title: { display: true, text: 'TD Loss', color: C.t3, ...M9 } }) }
    });
  }

  // Chart 2 — Policy improvement
  // Live reward during active run → persisted metrics reward → training history Sharpe fallback
  const rewardSource = prog.length ? prog : metrics;
  if (rewardSource.length) {
    const labels = rewardSource.map((r, i) => r.timestep != null ? String(r.timestep) : String((i + 1) * 1000));
    const reward = rewardSource.map(r => { const v = parseFloat(r.reward ?? r.ep_rew_mean ?? 0); return isNaN(v) || v === 0 ? null : v; });
    const [tl, tr] = thinLabeled(labels, reward);
    if (tr.some(v => v !== null)) {
      mkChart('cp4-c2', {
        type: 'line',
        data: {
          labels: tl,
          datasets: [{ label: 'Ep. Reward (mean)', data: tr, borderColor: C.build, backgroundColor: C.buildBg, borderWidth: 1.5, pointRadius: 0, fill: true, spanGaps: false }]
        },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: LEG }, scales: mkScales({}, { title: { display: true, text: 'Reward', color: C.t3, ...M9 } }) }
      });
    } else {
      _renderPolicyImprovementChart(hist);
    }
  } else {
    _renderPolicyImprovementChart(hist);
  }

  // Chart 3 — SHAP horizontal bar; API field is "Overall" (capital O)
  const shapRows = Array.isArray(shap) ? shap : (shap?.features ?? shap?.shap_values ?? []);
  if (shapRows.length) {
    const top = [...shapRows]
      .sort((a, b) => Math.abs(parseFloat(b.Overall ?? b.importance ?? b.mean_abs ?? b.value ?? 0))
                    - Math.abs(parseFloat(a.Overall ?? a.importance ?? a.mean_abs ?? a.value ?? 0)))
      .slice(0, 8);
    const fLabels = top.map(r => r.feature ?? r.name ?? String(r));
    const fVals   = top.map(r => Math.abs(parseFloat(r.Overall ?? r.importance ?? r.mean_abs ?? r.value ?? 0)));
    mkChart('cp4-c3', {
      type: 'bar',
      data: {
        labels: fLabels,
        datasets: [{ label: 'SHAP |Overall|', data: fVals, backgroundColor: C.dsBg, borderColor: C.ds, borderWidth: 1.5, borderRadius: 3 }]
      },
      options: {
        indexAxis: 'y',
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: LEG },
        scales: {
          x: { grid: { color: C.grid }, ticks: { ...M9, color: C.t3 }, title: { display: true, text: 'Mean |SHAP|', color: C.t3, ...M9 } },
          y: { grid: { color: C.grid }, ticks: { font: { family: "'IBM Plex Mono'", size: 9 }, color: C.t3 } }
        }
      }
    });
  } else {
    _noData('cp4-c3');
  }
}

function _renderPolicyImprovementChart(hist) {
  if (!hist.length) { _noData('cp4-c2'); return; }
  const labels = hist.map((r, i) => `R${r.round ?? i + 1}`);
  const train  = hist.map(r => r.train_sharpe != null ? parseFloat(r.train_sharpe) : null);
  const val    = hist.map(r => r.val_sharpe   != null ? parseFloat(r.val_sharpe)   : null);
  mkChart('cp4-c2', {
    type: 'line',
    data: {
      labels,
      datasets: [
        { label: 'Train Sharpe',      data: train, borderColor: C.build,  backgroundColor: C.buildBg, borderWidth: 2, pointRadius: 5, fill: true,  spanGaps: false },
        { label: 'Validation Sharpe', data: val,   borderColor: C.run,    backgroundColor: 'transparent', borderWidth: 1.5, pointRadius: 5, borderDash: [4,2], spanGaps: false },
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false, plugins: { legend: LEG },
      scales: mkScales({}, { title: { display: true, text: 'Sharpe Ratio', color: C.t3, ...M9 } })
    }
  });
}

// ── Phase 5: Evaluation ───────────────────────────────────────────────────────
function renderPhase5(hist, btd) {
  if (!hist.length) { _noData('cp5-c1'); _noData('cp5-c2'); } else {
    const best = hist.reduce((b, r) => parseFloat(r.backtest_sharpe ?? 0) > parseFloat(b.backtest_sharpe ?? 0) ? r : b, hist[0]);
    set('cp5-runs',        String(hist.length));
    set('cp5-best-sharpe', fmt(parseFloat(best.backtest_sharpe ?? 0), 2));
    set('cp5-best-mdd',    fmt(Math.abs(parseFloat(best.backtest_mdd_pct ?? 0)), 1) + '%');
    set('cp5-best-ret',    fmtPctRaw(parseFloat(best.backtest_return_pct ?? 0), 1));

    const labels = hist.map((r, i) => r.timestamp?.slice(0, 10) || `Run ${i + 1}`);
    const sharpe = hist.map(r => parseFloat(r.backtest_sharpe ?? 0) || null);
    const mdd    = hist.map(r => Math.abs(parseFloat(r.backtest_mdd_pct ?? 0)) || null);

    // Chart 1 — Sharpe across runs
    mkChart('cp5-c1', {
      type: 'bar',
      data: {
        labels,
        datasets: [{ label: 'Backtest Sharpe', data: sharpe, backgroundColor: C.dsBg, borderColor: C.ds, borderWidth: 1.5, borderRadius: 3 }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: LEG, annotation: { annotations: {
          target: { type: 'line', yMin: 1.0, yMax: 1.0, borderColor: 'rgba(26,107,60,.6)', borderWidth: 2, borderDash: [4, 3],
                    label: { content: 'Target 1.0', display: true, position: 'end', font: M9, backgroundColor: 'rgba(26,107,60,.1)', color: C.build } }
        }}},
        scales: mkScales()
      }
    });

    // Chart 2 — Max DD across runs
    mkChart('cp5-c2', {
      type: 'bar',
      data: {
        labels,
        datasets: [{ label: 'Max Drawdown %', data: mdd, backgroundColor: 'rgba(155,28,28,.15)', borderColor: C.danger, borderWidth: 1.5, borderRadius: 3 }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: LEG, annotation: { annotations: {
          limit: { type: 'line', yMin: 10, yMax: 10, borderColor: 'rgba(155,28,28,.6)', borderWidth: 2, borderDash: [4, 3],
                   label: { content: 'Limit 10%', display: true, position: 'end', font: M9, backgroundColor: 'rgba(155,28,28,.08)', color: C.danger } }
        }}},
        scales: mkScales()
      }
    });
  }

  // Chart 3 — DDQN vs B&H cumulative returns (backtest-daily)
  const days = Array.isArray(btd) ? btd : (btd?.daily ?? []);
  if (days.length) {
    const labels = days.map(d => d.date ?? d.Date ?? '');
    const ddqn   = days.map(d => parseFloat(d.strategy_value ?? d.portfolio_value ?? d.cum_return_pct ?? 0) || null);
    const bh     = days.map(d => parseFloat(d.bh_value ?? d.benchmark_value ?? d.bh_cum_return_pct ?? 0) || null);
    const [tl, td, tb] = thinLabeled(labels, ddqn, bh);
    mkChart('cp5-c3', {
      type: 'line',
      data: {
        labels: tl,
        datasets: [
          { label: 'DDQN Strategy', data: td, borderColor: C.build, backgroundColor: C.buildBg, borderWidth: 2, pointRadius: 0, fill: true, tension: 0.2, spanGaps: false },
          { label: 'Buy & Hold',    data: tb, borderColor: C.run,   backgroundColor: 'transparent', borderWidth: 1.5, pointRadius: 0, borderDash: [5, 3], tension: 0.2, spanGaps: false },
        ]
      },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: LEG }, scales: mkScales() }
    });
  } else {
    _noData('cp5-c3');
  }
}

// ── Phase 6: Deployment ───────────────────────────────────────────────────────
function renderPhase6(steps, hist) {
  // step-log returns the latest pipeline run as 4 synthetic rows
  // field is duration_secs (not duration_s)
  const completed = steps.filter(s => s.status === 'completed' || s.status === 'complete' || s.status === 'ok' || s.status === 'success');
  const failed    = steps.filter(s => s.status !== 'completed' && s.status !== 'complete' && s.status !== 'ok' && s.status !== 'success' && s.status !== 'pending');
  set('cp6-total-steps',  String(steps.length));
  set('cp6-failed-steps', String(failed.length));

  if (!steps.length) { _noData('cp6-c1'); _noData('cp6-c2'); _noData('cp6-c3'); return; }

  const labels  = steps.map(s => (s.step_name || s.name || `Step ${s.step_num ?? ''}`).replace(/_/g, ' '));
  // duration_secs is the correct API field
  const durations = steps.map(s => parseFloat(s.duration_secs ?? s.duration_s ?? 0) || null);
  const passes    = steps.map(s => (s.status === 'completed' || s.status === 'complete' || s.status === 'ok' || s.status === 'success') ? 1 : 0);
  const fails     = steps.map(s => (s.status !== 'completed' && s.status !== 'complete' && s.status !== 'ok' && s.status !== 'success' && s.status !== 'pending') ? 1 : 0);

  // Chart 1 — Step duration for latest pipeline run
  mkChart('cp6-c1', {
    type: 'bar',
    data: {
      labels,
      datasets: [{ label: 'Duration (s)', data: durations, backgroundColor: C.dsBg, borderColor: C.ds, borderWidth: 1.5, borderRadius: 3 }]
    },
    options: {
      responsive: true, maintainAspectRatio: false, plugins: { legend: LEG },
      scales: { x: { grid: { color: C.grid }, ticks: { ...M9, color: C.t3 } }, y: { grid: { color: C.grid }, ticks: { ...M9, color: C.t3 }, title: { display: true, text: 'seconds', color: C.t3, ...M9 } } }
    }
  });

  // Chart 2 — Pass vs Pending vs Fail per step
  mkChart('cp6-c2', {
    type: 'bar',
    data: {
      labels,
      datasets: [
        { label: 'Pass',    data: passes, backgroundColor: C.buildBg, borderColor: C.build,  borderWidth: 1.5, borderRadius: 3 },
        { label: 'Fail',    data: fails,  backgroundColor: 'rgba(155,28,28,.15)', borderColor: C.danger, borderWidth: 1.5, borderRadius: 3 },
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false, plugins: { legend: LEG },
      scales: {
        x: { grid: { color: C.grid }, ticks: { ...M9, color: C.t3 }, stacked: true },
        y: { grid: { color: C.grid }, ticks: { ...M9, color: C.t3 }, stacked: true, max: 1 }
      }
    }
  });

  // Chart 3 — Backtest return trend across training rounds (deployment impact over time)
  // Training history is the right source — each row is one pipeline deployment
  if (hist.length) {
    const hLabels  = hist.map((r, i) => `R${r.round ?? i + 1}`);
    const btReturn = hist.map(r => r.backtest_return_pct != null ? parseFloat(r.backtest_return_pct) : null);
    const btSharpe = hist.map(r => r.backtest_sharpe   != null ? parseFloat(r.backtest_sharpe)   : null);
    mkChart('cp6-c3', {
      type: 'line',
      data: {
        labels: hLabels,
        datasets: [
          { label: 'Backtest Return %', data: btReturn, borderColor: C.build,  backgroundColor: C.buildBg,  borderWidth: 2, pointRadius: 5, fill: true,  spanGaps: false, yAxisID: 'y' },
          { label: 'Backtest Sharpe',   data: btSharpe, borderColor: C.ds,     backgroundColor: 'transparent', borderWidth: 1.5, pointRadius: 5, borderDash: [4,2], spanGaps: false, yAxisID: 'y1' },
        ]
      },
      options: {
        responsive: true, maintainAspectRatio: false, plugins: { legend: LEG },
        scales: {
          x:  { grid: { color: C.grid }, ticks: { ...M9, color: C.t3 } },
          y:  { position: 'left',  grid: { color: C.grid }, ticks: { ...M9, color: C.t3 }, title: { display: true, text: 'Return %', color: C.t3, ...M9 } },
          y1: { position: 'right', grid: { drawOnChartArea: false }, ticks: { ...M9, color: C.t3 }, title: { display: true, text: 'Sharpe', color: C.t3, ...M9 } },
        }
      }
    });
  } else {
    _noData('cp6-c3');
  }
}

// ── Empty-state placeholder ───────────────────────────────────────────────────
function _noData(canvasId) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = 'rgba(0,0,0,.04)';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = '#8C877A';
  ctx.font = "11px 'IBM Plex Mono', monospace";
  ctx.textAlign = 'center';
  ctx.fillText('No data — run pipeline for ASML first', canvas.width / 2, canvas.height / 2);
}
