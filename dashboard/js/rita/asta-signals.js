// ── ASTA Signals — Double Screen & Triple Screen Analysis ──
import { api } from './api.js';
import { setEl } from './utils.js';
import { mkChart, C } from './charts.js';

function _getInstrument() {
  return (localStorage.getItem('ritaInstrument') || 'NIFTY').toUpperCase();
}

const _SETUP_LABELS = {
  smm_double_screen: 'SMM Double Screen',
  triple_screen:     'GEO PAN Triple Screen',
  swing_db_dt:       'GEO PAN Swing (DB/DT)',
  momentum_bb:       'GEO PAN Momentum BB',
};

const _SETUP_COLORS = {
  smm_double_screen: '#0056B8',
  triple_screen:     '#6B2FA0',
  swing_db_dt:       '#1A6B3C',
  momentum_bb:       '#92480A',
};

function _renderSummary(summary) {
  const el = document.getElementById('asta-summary');
  if (!el) return;

  const { buy_count, sell_count, hold_count, total_rows, signal_rate_pct, confidence_stats, date_range, points_stats } = summary;
  const ps = points_stats || {};
  const totalColor = (ps.total_pts || 0) >= 0 ? 'var(--build)' : 'var(--danger)';
  const buyColor = (ps.buy_pts || 0) >= 0 ? 'var(--build)' : 'var(--danger)';
  const sellColor = (ps.sell_pts || 0) >= 0 ? 'var(--build)' : 'var(--danger)';

  el.innerHTML = `
    <div style="display:grid;grid-template-columns:repeat(9,1fr);gap:10px">
      <div class="kpi kpi-sm">
        <div class="kpi-label">Total Bars</div>
        <div class="kpi-val">${total_rows.toLocaleString()}</div>
        <div class="kpi-sub">${date_range.start} → ${date_range.end}</div>
      </div>
      <div class="kpi kpi-sm">
        <div class="kpi-label">BUY Signals</div>
        <div class="kpi-val" style="color:var(--build)">${buy_count}</div>
        <div class="kpi-sub">${(buy_count/total_rows*100).toFixed(1)}%</div>
      </div>
      <div class="kpi kpi-sm">
        <div class="kpi-label">SELL Signals</div>
        <div class="kpi-val" style="color:var(--danger)">${sell_count}</div>
        <div class="kpi-sub">${(sell_count/total_rows*100).toFixed(1)}%</div>
      </div>
      <div class="kpi kpi-sm">
        <div class="kpi-label">HOLD</div>
        <div class="kpi-val" style="color:var(--t3)">${hold_count}</div>
        <div class="kpi-sub">${(hold_count/total_rows*100).toFixed(1)}%</div>
      </div>
      <div class="kpi kpi-sm">
        <div class="kpi-label">Signal Rate</div>
        <div class="kpi-val">${signal_rate_pct}%</div>
        <div class="kpi-sub">Target: 5–15%</div>
      </div>
      <div class="kpi kpi-sm">
        <div class="kpi-label">Avg Confidence</div>
        <div class="kpi-val">${confidence_stats.mean || '—'}</div>
        <div class="kpi-sub">Win rate: ${ps.win_rate_pct || 0}%</div>
      </div>
      <div class="kpi kpi-sm">
        <div class="kpi-label">▲ BUY Points</div>
        <div class="kpi-val" style="color:${buyColor}">${ps.buy_pts != null ? ps.buy_pts.toLocaleString() : '—'}</div>
        <div class="kpi-sub">${ps.buy_target_count || 0} won · ${ps.buy_stopped_count || 0} stopped</div>
      </div>
      <div class="kpi kpi-sm">
        <div class="kpi-label">▼ SELL Points</div>
        <div class="kpi-val" style="color:${sellColor}">${ps.sell_pts != null ? ps.sell_pts.toLocaleString() : '—'}</div>
        <div class="kpi-sub">${ps.sell_target_count || 0} won · ${ps.sell_stopped_count || 0} stopped</div>
      </div>
      <div class="kpi kpi-sm" style="border-left:3px solid ${totalColor}">
        <div class="kpi-label">Total Points</div>
        <div class="kpi-val" style="color:${totalColor}">${ps.total_pts != null ? (ps.total_pts >= 0 ? '+' : '') + ps.total_pts.toLocaleString() : '—'}</div>
        <div class="kpi-sub">Max hold: ${ps.hold_days || 20} days</div>
      </div>
    </div>
  `;
}

function _renderSetupBreakdown(summary) {
  const el = document.getElementById('asta-setup-breakdown');
  if (!el) return;
  const bd = summary.setup_breakdown || {};
  const total = summary.total_rows || 1;

  const setupCards = Object.entries(bd).map(([key, val]) => {
    const label = _SETUP_LABELS[key] || key;
    const color = _SETUP_COLORS[key] || C.t3;
    const pct = (val.total / total * 100).toFixed(1);
    const buyPct = val.total ? Math.round(val.buy / val.total * 100) : 0;
    return `<div class="kpi kpi-sm" style="border-left:3px solid ${color}">
      <div class="kpi-label">${label}</div>
      <div class="kpi-val">${val.total} <span style="font-size:11px;color:var(--t3);font-weight:400">signals · ${pct}%</span></div>
      <div style="display:flex;gap:16px;margin-top:4px;font-size:12px;font-family:var(--fm)">
        <span style="color:var(--build)">▲ BUY ${val.buy}</span>
        <span style="color:var(--danger)">▼ SELL ${val.sell}</span>
      </div>
      <div style="height:4px;border-radius:2px;background:var(--danger-bg);margin-top:6px;overflow:hidden">
        <div style="height:100%;width:${buyPct}%;background:var(--build);border-radius:2px"></div>
      </div>
    </div>`;
  }).join('');

  el.innerHTML = setupCards || '<span style="color:var(--t3)">No signals</span>';
}

function _renderPriceSignalChart(rows) {
  if (!rows.length) return;

  const dates  = rows.map(r => r.date);
  const closes = rows.map(r => r.Close);
  const n = rows.length;

  const buyPts  = new Array(n).fill(null);
  const sellPts = new Array(n).fill(null);
  for (let i = 0; i < n; i++) {
    if (rows[i].asta_signal === 'BUY')  buyPts[i]  = rows[i].Close;
    if (rows[i].asta_signal === 'SELL') sellPts[i] = rows[i].Close;
  }

  const _xFmt   = v => typeof v === 'string' ? v.slice(5) : v;
  const _xTicks = 12;

  try {
    mkChart('chart-asta-price', {
      type: 'line',
      data: {
        labels: dates,
        datasets: [
          { label: 'Close', data: closes,
            borderColor: 'rgba(100,181,246,0.6)', backgroundColor: 'transparent',
            pointRadius: 0, borderWidth: 1.5, order: 3 },
          { label: 'BUY Signal', data: buyPts, type: 'line', showLine: false, spanGaps: false,
            pointStyle: 'triangle', pointRadius: 5, rotation: 0,
            borderColor: C.build, backgroundColor: C.build,
            pointBorderColor: C.build, pointBackgroundColor: C.build, order: 1 },
          { label: 'SELL Signal', data: sellPts, type: 'line', showLine: false, spanGaps: false,
            pointStyle: 'triangle', pointRadius: 5, rotation: 180,
            borderColor: C.danger, backgroundColor: C.danger,
            pointBorderColor: C.danger, pointBackgroundColor: C.danger, order: 2 },
        ]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { position: 'top', labels: { font: { size: 11 }, boxWidth: 20 } } },
        scales: {
          x: { grid: { display: false }, ticks: { maxTicksLimit: _xTicks, callback: _xFmt, font: { family: C.mono, size: 10 } } },
          y: { grid: { color: 'rgba(0,0,0,.04)' }, ticks: { callback: v => v.toFixed(0), font: { family: C.mono, size: 10 } } }
        }
      }
    });
  } catch (e) { /* chart render failed */ }
}

function _renderConfidenceChart(rows) {
  const active = rows.filter(r => r.asta_signal !== 'HOLD');
  if (!active.length) return;

  const bins = [0, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.01];
  const labels = bins.slice(0, -1).map((b, i) => `${b.toFixed(1)}–${bins[i+1].toFixed(1)}`);
  const counts = new Array(labels.length).fill(0);

  for (const r of active) {
    const c = r.asta_confidence || 0;
    for (let i = 0; i < bins.length - 1; i++) {
      if (c >= bins[i] && c < bins[i+1]) { counts[i]++; break; }
    }
  }

  try {
    mkChart('chart-asta-conf', {
      type: 'bar',
      data: {
        labels,
        datasets: [{
          label: 'Signal Count',
          data: counts,
          backgroundColor: counts.map((_, i) => {
            const t = i / (labels.length - 1);
            return `rgba(${Math.round(26 + (0 - 26) * t)},${Math.round(107 + (86 - 107) * t)},${Math.round(60 + (184 - 60) * t)},0.7)`;
          }),
          borderWidth: 0,
        }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { grid: { display: false }, ticks: { font: { family: C.mono, size: 10 } } },
          y: { grid: { color: 'rgba(0,0,0,.04)' }, ticks: { font: { family: C.mono, size: 10 } } }
        }
      }
    });
  } catch (e) { /* chart render failed */ }
}

function _renderSetupDonut(summary) {
  const bd = summary.setup_breakdown || {};
  const entries = Object.entries(bd);
  if (!entries.length) return;

  try {
    mkChart('chart-asta-setup', {
      type: 'doughnut',
      data: {
        labels: entries.map(([k]) => _SETUP_LABELS[k] || k),
        datasets: [{
          data: entries.map(([, v]) => v.total),
          backgroundColor: entries.map(([k]) => _SETUP_COLORS[k] || C.t3),
          borderWidth: 2,
          borderColor: '#fff',
        }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { position: 'right', labels: { font: { size: 11 }, boxWidth: 14, padding: 10 } },
        },
      }
    });
  } catch (e) { /* chart render failed */ }
}

function _renderStochRsiChart(rows) {
  if (!rows.length) return;
  const dates = rows.map(r => r.date);
  const _xFmt   = v => typeof v === 'string' ? v.slice(5) : v;
  const _xTicks = 12;

  try {
    mkChart('chart-asta-stoch', {
      type: 'line',
      data: {
        labels: dates,
        datasets: [
          { label: 'Stoch %K', data: rows.map(r => r.stoch_k),
            borderColor: C.run, backgroundColor: 'transparent',
            pointRadius: 0, borderWidth: 1.5 },
          { label: 'Stoch %D', data: rows.map(r => r.stoch_d),
            borderColor: C.warn, backgroundColor: 'transparent',
            pointRadius: 0, borderWidth: 1.5, borderDash: [3,2] },
        ]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { position: 'top', labels: { font: { size: 11 }, boxWidth: 20 } },
          annotation: { annotations: {
            ob: { type: 'line', yMin: 80, yMax: 80, borderColor: 'rgba(155,28,28,0.5)', borderWidth: 1, borderDash: [4,3] },
            os: { type: 'line', yMin: 20, yMax: 20, borderColor: 'rgba(26,107,60,0.5)', borderWidth: 1, borderDash: [4,3] },
          }}
        },
        scales: {
          x: { grid: { display: false }, ticks: { maxTicksLimit: _xTicks, callback: _xFmt, font: { family: C.mono, size: 10 } } },
          y: { min: 0, max: 100, grid: { color: 'rgba(0,0,0,.04)' }, ticks: { font: { family: C.mono, size: 10 } } }
        }
      }
    });
  } catch (e) { /* chart render failed */ }
}

const _OUTCOME_BADGE = {
  target:  '<span class="badge pos">Target</span>',
  stopped: '<span class="badge neg">Stopped</span>',
  open:    '<span class="badge neu">Open</span>',
};

function _renderRecentSignals(rows) {
  const tbody = document.getElementById('asta-recent-tbody');
  if (!tbody) return;

  const active = rows.filter(r => r.asta_signal !== 'HOLD').slice(-20).reverse();
  if (!active.length) {
    tbody.innerHTML = '<tr><td colspan="9" style="color:var(--t3)">No signals in range</td></tr>';
    return;
  }

  tbody.innerHTML = active.map(r => {
    const cls = r.asta_signal === 'BUY' ? 'pos' : 'neg';
    const setup = _SETUP_LABELS[r.asta_setup] || r.asta_setup;
    const conf = ((r.asta_confidence || 0) * 100).toFixed(0);
    const sl = r.asta_stop_loss ? r.asta_stop_loss.toFixed(0) : '—';
    const tgt = r.asta_target ? r.asta_target.toFixed(0) : '—';
    const outcome = r._outcome || '';
    const pts = r._realized_pts || 0;
    const ptsStr = outcome ? `${pts >= 0 ? '+' : ''}${pts.toFixed(0)}` : '—';
    const ptsColor = outcome ? (pts >= 0 ? 'color:var(--build)' : 'color:var(--danger)') : '';
    const outBadge = _OUTCOME_BADGE[outcome] || '';
    return `<tr>
      <td style="font-family:var(--fm)">${r.date}</td>
      <td><span class="badge ${cls}">${r.asta_signal}</span></td>
      <td>${setup}</td>
      <td style="font-family:var(--fm)">${r.Close ? r.Close.toFixed(1) : '—'}</td>
      <td style="font-family:var(--fm)">${conf}%</td>
      <td style="font-family:var(--fm)">${sl}</td>
      <td style="font-family:var(--fm)">${tgt}</td>
      <td>${outBadge}</td>
      <td style="font-family:var(--fm);font-weight:600;${ptsColor}">${ptsStr}</td>
    </tr>`;
  }).join('');
}

export async function loadAstaSignals() {
  const inst = _getInstrument();

  let data;
  try {
    data = await api(`/api/v1/experience/rita/asta-signals?instrument=${encodeURIComponent(inst)}&periods=500`);
  } catch (e) {
    setEl('asta-summary', '<span style="color:var(--danger)">Failed to load signal data</span>');
    return;
  }

  if (!data || data.error) {
    setEl('asta-summary', `<span style="color:var(--t3)">No ASTA dataset for ${inst}. Run the labeler pipeline first.</span>`);
    return;
  }

  const { summary, rows } = data;

  _renderSummary(summary);
  _renderSetupBreakdown(summary);
  _renderPriceSignalChart(rows);
  _renderConfidenceChart(rows);
  _renderSetupDonut(summary);
  _renderStochRsiChart(rows);
  _renderRecentSignals(rows);
}
