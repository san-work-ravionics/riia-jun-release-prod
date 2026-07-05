// ── Invest Game App — CRISP-DM ───────────────────────────────────────────────
// Full 6-phase CRISP-DM methodology — ported from ds/concepts.js for ASML.
import { api } from '../shared/api.js';
import { mkChart, C } from '../shared/charts.js';

const _LEG = { labels: { font: { family: "'IBM Plex Mono'", size: 10 }, color: '#4A4640' } };
const _M9  = { font: { family: "'IBM Plex Mono'", size: 9 } };

function _mkScales(extraX = {}, extraY = {}) {
  return {
    x: { grid: { color: 'rgba(0,0,0,.04)' }, ticks: { font: { family: "'IBM Plex Mono'", size: 9 }, color: '#8C877A', maxTicksLimit: 10 }, ...extraX },
    y: { grid: { color: 'rgba(0,0,0,.04)' }, ticks: { font: { family: "'IBM Plex Mono'", size: 9 }, color: '#8C877A' }, ...extraY }
  };
}

function _num(v) {
  if (v == null || v === '') return null;
  const n = parseFloat(v);
  return isNaN(n) ? null : n;
}

function _set(id, v) {
  const e = document.getElementById(id);
  if (e) e.textContent = v;
}

function _fmt(v, dec = 2) {
  if (v == null || v === '') return '—';
  const n = parseFloat(v);
  return isNaN(n) ? String(v) : n.toFixed(dec);
}

function _fmtPct(v, dec = 1) {
  if (v == null) return '—';
  return parseFloat(v).toFixed(dec) + '%';
}

function _thin(labels, ...arrays) {
  const n = labels.length;
  const maxPts = 300;
  if (n <= maxPts) return [labels, ...arrays];
  const step = Math.ceil(n / maxPts);
  const idx = labels.map((_, i) => i).filter(i => i % step === 0);
  return [idx.map(i => labels[i]), ...arrays.map(a => idx.map(i => a[i]))];
}

export function switchCrispTab(phase, el) {
  document.querySelectorAll('.crisp-tab').forEach(t => t.classList.remove('active'));
  el?.classList.add('active');
  document.querySelectorAll('.crisp-panel').forEach(p => p.classList.add('hidden'));
  const panel = document.getElementById('crisp-' + phase);
  if (panel) panel.classList.remove('hidden');
}

export async function loadCrispDm() {
  const statusEl = document.getElementById('crisp-status');
  if (statusEl) statusEl.innerHTML = 'Loading ASML...';

  try {
    const [perfRes, btdRes, histRes, shapRes, sigRes, dataRes, stepRes, metricsRes] = await Promise.allSettled([
      api('/api/v1/performance-summary'),
      api('/api/v1/experience/rita/backtest-daily?instrument=ASML'),
      api('/api/v1/experience/rita/training-history?instrument=ASML'),
      api('/api/v1/shap'),
      api('/api/v1/market-signals?instrument=ASML&timeframe=daily&periods=0'),
      api('/api/v1/data-understanding?instrument_id=ASML'),
      api('/api/experience/ops/step-log').catch(() => []),
      api('/api/v1/training-metrics?instrument=ASML').catch(() => []),
    ]);

    const perf    = perfRes.status    === 'fulfilled' ? perfRes.value    : null;
    const btd     = btdRes.status     === 'fulfilled' ? btdRes.value     : null;
    const hist    = histRes.status    === 'fulfilled' && Array.isArray(histRes.value)    ? histRes.value    : [];
    const shap    = shapRes.status    === 'fulfilled' ? shapRes.value    : null;
    const sigs    = sigRes.status     === 'fulfilled' && Array.isArray(sigRes.value)     ? sigRes.value     : [];
    const dataUnd = dataRes.status    === 'fulfilled' ? dataRes.value    : null;
    const steps   = stepRes.status    === 'fulfilled' && Array.isArray(stepRes.value)    ? stepRes.value    : [];
    const metrics = metricsRes.status === 'fulfilled' && Array.isArray(metricsRes.value) ? metricsRes.value : [];

    if (statusEl) statusEl.textContent = '';

    _renderPhase1(perf, btd);
    _renderPhase2(dataUnd, sigs);
    _renderPhase3(dataUnd, sigs);
    _renderPhase4(shap, hist, metrics);
    _renderPhase5(hist, btd);
    _renderPhase6(steps, hist);
  } catch (e) {
    if (statusEl) statusEl.textContent = 'Failed to load data';
  }
}

// Phase 1 — Business Understanding
function _renderPhase1(perf, btd) {
  const p      = perf?.performance || perf || {};
  const sharpe = parseFloat(p.sharpe_ratio ?? p.sharpe ?? 0) || 0;
  const mdd    = Math.abs(parseFloat(p.max_drawdown_pct ?? p.max_drawdown ?? 0)) || 0;
  const ret    = parseFloat(p.portfolio_total_return_pct ?? p.total_return_pct ?? p.total_return ?? 0) || 0;
  const winRt  = parseFloat(p.win_rate_pct ?? p.win_rate ?? 0) || 0;

  _set('crisp-p1-sharpe', _fmt(sharpe, 2));
  _set('crisp-p1-mdd', _fmt(mdd, 1) + '%');
  _set('crisp-p1-ret', _fmtPct(ret, 1));
  _set('crisp-p1-wr', _fmtPct(winRt, 1));

  // Chart 1a — Sharpe vs target
  mkChart('crisp-p1-c1', {
    type: 'bar',
    data: {
      labels: ['Achieved', 'Target'],
      datasets: [{
        label: 'Sharpe Ratio', data: [sharpe, 1.0],
        backgroundColor: [sharpe >= 1.0 ? 'rgba(26,107,60,.12)' : 'rgba(155,28,28,.12)', 'rgba(0,86,184,.12)'],
        borderColor: [sharpe >= 1.0 ? C.build : C.danger, C.run],
        borderWidth: 1.5, borderRadius: 4
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false },
        annotation: { annotations: {
          goal: { type: 'line', yMin: 1.0, yMax: 1.0, borderColor: C.run, borderWidth: 1.5, borderDash: [5, 3],
                  label: { content: 'Goal ≥ 1.0', display: true, position: 'end',
                           font: _M9.font, backgroundColor: 'rgba(0,0,0,0)', color: C.run } }
        }}
      },
      scales: { ..._mkScales(), y: { ..._mkScales().y, min: 0, suggestedMax: Math.max(sharpe, 1.0) * 1.3 } }
    }
  });

  // Chart 1b — Max DD vs limit
  mkChart('crisp-p1-c1b', {
    type: 'bar',
    data: {
      labels: ['Achieved', 'Limit'],
      datasets: [{
        label: 'Max Drawdown %', data: [mdd, 10],
        backgroundColor: [mdd <= 10 ? 'rgba(26,107,60,.12)' : 'rgba(155,28,28,.12)', 'rgba(0,86,184,.12)'],
        borderColor: [mdd <= 10 ? C.build : C.danger, C.run],
        borderWidth: 1.5, borderRadius: 4
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false },
        annotation: { annotations: {
          limit: { type: 'line', yMin: 10, yMax: 10, borderColor: C.danger, borderWidth: 1.5, borderDash: [5, 3],
                   label: { content: 'Limit ≤ 10%', display: true, position: 'end',
                            font: _M9.font, backgroundColor: 'rgba(0,0,0,0)', color: C.danger } }
        }}
      },
      scales: { ..._mkScales(), y: { ..._mkScales().y, min: 0, suggestedMax: Math.max(mdd, 10) * 1.3,
                ticks: { ..._mkScales().y.ticks, callback: v => v + '%' } } }
    }
  });

  // Chart 2 — DDQN vs B&H cumulative returns
  const days = Array.isArray(btd) ? btd : (btd?.daily ?? []);
  if (days.length) {
    const labels = days.map(d => d.date ?? d.Date ?? '');
    const ddqn   = days.map(d => _num(d.strategy_value ?? d.portfolio_value ?? d.cum_return_pct));
    const bh     = days.map(d => _num(d.bh_value ?? d.benchmark_value ?? d.bh_cum_return_pct));
    const [tl, td, tb] = _thin(labels, ddqn, bh);
    mkChart('crisp-p1-c2', {
      type: 'line',
      data: {
        labels: tl,
        datasets: [
          { label: 'DDQN Strategy', data: td, borderColor: C.build, backgroundColor: 'rgba(26,107,60,.10)', borderWidth: 2, pointRadius: 0, fill: true, tension: 0.2, spanGaps: false },
          { label: 'Buy & Hold',    data: tb, borderColor: C.run, backgroundColor: 'transparent', borderWidth: 1.5, pointRadius: 0, borderDash: [5, 3], tension: 0.2, spanGaps: false },
        ]
      },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: _LEG }, scales: _mkScales() }
    });

    // Chart 3 — Rolling 63d Sharpe
    const pv       = days.map(d => parseFloat(d.strategy_value ?? d.portfolio_value ?? 1) || 1);
    const pvRets   = pv.map((v, i) => i === 0 ? 0 : (pv[i - 1] > 0 ? (v - pv[i - 1]) / pv[i - 1] : 0));
    const rollSharpe = pvRets.map((_, i) => {
      if (i < 2) return null;
      const sl = pvRets.slice(Math.max(0, i - 63), i);
      const mn = sl.reduce((a, b) => a + b, 0) / sl.length;
      const sd = Math.sqrt(sl.map(x => (x - mn) ** 2).reduce((a, b) => a + b, 0) / sl.length);
      return sd > 0 ? (mn / sd) * Math.sqrt(252) : null;
    });
    const [tl3, ts3] = _thin(labels, rollSharpe);
    mkChart('crisp-p1-c3', {
      type: 'line',
      data: {
        labels: tl3,
        datasets: [{ label: 'Rolling 63d Sharpe', data: ts3, borderColor: C.build, backgroundColor: 'rgba(26,107,60,.07)', borderWidth: 1.5, pointRadius: 0, fill: true, tension: 0.2, spanGaps: false }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: _LEG },
        scales: {
          ..._mkScales(),
          y: { grid: { color: 'rgba(0,0,0,.04)' }, ticks: { font: { family: "'IBM Plex Mono'", size: 9 }, color: '#8C877A' },
               title: { display: true, text: 'Sharpe Ratio', color: '#8C877A', font: { size: 9, family: "'IBM Plex Mono'" } } }
        }
      }
    });
  } else {
    _noData('crisp-p1-c2'); _noData('crisp-p1-c3');
  }
}

// Phase 2 — Data Understanding
function _renderPhase2(dataUnd, sigs) {
  const ts = dataUnd?.timeseries;
  const s  = dataUnd?.summary || {};

  _set('crisp-p2-rows',  s.rows?.toLocaleString() ?? (sigs.length ? String(sigs.length) : '—'));
  _set('crisp-p2-feats', s.features ?? '11');
  _set('crisp-p2-from',  s.date_from ?? (sigs.length ? sigs[0]?.date?.slice(0, 10) : '—'));
  _set('crisp-p2-to',    s.date_to   ?? (sigs.length ? sigs[sigs.length - 1]?.date?.slice(0, 10) : '—'));

  if (ts?.dates?.length) {
    const [tl, tc, tr, tm] = _thin(ts.dates, ts.close, ts.rsi, ts.macd);

    mkChart('crisp-p2-c1', {
      type: 'line',
      data: { labels: tl, datasets: [{ label: 'ASML Close (€)', data: tc, borderColor: C.run, backgroundColor: 'rgba(0,86,184,.07)', fill: true, tension: 0.2, pointRadius: 0, borderWidth: 1.5 }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: _LEG }, scales: _mkScales() }
    });

    const rsiAnnotations = {
      ob: { type: 'line', yMin: 70, yMax: 70, borderColor: 'rgba(155,28,28,.5)', borderWidth: 1.5, borderDash: [4, 3],
            label: { content: 'Overbought 70', display: true, position: 'end', font: _M9.font, backgroundColor: 'rgba(155,28,28,.08)', color: C.danger } },
      os: { type: 'line', yMin: 30, yMax: 30, borderColor: 'rgba(0,86,184,.5)', borderWidth: 1.5, borderDash: [4, 3],
            label: { content: 'Oversold 30', display: true, position: 'end', font: _M9.font, backgroundColor: 'rgba(0,86,184,.08)', color: C.run } },
    };
    mkChart('crisp-p2-c2', {
      type: 'line',
      data: { labels: tl, datasets: [{ label: 'RSI (14)', data: tr, borderColor: C.warn, backgroundColor: 'transparent', borderWidth: 1.5, pointRadius: 0, tension: 0.2 }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: _LEG, annotation: { annotations: rsiAnnotations } }, scales: _mkScales({}, { min: 0, max: 100 }) }
    });

    mkChart('crisp-p2-c3', {
      type: 'line',
      data: { labels: tl, datasets: [{ label: 'MACD (12/26)', data: tm, borderColor: '#6B2FA0', backgroundColor: 'transparent', borderWidth: 1.5, pointRadius: 0, tension: 0.2 }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: _LEG }, scales: _mkScales({}, { ticks: { ..._M9.font, color: '#8C877A', callback: v => v?.toFixed(2) } }) }
    });
  } else if (sigs.length) {
    const dates = sigs.map(r => r.date ?? '');
    const close = sigs.map(r => _num(r.Close));
    const rsi   = sigs.map(r => _num(r.rsi_14));
    const macd  = sigs.map(r => _num(r.macd));
    const [td, tc] = _thin(dates, close);
    const [td2, tr] = _thin(dates, rsi);
    const [td3, tm] = _thin(dates, macd);

    mkChart('crisp-p2-c1', {
      type: 'line',
      data: { labels: td, datasets: [{ label: 'ASML Close (€)', data: tc, borderColor: C.run, backgroundColor: 'rgba(0,86,184,.07)', fill: true, tension: 0.2, pointRadius: 0, borderWidth: 2 }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: _LEG }, scales: _mkScales() }
    });
    mkChart('crisp-p2-c2', {
      type: 'line',
      data: { labels: td2, datasets: [{ label: 'RSI (14)', data: tr, borderColor: C.warn, backgroundColor: 'transparent', fill: false, tension: 0.2, pointRadius: 0, borderWidth: 2 }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: _LEG }, scales: _mkScales({}, { min: 0, max: 100 }) }
    });
    mkChart('crisp-p2-c3', {
      type: 'line',
      data: { labels: td3, datasets: [{ label: 'MACD (12/26)', data: tm, borderColor: '#6B2FA0', backgroundColor: 'rgba(107,47,160,.07)', fill: true, tension: 0.2, pointRadius: 0, borderWidth: 2 }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: _LEG }, scales: _mkScales() }
    });
  } else {
    _noData('crisp-p2-c1'); _noData('crisp-p2-c2'); _noData('crisp-p2-c3');
  }
}

// Phase 3 — Data Preparation
function _renderPhase3(dataUnd, sigs) {
  const ts    = dataUnd?.timeseries;
  const split = dataUnd?.training_context?.split || {};

  if (ts?.dates) _set('crisp-p3-rows', ts.dates.length.toLocaleString());
  else if (sigs.length) _set('crisp-p3-rows', String(sigs.length));
  _set('crisp-p3-train-end', split.train_end ?? '—');
  _set('crisp-p3-val-start', split.val_start ?? '—');

  if (!sigs.length) { _noData('crisp-p3-c1'); _noData('crisp-p3-c2'); _noData('crisp-p3-c3'); return; }

  const [sDates, sTrend, sAtrPct, sClose, sEma5, sEma13, sEma26, sEma50] = _thin(
    sigs.map(r => r.date),
    sigs.map(r => r.trend_score != null ? +parseFloat(r.trend_score).toFixed(3) : null),
    sigs.map(r => { const a = parseFloat(r.atr_14), c = parseFloat(r.Close); return (!isNaN(a) && !isNaN(c) && c) ? +(a / c * 100).toFixed(3) : null; }),
    sigs.map(r => r.Close),
    sigs.map(r => r.ema_5),
    sigs.map(r => r.ema_13),
    sigs.map(r => r.ema_26),
    sigs.map(r => r.ema_50),
  );

  // Trend Score
  mkChart('crisp-p3-c1', {
    type: 'line',
    data: {
      labels: sDates,
      datasets: [{ label: 'Trend Score', data: sTrend, borderColor: '#7b3fb8', backgroundColor: 'rgba(107,47,160,0.07)', fill: 'origin', tension: 0.25, pointRadius: 0, borderWidth: 1.5 }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: _LEG, annotation: { annotations: {
        zero:  { type: 'line', yMin: 0,    yMax: 0,    borderColor: 'rgba(0,0,0,0.3)',      borderWidth: 1.5 },
        upStr: { type: 'line', yMin: 0.5,  yMax: 0.5,  borderColor: 'rgba(26,107,60,0.6)',  borderWidth: 1, borderDash: [4, 3] },
        dnStr: { type: 'line', yMin: -0.5, yMax: -0.5, borderColor: 'rgba(155,28,28,0.6)',  borderWidth: 1, borderDash: [4, 3] },
      }}},
      scales: _mkScales({}, { min: -1, max: 1 })
    }
  });

  // ATR%
  mkChart('crisp-p3-c2', {
    type: 'line',
    data: {
      labels: sDates,
      datasets: [{ label: 'ATR%', data: sAtrPct, borderColor: C.warn, backgroundColor: 'rgba(146,72,10,0.07)', fill: true, tension: 0.2, pointRadius: 0, borderWidth: 1.5 }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: _LEG, annotation: { annotations: {
        hi: { type: 'line', yMin: 1.5, yMax: 1.5, borderColor: 'rgba(155,28,28,0.55)', borderWidth: 1, borderDash: [4, 3] },
        lo: { type: 'line', yMin: 0.8, yMax: 0.8, borderColor: 'rgba(26,107,60,0.45)', borderWidth: 1, borderDash: [4, 3] },
      }}},
      scales: _mkScales({}, { ticks: { callback: v => v.toFixed(1) + '%' } })
    }
  });

  // EMA Crossovers
  const crossUpFull = new Array(sigs.length).fill(null);
  const crossDownFull = new Array(sigs.length).fill(null);
  for (let i = 1; i < sigs.length; i++) {
    const p = sigs[i - 1], c = sigs[i];
    if (p.ema_5 != null && p.ema_13 != null && c.ema_5 != null && c.ema_13 != null) {
      if (p.ema_5 <= p.ema_13 && c.ema_5 > c.ema_13)      crossUpFull[i]   = (c.ema_5 + c.ema_13) / 2;
      else if (p.ema_5 >= p.ema_13 && c.ema_5 < c.ema_13) crossDownFull[i] = (c.ema_5 + c.ema_13) / 2;
    }
  }
  const [, sCrossUp, sCrossDown] = _thin(sigs.map(r => r.date), crossUpFull, crossDownFull);
  mkChart('crisp-p3-c3', {
    type: 'line',
    data: {
      labels: sDates,
      datasets: [
        { label: 'Close',   data: sClose,     borderColor: 'rgba(100,181,246,0.7)', backgroundColor: 'transparent', pointRadius: 0, borderWidth: 1.5, borderDash: [3, 3] },
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
      plugins: { legend: { ..._LEG, position: 'top' } },
      scales: _mkScales()
    }
  });
}

// Phase 4 — Modeling
function _renderPhase4(shap, hist, metrics) {
  // TD Loss — prefer training_metrics, fall back to empty
  if (!metrics.length) {
    _noData('crisp-p4-c1');
  } else {
    const labels = metrics.map((r, i) => r.timestep != null ? String(r.timestep) : String((i + 1) * 1000));
    const loss   = metrics.map(r => { const v = parseFloat(r.loss ?? r.td_loss ?? r.mean_loss ?? 0); return isNaN(v) || v === 0 ? null : v; });
    const [tl, tLoss] = _thin(labels, loss);
    mkChart('crisp-p4-c1', {
      type: 'line',
      data: { labels: tl, datasets: [{ label: 'TD Loss', data: tLoss, borderColor: C.danger, backgroundColor: 'transparent', borderWidth: 1.5, pointRadius: 0, spanGaps: false }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: _LEG }, scales: _mkScales({}, { title: { display: true, text: 'TD Loss', color: '#8C877A', ..._M9 } }) }
    });
  }

  // Policy improvement — reward from metrics, else Sharpe from training history
  if (metrics.length) {
    const labels = metrics.map((r, i) => r.timestep != null ? String(r.timestep) : String((i + 1) * 1000));
    const reward = metrics.map(r => { const v = parseFloat(r.reward ?? r.ep_rew_mean ?? 0); return isNaN(v) || v === 0 ? null : v; });
    const [tl, tr] = _thin(labels, reward);
    if (tr.some(v => v !== null)) {
      mkChart('crisp-p4-c2', {
        type: 'line',
        data: { labels: tl, datasets: [{ label: 'Ep. Reward (mean)', data: tr, borderColor: C.build, backgroundColor: 'rgba(26,107,60,.10)', borderWidth: 1.5, pointRadius: 0, fill: true, spanGaps: false }] },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: _LEG }, scales: _mkScales({}, { title: { display: true, text: 'Reward', color: '#8C877A', ..._M9 } }) }
      });
    } else {
      _renderPolicyFromHistory(hist);
    }
  } else {
    _renderPolicyFromHistory(hist);
  }

  // SHAP
  const shapRows = Array.isArray(shap) ? shap : (shap?.features ?? shap?.shap_values ?? []);
  if (shapRows.length) {
    const top = [...shapRows]
      .sort((a, b) => Math.abs(parseFloat(b.Overall ?? b.importance ?? b.mean_abs ?? b.value ?? 0))
                    - Math.abs(parseFloat(a.Overall ?? a.importance ?? a.mean_abs ?? a.value ?? 0)))
      .slice(0, 8);
    const fLabels = top.map(r => r.feature ?? r.name ?? String(r));
    const fVals   = top.map(r => Math.abs(parseFloat(r.Overall ?? r.importance ?? r.mean_abs ?? r.value ?? 0)));
    mkChart('crisp-p4-c3', {
      type: 'bar',
      data: { labels: fLabels, datasets: [{ label: 'SHAP |Overall|', data: fVals, backgroundColor: 'rgba(0,86,184,.12)', borderColor: C.run, borderWidth: 1.5, borderRadius: 3 }] },
      options: {
        indexAxis: 'y', responsive: true, maintainAspectRatio: false,
        plugins: { legend: _LEG },
        scales: {
          x: { grid: { color: 'rgba(0,0,0,.04)' }, ticks: { ..._M9, color: '#8C877A' }, title: { display: true, text: 'Mean |SHAP|', color: '#8C877A', ..._M9 } },
          y: { grid: { color: 'rgba(0,0,0,.04)' }, ticks: { font: { family: "'IBM Plex Mono'", size: 9 }, color: '#8C877A' } }
        }
      }
    });
  } else {
    _noData('crisp-p4-c3');
  }
}

function _renderPolicyFromHistory(hist) {
  if (!hist.length) { _noData('crisp-p4-c2'); return; }
  const labels = hist.map((r, i) => `R${r.round ?? i + 1}`);
  const train  = hist.map(r => r.train_sharpe != null ? parseFloat(r.train_sharpe) : null);
  const val    = hist.map(r => r.val_sharpe   != null ? parseFloat(r.val_sharpe)   : null);
  mkChart('crisp-p4-c2', {
    type: 'line',
    data: {
      labels,
      datasets: [
        { label: 'Train Sharpe',      data: train, borderColor: C.build,  backgroundColor: 'rgba(26,107,60,.10)', borderWidth: 2, pointRadius: 5, fill: true, spanGaps: false },
        { label: 'Validation Sharpe', data: val,   borderColor: C.run,    backgroundColor: 'transparent', borderWidth: 1.5, pointRadius: 5, borderDash: [4,2], spanGaps: false },
      ]
    },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: _LEG }, scales: _mkScales({}, { title: { display: true, text: 'Sharpe Ratio', color: '#8C877A', ..._M9 } }) }
  });
}

// Phase 5 — Evaluation
function _renderPhase5(hist, btd) {
  if (!hist.length) { _noData('crisp-p5-c1'); _noData('crisp-p5-c2'); } else {
    const best = hist.reduce((b, r) => parseFloat(r.backtest_sharpe ?? 0) > parseFloat(b.backtest_sharpe ?? 0) ? r : b, hist[0]);
    _set('crisp-p5-runs',        String(hist.length));
    _set('crisp-p5-best-sharpe', _fmt(parseFloat(best.backtest_sharpe ?? 0), 2));
    _set('crisp-p5-best-mdd',    _fmt(Math.abs(parseFloat(best.backtest_mdd_pct ?? 0)), 1) + '%');
    _set('crisp-p5-best-ret',    _fmtPct(parseFloat(best.backtest_return_pct ?? 0), 1));

    const labels = hist.map((r, i) => r.timestamp?.slice(0, 10) || `Run ${i + 1}`);
    const sharpe = hist.map(r => parseFloat(r.backtest_sharpe ?? 0) || null);
    const mdd    = hist.map(r => Math.abs(parseFloat(r.backtest_mdd_pct ?? 0)) || null);

    mkChart('crisp-p5-c1', {
      type: 'bar',
      data: { labels, datasets: [{ label: 'Backtest Sharpe', data: sharpe, backgroundColor: 'rgba(0,86,184,.12)', borderColor: C.run, borderWidth: 1.5, borderRadius: 3 }] },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: _LEG, annotation: { annotations: {
          target: { type: 'line', yMin: 1.0, yMax: 1.0, borderColor: 'rgba(26,107,60,.6)', borderWidth: 2, borderDash: [4, 3],
                    label: { content: 'Target 1.0', display: true, position: 'end', font: _M9.font, backgroundColor: 'rgba(26,107,60,.1)', color: C.build } }
        }}},
        scales: _mkScales()
      }
    });

    mkChart('crisp-p5-c2', {
      type: 'bar',
      data: { labels, datasets: [{ label: 'Max Drawdown %', data: mdd, backgroundColor: 'rgba(155,28,28,.15)', borderColor: C.danger, borderWidth: 1.5, borderRadius: 3 }] },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: _LEG, annotation: { annotations: {
          limit: { type: 'line', yMin: 10, yMax: 10, borderColor: 'rgba(155,28,28,.6)', borderWidth: 2, borderDash: [4, 3],
                   label: { content: 'Limit 10%', display: true, position: 'end', font: _M9.font, backgroundColor: 'rgba(155,28,28,.08)', color: C.danger } }
        }}},
        scales: _mkScales()
      }
    });
  }

  // DDQN vs B&H cumulative returns
  const days = Array.isArray(btd) ? btd : (btd?.daily ?? []);
  if (days.length) {
    const labels = days.map(d => d.date ?? d.Date ?? '');
    const ddqn   = days.map(d => _num(d.strategy_value ?? d.portfolio_value ?? d.cum_return_pct));
    const bh     = days.map(d => _num(d.bh_value ?? d.benchmark_value ?? d.bh_cum_return_pct));
    const [tl, td, tb] = _thin(labels, ddqn, bh);
    mkChart('crisp-p5-c3', {
      type: 'line',
      data: {
        labels: tl,
        datasets: [
          { label: 'DDQN Strategy', data: td, borderColor: C.build, backgroundColor: 'rgba(26,107,60,.10)', borderWidth: 2, pointRadius: 0, fill: true, tension: 0.2, spanGaps: false },
          { label: 'Buy & Hold',    data: tb, borderColor: C.run, backgroundColor: 'transparent', borderWidth: 1.5, pointRadius: 0, borderDash: [5, 3], tension: 0.2, spanGaps: false },
        ]
      },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: _LEG }, scales: _mkScales() }
    });
  } else {
    _noData('crisp-p5-c3');
  }
}

// Phase 6 — Deployment
function _renderPhase6(steps, hist) {
  const completed = steps.filter(s => s.status === 'completed' || s.status === 'complete' || s.status === 'ok' || s.status === 'success');
  const failed    = steps.filter(s => s.status !== 'completed' && s.status !== 'complete' && s.status !== 'ok' && s.status !== 'success' && s.status !== 'pending');
  _set('crisp-p6-total-steps', String(steps.length));
  _set('crisp-p6-failed-steps', String(failed.length));

  if (!steps.length) { _noData('crisp-p6-c1'); _noData('crisp-p6-c2'); _noData('crisp-p6-c3'); return; }

  const labels    = steps.map(s => (s.step_name || s.name || `Step ${s.step_num ?? ''}`).replace(/_/g, ' '));
  const durations = steps.map(s => parseFloat(s.duration_secs ?? s.duration_s ?? 0) || null);
  const passes    = steps.map(s => (s.status === 'completed' || s.status === 'complete' || s.status === 'ok' || s.status === 'success') ? 1 : 0);
  const fails     = steps.map(s => (s.status !== 'completed' && s.status !== 'complete' && s.status !== 'ok' && s.status !== 'success' && s.status !== 'pending') ? 1 : 0);

  mkChart('crisp-p6-c1', {
    type: 'bar',
    data: { labels, datasets: [{ label: 'Duration (s)', data: durations, backgroundColor: 'rgba(0,86,184,.12)', borderColor: C.run, borderWidth: 1.5, borderRadius: 3 }] },
    options: {
      responsive: true, maintainAspectRatio: false, plugins: { legend: _LEG },
      scales: { x: { grid: { color: 'rgba(0,0,0,.04)' }, ticks: { ..._M9, color: '#8C877A' } }, y: { grid: { color: 'rgba(0,0,0,.04)' }, ticks: { ..._M9, color: '#8C877A' }, title: { display: true, text: 'seconds', color: '#8C877A', ..._M9 } } }
    }
  });

  mkChart('crisp-p6-c2', {
    type: 'bar',
    data: {
      labels,
      datasets: [
        { label: 'Pass', data: passes, backgroundColor: 'rgba(26,107,60,.12)', borderColor: C.build, borderWidth: 1.5, borderRadius: 3 },
        { label: 'Fail', data: fails,  backgroundColor: 'rgba(155,28,28,.15)', borderColor: C.danger, borderWidth: 1.5, borderRadius: 3 },
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false, plugins: { legend: _LEG },
      scales: {
        x: { grid: { color: 'rgba(0,0,0,.04)' }, ticks: { ..._M9, color: '#8C877A' }, stacked: true },
        y: { grid: { color: 'rgba(0,0,0,.04)' }, ticks: { ..._M9, color: '#8C877A' }, stacked: true, max: 1 }
      }
    }
  });

  if (hist.length) {
    const hLabels  = hist.map((r, i) => `R${r.round ?? i + 1}`);
    const btReturn = hist.map(r => r.backtest_return_pct != null ? parseFloat(r.backtest_return_pct) : null);
    const btSharpe = hist.map(r => r.backtest_sharpe     != null ? parseFloat(r.backtest_sharpe)     : null);
    mkChart('crisp-p6-c3', {
      type: 'line',
      data: {
        labels: hLabels,
        datasets: [
          { label: 'Backtest Return %', data: btReturn, borderColor: C.build, backgroundColor: 'rgba(26,107,60,.10)', borderWidth: 2, pointRadius: 5, fill: true, spanGaps: false, yAxisID: 'y' },
          { label: 'Backtest Sharpe',   data: btSharpe, borderColor: C.run,   backgroundColor: 'transparent', borderWidth: 1.5, pointRadius: 5, borderDash: [4,2], spanGaps: false, yAxisID: 'y1' },
        ]
      },
      options: {
        responsive: true, maintainAspectRatio: false, plugins: { legend: _LEG },
        scales: {
          x:  { grid: { color: 'rgba(0,0,0,.04)' }, ticks: { ..._M9, color: '#8C877A' } },
          y:  { position: 'left',  grid: { color: 'rgba(0,0,0,.04)' }, ticks: { ..._M9, color: '#8C877A' }, title: { display: true, text: 'Return %', color: '#8C877A', ..._M9 } },
          y1: { position: 'right', grid: { drawOnChartArea: false }, ticks: { ..._M9, color: '#8C877A' }, title: { display: true, text: 'Sharpe', color: '#8C877A', ..._M9 } },
        }
      }
    });
  } else {
    _noData('crisp-p6-c3');
  }
}

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
  ctx.fillText('No data — run pipeline for ASML first', canvas.width / 2, canvas.height / 2);
}
