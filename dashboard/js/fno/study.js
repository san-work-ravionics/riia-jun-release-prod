// ── FnO Study — Rolling Index Futures Backtest (BANKNIFTY + NIFTY) ───────────
// Fetches /api/v1/experience/fno/study and renders per-instrument:
// 1. KPI strip (6 tiles): total P&L, RITA protected, avg, downside, probability, breaches
// 2. Quarterly risk summary table with VaR vs actual + breach flag
// 3. Cumulative P&L chart
// 4. Contracts detail table with SAFE/BREACHED badges

import { apiFetch } from './api.js';
import { mkChart, C } from '../shared/charts.js';

const _fmtPts = v => v != null ? v.toLocaleString('en-IN', { maximumFractionDigits: 0 }) : '—';
const _fmtPct = v => v != null ? (v >= 0 ? '+' : '') + v.toFixed(1) + '%' : '—';

const _charts = {};

function _setEl(id, html) {
  const el = document.getElementById(id);
  if (el) el.innerHTML = html;
}

function _renderKpis(study) {
  const s = study.instrument;
  const closed = study.contracts.filter(c => c.status === 'closed');
  const open = study.contracts.filter(c => c.status === 'open');
  const avgPnl = closed.length > 0 ? study.total_pnl / closed.length : 0;
  const breaches = study.quarters.filter(q => q.var_breached === true).length;
  const totalQ = study.quarters.length;

  _setEl(`study-kpi-pnl-${s}`, `<div class="kpi-val" style="color:${study.total_pnl >= 0 ? '#16a34a' : '#dc2626'}">${_fmtPts(study.total_pnl)} pts</div><div class="kpi-sub">total P&L (${closed.length} closed + ${open.length} open)</div>`);

  const ritaPct = study.rita_protected_pct;
  const ritaColor = ritaPct != null && ritaPct > 0 ? '#16a34a' : '#64748b';
  _setEl(`study-kpi-protected-${s}`, `<div class="kpi-val" style="color:${ritaColor}">${ritaPct != null ? ritaPct.toFixed(1) + '%' : '—'}</div><div class="kpi-sub">downside absorbed by hedge</div>`);

  _setEl(`study-kpi-avg-${s}`, `<div class="kpi-val" style="color:${avgPnl >= 0 ? '#16a34a' : '#dc2626'}">${_fmtPts(avgPnl)} pts</div><div class="kpi-sub">avg P&L per contract</div>`);

  const qVar = study.quarterly_var_pct;
  const qLabel = study.quarter_label || '';
  _setEl(`study-kpi-downside-${s}`, `<div class="kpi-val" style="color:#dc2626">${qVar != null ? '−' + qVar.toFixed(1) + '%' : '—'}</div><div class="kpi-sub">Qtr Downside · ${qLabel}</div>`);

  const bProb = study.hist_breach_prob_pct;
  const probColor = bProb != null ? (bProb > 10 ? '#dc2626' : bProb > 5 ? '#d97706' : '#16a34a') : '#16a34a';
  _setEl(`study-kpi-probability-${s}`, `<div class="kpi-val" style="color:${probColor}">${bProb != null ? bProb.toFixed(1) + '%' : '—'}</div><div class="kpi-sub">Hist. Probability · ${qLabel}</div>`);

  _setEl(`study-kpi-breaches-${s}`, `<div class="kpi-val" style="color:${breaches > 0 ? '#dc2626' : '#16a34a'}">${breaches}/${totalQ}</div><div class="kpi-sub">quarters breached VaR</div>`);
}

function _renderQuarters(study) {
  const tbody = document.getElementById(`study-quarter-body-${study.instrument}`);
  if (!tbody) return;

  tbody.innerHTML = study.quarters.map(q => {
    const retColor = (q.actual_return_pct || 0) >= 0 ? '#16a34a' : '#dc2626';
    const hedgedColor = (q.hedged_return_pct || 0) >= 0 ? '#16a34a' : '#dc2626';
    const breachBadge = q.var_breached === true
      ? '<span style="background:rgba(220,38,38,.1);color:#dc2626;padding:2px 6px;border-radius:100px;font-size:10px;font-weight:700">BREACHED</span>'
      : q.var_breached === false
        ? '<span style="background:rgba(22,163,74,.1);color:#16a34a;padding:2px 6px;border-radius:100px;font-size:10px;font-weight:700">SAFE</span>'
        : '—';
    const probColor = (q.hist_breach_prob_pct || 0) > 10 ? '#dc2626' : (q.hist_breach_prob_pct || 0) > 5 ? '#d97706' : '#16a34a';

    return `<tr style="border-bottom:1px solid rgba(0,0,0,.06)">
      <td style="padding:8px;font-weight:700;font-family:var(--fm)">${q.quarter}</td>
      <td style="padding:8px;font-family:'IBM Plex Mono',monospace;font-size:11px;color:${retColor};font-weight:600">${_fmtPct(q.actual_return_pct)}</td>
      <td style="padding:8px;font-family:'IBM Plex Mono',monospace;font-size:11px;color:${hedgedColor};font-weight:600">${_fmtPct(q.hedged_return_pct)}</td>
      <td style="padding:8px;font-family:'IBM Plex Mono',monospace;font-size:11px;color:#dc2626">${q.quarterly_var_pct != null ? '−' + q.quarterly_var_pct.toFixed(1) + '%' : '—'}</td>
      <td style="padding:8px;font-family:'IBM Plex Mono',monospace;font-size:11px;color:${probColor}">${q.hist_breach_prob_pct != null ? q.hist_breach_prob_pct.toFixed(1) + '%' : '—'}</td>
      <td style="padding:8px;text-align:center">${breachBadge}</td>
    </tr>`;
  }).join('');
}

function _renderContracts(study) {
  const tbody = document.getElementById(`study-contracts-body-${study.instrument}`);
  if (!tbody) return;
  const varPct = study.quarterly_var_pct;

  tbody.innerHTML = study.contracts.map(c => {
    const pnlColor = (c.pnl || 0) >= 0 ? '#16a34a' : '#dc2626';
    const mtmBadge = c.status === 'open'
      ? ' <span style="background:rgba(37,99,235,.1);color:#2563eb;padding:2px 6px;border-radius:100px;font-size:9px;font-weight:700">MTM</span>'
      : '';

    let statusBadge = '—';
    if (c.pnl_pct != null && varPct != null) {
      const breached = c.pnl_pct < -varPct;
      statusBadge = breached
        ? '<span style="background:rgba(220,38,38,.1);color:#dc2626;padding:2px 6px;border-radius:100px;font-size:10px;font-weight:700">BREACHED</span>'
        : '<span style="background:rgba(22,163,74,.1);color:#16a34a;padding:2px 6px;border-radius:100px;font-size:10px;font-weight:700">SAFE</span>';
    }

    return `<tr style="border-bottom:1px solid rgba(0,0,0,.05)">
      <td style="padding:6px 8px;font-weight:600;font-family:var(--fm);font-size:12px">${c.month_label}${mtmBadge}</td>
      <td style="padding:6px 8px;font-family:'IBM Plex Mono',monospace;font-size:11px">${c.buy_date}</td>
      <td style="padding:6px 8px;font-family:'IBM Plex Mono',monospace;font-size:11px">${_fmtPts(c.buy_spot)}</td>
      <td style="padding:6px 8px;font-family:'IBM Plex Mono',monospace;font-size:11px">${_fmtPts(c.buy_price)}</td>
      <td style="padding:6px 8px;font-family:'IBM Plex Mono',monospace;font-size:11px">${c.sell_date || '—'}</td>
      <td style="padding:6px 8px;font-family:'IBM Plex Mono',monospace;font-size:11px;font-weight:700;color:${pnlColor}">${_fmtPts(c.pnl)}</td>
      <td style="padding:6px 8px;font-family:'IBM Plex Mono',monospace;font-size:11px;color:${pnlColor}">${_fmtPct(c.pnl_pct)}</td>
      <td style="padding:6px 8px;text-align:center">${statusBadge}</td>
    </tr>`;
  }).join('');
}

function _renderCumChart(study) {
  const canvasId = `study-cum-chart-${study.instrument}`;
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  if (_charts[canvasId]) { _charts[canvasId].destroy(); _charts[canvasId] = null; }
  if (!study.cumulative_pnl.length) return;

  const labels = study.cumulative_pnl.map(p => p.contract);
  const values = study.cumulative_pnl.map(p => p.pnl);
  const hedgedValues = study.cumulative_pnl.map(p => p.hedged_pnl ?? p.pnl);

  requestAnimationFrame(() => {
    _charts[canvasId] = mkChart(canvasId, {
      type: 'line',
      data: {
        labels,
        datasets: [{
          label: 'Actual P&L',
          data: values,
          borderColor: C.pink,
          borderWidth: 2.5,
          pointRadius: 3,
          pointBackgroundColor: values.map(v => v >= 0 ? C.green : C.red),
          tension: 0.2,
          fill: {
            target: 'origin',
            above: 'rgba(22,163,74,.08)',
            below: 'rgba(220,38,38,.08)',
          },
        }, {
          label: 'Hedged P&L',
          data: hedgedValues,
          borderColor: '#16a34a',
          borderWidth: 2,
          borderDash: [5, 3],
          pointRadius: 2,
          pointBackgroundColor: '#16a34a',
          tension: 0.2,
          fill: false,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { display: true, position: 'top', labels: { boxWidth: 14, font: { family: 'IBM Plex Mono', size: 9 } } },
          tooltip: {
            callbacks: {
              label: ctx => `${ctx.dataset.label}: ${ctx.parsed.y.toLocaleString('en-IN')} pts`,
            }
          },
        },
        scales: {
          x: { grid: { color: 'rgba(0,0,0,.04)' }, ticks: { font: { family: 'IBM Plex Mono', size: 9 } } },
          y: { grid: { color: 'rgba(0,0,0,.04)' }, ticks: { font: { family: 'IBM Plex Mono', size: 9 }, callback: v => v.toLocaleString('en-IN') } },
        },
      },
    });
  });
}

export async function loadStudy() {
  _setEl('study-loading', 'Loading study data…');
  const errEl = document.getElementById('study-error');
  if (errEl) errEl.style.display = 'none';

  try {
    const data = await apiFetch('/api/v1/experience/fno/study');
    _setEl('study-loading', '');

    if (!data || !data.studies || !data.studies.length) {
      _setEl('study-loading', 'No data available for the study period.');
      return;
    }

    for (const study of data.studies) {
      _renderKpis(study);
      _renderQuarters(study);
      _renderContracts(study);
      _renderCumChart(study);
    }
  } catch (e) {
    _setEl('study-loading', '');
    if (errEl) { errEl.style.display = ''; errEl.textContent = 'Failed to load study: ' + e.message; }
    console.error('[Study] load error:', e);
  }
}
