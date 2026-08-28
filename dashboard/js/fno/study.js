// ── FnO Study — Rolling BANKNIFTY Futures Backtest ───────────────────────────
// Fetches /api/v1/experience/fno/study and renders:
// 1. KPI strip: total P&L, contracts, avg P&L, VaR breaches
// 2. Quarterly summary table with VaR vs actual + breach flag
// 3. Contracts table (each monthly roll)
// 4. Cumulative P&L chart

import { apiFetch } from './api.js';
import { mkChart, C } from '../shared/charts.js';

const _fmtPts = v => v != null ? v.toLocaleString('en-IN', { maximumFractionDigits: 0 }) : '—';
const _fmtPct = v => v != null ? (v >= 0 ? '+' : '') + v.toFixed(1) + '%' : '—';

let _cumChart = null;

function _setEl(id, html) {
  const el = document.getElementById(id);
  if (el) el.innerHTML = html;
}

function _renderKpis(data) {
  const closed = data.contracts.filter(c => c.status === 'closed');
  const open = data.contracts.filter(c => c.status === 'open');
  const avgPnl = closed.length > 0 ? data.total_pnl / closed.length : 0;
  const breaches = data.quarters.filter(q => q.var_breached === true).length;
  const totalQ = data.quarters.length;

  _setEl('study-kpi-pnl', `<div class="kpi-val" style="color:${data.total_pnl >= 0 ? '#16a34a' : '#dc2626'}">${_fmtPts(data.total_pnl)} pts</div><div class="kpi-sub">total P&L (${closed.length} closed + ${open.length} open)</div>`);
  _setEl('study-kpi-contracts', `<div class="kpi-val">${data.total_contracts}</div><div class="kpi-sub">contracts traded</div>`);
  _setEl('study-kpi-avg', `<div class="kpi-val" style="color:${avgPnl >= 0 ? '#16a34a' : '#dc2626'}">${_fmtPts(avgPnl)} pts</div><div class="kpi-sub">avg P&L per contract</div>`);
  // Qtr Downside (1σ VaR)
  const qVar = data.quarterly_var_pct;
  const qLabel = data.quarter_label || '';
  _setEl('study-kpi-downside', `<div class="kpi-val" style="color:#dc2626">${qVar != null ? '−' + qVar.toFixed(1) + '%' : '—'}</div><div class="kpi-sub">Qtr Downside · ${qLabel}</div>`);

  // Historical breach probability
  const bProb = data.hist_breach_prob_pct;
  const probColor = bProb != null ? (bProb > 10 ? '#dc2626' : bProb > 5 ? '#d97706' : '#16a34a') : '#16a34a';
  _setEl('study-kpi-probability', `<div class="kpi-val" style="color:${probColor}">${bProb != null ? bProb.toFixed(1) + '%' : '—'}</div><div class="kpi-sub">Hist. Probability · ${qLabel}</div>`);

  _setEl('study-kpi-breaches', `<div class="kpi-val" style="color:${breaches > 0 ? '#dc2626' : '#16a34a'}">${breaches}/${totalQ}</div><div class="kpi-sub">quarters breached VaR</div>`);
}

function _renderQuarters(quarters) {
  const tbody = document.getElementById('study-quarter-body');
  if (!tbody) return;

  tbody.innerHTML = quarters.map(q => {
    const retColor = (q.actual_return_pct || 0) >= 0 ? '#16a34a' : '#dc2626';
    const breachBadge = q.var_breached === true
      ? '<span style="background:rgba(220,38,38,.1);color:#dc2626;padding:2px 8px;border-radius:100px;font-size:11px;font-weight:700">BREACHED</span>'
      : q.var_breached === false
        ? '<span style="background:rgba(22,163,74,.1);color:#16a34a;padding:2px 8px;border-radius:100px;font-size:11px;font-weight:700">SAFE</span>'
        : '—';
    const probColor = (q.hist_breach_prob_pct || 0) > 10 ? '#dc2626' : (q.hist_breach_prob_pct || 0) > 5 ? '#d97706' : '#16a34a';

    return `<tr style="border-bottom:1px solid rgba(0,0,0,.06)">
      <td style="padding:10px 12px;font-weight:700;font-family:var(--fm)">${q.quarter}</td>
      <td style="padding:10px 12px;font-family:'IBM Plex Mono',monospace;font-size:12px">${q.contracts_closed}</td>
      <td style="padding:10px 12px;font-family:'IBM Plex Mono',monospace;font-size:12px;color:${q.total_pnl >= 0 ? '#16a34a' : '#dc2626'};font-weight:600">${_fmtPts(q.total_pnl)}</td>
      <td style="padding:10px 12px;font-family:'IBM Plex Mono',monospace;font-size:12px;color:${retColor};font-weight:600">${_fmtPct(q.actual_return_pct)}</td>
      <td style="padding:10px 12px;font-family:'IBM Plex Mono',monospace;font-size:12px;color:#dc2626">${q.quarterly_var_pct != null ? '−' + q.quarterly_var_pct.toFixed(1) + '%' : '—'}</td>
      <td style="padding:10px 12px;font-family:'IBM Plex Mono',monospace;font-size:12px;color:${probColor}">${q.hist_breach_prob_pct != null ? q.hist_breach_prob_pct.toFixed(1) + '%' : '—'}</td>
      <td style="padding:10px 12px;text-align:center">${breachBadge}</td>
    </tr>`;
  }).join('');
}

function _renderContracts(contracts, varPct) {
  const tbody = document.getElementById('study-contracts-body');
  if (!tbody) return;

  tbody.innerHTML = contracts.map(c => {
    const pnlColor = (c.pnl || 0) >= 0 ? '#16a34a' : '#dc2626';
    const mtmBadge = c.status === 'open'
      ? ' <span style="background:rgba(37,99,235,.1);color:#2563eb;padding:2px 8px;border-radius:100px;font-size:10px;font-weight:700">MTM</span>'
      : '';

    let statusBadge = '—';
    if (c.pnl_pct != null && varPct != null) {
      const breached = c.pnl_pct < -varPct;
      statusBadge = breached
        ? '<span style="background:rgba(220,38,38,.1);color:#dc2626;padding:2px 8px;border-radius:100px;font-size:11px;font-weight:700">BREACHED</span>'
        : '<span style="background:rgba(22,163,74,.1);color:#16a34a;padding:2px 8px;border-radius:100px;font-size:11px;font-weight:700">SAFE</span>';
    }

    return `<tr style="border-bottom:1px solid rgba(0,0,0,.05)">
      <td style="padding:8px 12px;font-weight:600;font-family:var(--fm)">${c.month_label}${mtmBadge}</td>
      <td style="padding:8px 12px;font-family:'IBM Plex Mono',monospace;font-size:12px">${c.buy_date}</td>
      <td style="padding:8px 12px;font-family:'IBM Plex Mono',monospace;font-size:12px">${_fmtPts(c.buy_spot)}</td>
      <td style="padding:8px 12px;font-family:'IBM Plex Mono',monospace;font-size:12px">${_fmtPts(c.buy_price)}</td>
      <td style="padding:8px 12px;font-family:'IBM Plex Mono',monospace;font-size:12px">${c.sell_date || '—'}</td>
      <td style="padding:8px 12px;font-family:'IBM Plex Mono',monospace;font-size:12px">${_fmtPts(c.sell_price)}</td>
      <td style="padding:8px 12px;font-family:'IBM Plex Mono',monospace;font-size:12px;font-weight:700;color:${pnlColor}">${_fmtPts(c.pnl)}</td>
      <td style="padding:8px 12px;font-family:'IBM Plex Mono',monospace;font-size:12px;color:${pnlColor}">${_fmtPct(c.pnl_pct)}</td>
      <td style="padding:8px 12px;text-align:center">${statusBadge}</td>
    </tr>`;
  }).join('');
}

function _renderCumChart(cumulative) {
  const canvas = document.getElementById('study-cum-chart');
  if (!canvas) return;
  if (_cumChart) { _cumChart.destroy(); _cumChart = null; }
  if (!cumulative.length) return;

  const labels = cumulative.map(p => p.contract);
  const values = cumulative.map(p => p.pnl);

  requestAnimationFrame(() => {
    _cumChart = mkChart('study-cum-chart', {
      type: 'line',
      data: {
        labels,
        datasets: [{
          label: 'Cumulative P&L (pts)',
          data: values,
          borderColor: C.pink,
          borderWidth: 2.5,
          pointRadius: 4,
          pointBackgroundColor: values.map(v => v >= 0 ? C.green : C.red),
          tension: 0.2,
          fill: {
            target: 'origin',
            above: 'rgba(22,163,74,.08)',
            below: 'rgba(220,38,38,.08)',
          },
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: ctx => `P&L: ${ctx.parsed.y.toLocaleString('en-IN')} pts`,
            }
          },
        },
        scales: {
          x: { grid: { color: 'rgba(0,0,0,.04)' }, ticks: { font: { family: 'IBM Plex Mono', size: 10 } } },
          y: { grid: { color: 'rgba(0,0,0,.04)' }, ticks: { font: { family: 'IBM Plex Mono', size: 10 }, callback: v => v.toLocaleString('en-IN') } },
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

    if (!data || !data.contracts.length) {
      _setEl('study-loading', 'No BANKNIFTY data available for the study period.');
      return;
    }

    _renderKpis(data);
    _renderQuarters(data.quarters);
    _renderContracts(data.contracts, data.quarterly_var_pct);
    _renderCumChart(data.cumulative_pnl);
  } catch (e) {
    _setEl('study-loading', '');
    if (errEl) { errEl.style.display = ''; errEl.textContent = 'Failed to load study: ' + e.message; }
    console.error('[Study] load error:', e);
  }
}
