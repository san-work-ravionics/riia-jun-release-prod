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

  const [perfRes, dataRes, dsRes, progRes, histRes, stepRes, btdRes, shapRes, metricsRes] = await Promise.allSettled([
    api('/api/v1/performance-summary'),
    api('/api/v1/data-understanding?instrument_id=ASML'),
    api('/api/experience/ds/?instrument=ASML'),
    api('/api/v1/training-progress').catch(() => []),
    api('/api/v1/experience/rita/training-history?instrument=ASML'),
    api('/api/experience/ops/step-log').catch(() => []),
    api('/api/v1/experience/rita/backtest-daily?instrument=ASML').catch(() => null),
    api('/api/v1/shap').catch(() => null),
    api('/api/v1/training-metrics?instrument=ASML').catch(() => []),
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

  if (statusEl) statusEl.textContent = '';

  renderPhase1(perf, btd);
  renderPhase2(dataUnd);
  renderPhase3(dataUnd, dsData);
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

  // Chart 1 — Target vs Achieved grouped bar
  mkChart('cp1-c1', {
    type: 'bar',
    data: {
      labels: ['Sharpe Ratio', 'Win Rate %', 'CAGR %'],
      datasets: [
        { label: 'Target',   data: [1.0,    50,    12],   backgroundColor: C.dsBg,   borderColor: C.ds,    borderWidth: 1.5, borderRadius: 3 },
        { label: 'Achieved', data: [sharpe, winRt, cagr], backgroundColor: C.buildBg, borderColor: C.build, borderWidth: 1.5, borderRadius: 3 },
      ]
    },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: LEG }, scales: mkScales() }
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

    // Chart 3 — Allocation doughnut
    let a0 = 0, a50 = 0, a100 = 0;
    days.forEach(d => {
      const act = parseFloat(d.action ?? d.allocation ?? d.position ?? -1);
      if (act === 0)   a0++;
      else if (act === 1) a50++;
      else if (act === 2) a100++;
      else {
        const pct = parseFloat(d.allocation_pct ?? d.alloc_pct ?? -1);
        if (pct === 0)   a0++;
        else if (pct === 50)  a50++;
        else if (pct === 100) a100++;
      }
    });
    if (a0 + a50 + a100 === 0) { a0 = 1; a50 = 1; a100 = 1; } // fallback placeholder
    mkChart('cp1-c3', {
      type: 'doughnut',
      data: {
        labels: ['Cash (0%)', 'Half (50%)', 'Full (100%)'],
        datasets: [{ data: [a0, a50, a100], backgroundColor: [C.dangerBg, C.dsBg, C.buildBg], borderColor: [C.danger, C.ds, C.build], borderWidth: 2 }]
      },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: LEG } }
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
function renderPhase3(dataUnd, dsData) {
  const ts     = dataUnd?.timeseries;
  const split  = dsData?.training_context?.split || {};
  const trainEnd = split.train_end;

  if (ts?.dates) set('cp3-rows', ts.dates.length.toLocaleString());
  set('cp3-train-end', trainEnd ?? '—');
  set('cp3-val-start', split.val_start ?? '—');

  if (!ts?.dates?.length) { _noData('cp3-c1'); _noData('cp3-c2'); _noData('cp3-c3'); return; }

  let splitIdx = Math.floor(ts.dates.length * 0.8);
  if (trainEnd) {
    for (let i = ts.dates.length - 1; i >= 0; i--) {
      if (ts.dates[i] <= trainEnd) { splitIdx = i; break; }
    }
  }

  const splitLabel = ts.dates[splitIdx];
  const splitAnnotation = splitLabel ? {
    splitLine: {
      type: 'line', xMin: splitLabel, xMax: splitLabel,
      borderColor: 'rgba(155,28,28,.75)', borderWidth: 2, borderDash: [5, 4],
      label: { content: '80/20 Split', display: true, position: 'start', font: M9, backgroundColor: 'rgba(155,28,28,.1)', color: C.danger }
    }
  } : {};

  function splitSeries(arr) {
    const train = arr.map((v, i) => (i <= splitIdx ? v : null));
    const val   = arr.map((v, i) => (i >= splitIdx ? v : null));
    return [train, val];
  }

  const [tl, tClose, tVol, tRsi] = thinLabeled(ts.dates, ts.close, ts.volume ?? [], ts.rsi ?? []);
  // Recompute split after thinning
  const thinSplitIdx = tl.findIndex(d => d >= (trainEnd || ''));
  const splitIdxThin = thinSplitIdx >= 0 ? thinSplitIdx : Math.floor(tl.length * 0.8);

  function splitThin(arr) {
    return [arr.map((v, i) => (i <= splitIdxThin ? v : null)), arr.map((v, i) => (i >= splitIdxThin ? v : null))];
  }

  const [trainClose, valClose] = splitThin(tClose);
  const [trainVol,   valVol  ] = splitThin(tVol);
  const [trainRsi,   valRsi  ] = splitThin(tRsi);

  const trainDs = (label, data, col) => ({ label, data, borderColor: col, backgroundColor: col.replace(')', ',.12)').replace('rgb', 'rgba'), borderWidth: 1.5, pointRadius: 0, fill: true, tension: 0.2, spanGaps: false });
  const valDs   = (label, data, col) => ({ label, data, borderColor: col, backgroundColor: col.replace(')', ',.12)').replace('rgb', 'rgba'), borderWidth: 1.5, pointRadius: 0, fill: true, tension: 0.2, spanGaps: false });

  // Chart 1 — Close price split
  mkChart('cp3-c1', {
    type: 'line',
    data: {
      labels: tl,
      datasets: [
        { label: 'Training (80%)',      data: trainClose, borderColor: C.build,  backgroundColor: C.buildBg,  borderWidth: 1.5, pointRadius: 0, fill: true, tension: 0.2, spanGaps: false },
        { label: 'Val/Backtest (20%)',  data: valClose,   borderColor: C.run,    backgroundColor: C.runBg,    borderWidth: 1.5, pointRadius: 0, fill: true, tension: 0.2, spanGaps: false },
      ]
    },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: LEG, annotation: { annotations: splitAnnotation } }, scales: mkScales() }
  });

  // Chart 2 — Volume split (bar)
  const hasVol = tVol.some(v => v != null && v > 0);
  if (hasVol) {
    mkChart('cp3-c2', {
      type: 'bar',
      data: {
        labels: tl,
        datasets: [
          { label: 'Training (80%)',     data: trainVol, backgroundColor: C.buildBg, borderColor: C.build, borderWidth: 0.5, borderRadius: 1 },
          { label: 'Val/Backtest (20%)', data: valVol,   backgroundColor: C.runBg,   borderColor: C.run,   borderWidth: 0.5, borderRadius: 1 },
        ]
      },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: LEG }, scales: mkScales() }
    });
  } else {
    _noData('cp3-c2');
  }

  // Chart 3 — RSI split with 30/70 bands
  const hasRsi = tRsi.some(v => v != null);
  if (hasRsi) {
    mkChart('cp3-c3', {
      type: 'line',
      data: {
        labels: tl,
        datasets: [
          { label: 'RSI Training',    data: trainRsi, borderColor: C.build, backgroundColor: 'transparent', borderWidth: 1.5, pointRadius: 0, tension: 0.2, spanGaps: false },
          { label: 'RSI Val/BT',      data: valRsi,   borderColor: C.run,   backgroundColor: 'transparent', borderWidth: 1.5, pointRadius: 0, tension: 0.2, spanGaps: false },
        ]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: LEG, annotation: { annotations: {
          ob: { type: 'line', yMin: 70, yMax: 70, borderColor: 'rgba(155,28,28,.4)', borderWidth: 1.5, borderDash: [4, 3] },
          os: { type: 'line', yMin: 30, yMax: 30, borderColor: 'rgba(0,86,184,.4)',  borderWidth: 1.5, borderDash: [4, 3] },
        }}},
        scales: mkScales({}, { min: 0, max: 100 })
      }
    });
  } else {
    _noData('cp3-c3');
  }
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
