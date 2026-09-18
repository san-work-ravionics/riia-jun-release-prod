// ── FnO Experiment — Nifty Options Strangle Backtest ──────────────────────────
// Calls fno-margin-fetch middleware: /api/experiment/backtest
// Summary panel + scrollable daily entry/exit table

import { apiFetch, kiteFetch } from './api.js';
import { mkChart } from '../shared/charts.js';

const _fmtRs = v => v != null ? '₹' + Math.abs(v).toLocaleString('en-IN', { maximumFractionDigits: 0 }) : '—';
const _fmtPct = v => v != null ? (v >= 0 ? '+' : '') + v.toFixed(1) + '%' : '—';
const _fmtNum = v => v != null ? v.toLocaleString('en-IN', { maximumFractionDigits: 0 }) : '—';

function _setEl(id, html) {
  const el = document.getElementById(id);
  if (el) el.innerHTML = html;
}

function _pnlColor(v) {
  return v >= 0 ? '#16a34a' : '#dc2626';
}

function _exitBadge(t) {
  const colors = {
    target: { bg: 'rgba(22,163,74,.1)', fg: '#16a34a', label: 'TARGET' },
    sl:     { bg: 'rgba(220,38,38,.1)', fg: '#dc2626', label: 'SL' },
    time:   { bg: 'rgba(100,116,139,.1)', fg: '#64748b', label: '3PM' },
  };
  const c = colors[t] || colors.time;
  return `<span style="background:${c.bg};color:${c.fg};padding:2px 6px;border-radius:100px;font-size:10px;font-weight:700">${c.label}</span>`;
}

function _renderChart(entries) {
  if (!entries.length) return;

  const labels = entries.map(e => e.date.slice(5));
  const data = entries.map(e => e.cum_pnl);

  mkChart('exp-cum-chart', {
    type: 'line',
    data: {
      labels,
      datasets: [{
        label: 'Cumulative P&L',
        data,
        borderColor: data[data.length - 1] >= 0 ? '#16a34a' : '#dc2626',
        backgroundColor: (data[data.length - 1] >= 0 ? 'rgba(22,163,74,' : 'rgba(220,38,38,') + '0.08)',
        fill: true,
        tension: 0.3,
        pointRadius: 0,
        borderWidth: 2,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { maxTicksLimit: 12, font: { size: 10 } }, grid: { display: false } },
        y: { ticks: { font: { size: 10 }, callback: v => '₹' + (v / 1000).toFixed(0) + 'k' }, grid: { color: 'rgba(0,0,0,.06)' } },
      },
    },
  });
}

function _renderSummary(s) {
  const capital = parseFloat(document.getElementById('exp-capital')?.value) || 15000;
  const returnPct = capital > 0 ? (s.total_pnl / capital) * 100 : 0;
  const finalVal = capital + s.total_pnl;

  _setEl('exp-kpi-capital', `<div class="kpi-val">${_fmtRs(capital)}</div><div class="kpi-sub">starting capital</div>`);
  _setEl('exp-kpi-pnl', `<div class="kpi-val" style="color:${_pnlColor(s.total_pnl)}">${s.total_pnl >= 0 ? '+' : '-'}${_fmtRs(s.total_pnl)}</div><div class="kpi-sub">total P&L</div>`);
  _setEl('exp-kpi-final', `<div class="kpi-val" style="color:${_pnlColor(s.total_pnl)}">${_fmtRs(finalVal)}</div><div class="kpi-sub">final value</div>`);
  _setEl('exp-kpi-return', `<div class="kpi-val" style="color:${_pnlColor(returnPct)}">${_fmtPct(returnPct)}</div><div class="kpi-sub">return on capital</div>`);
  _setEl('exp-kpi-winrate', `<div class="kpi-val" style="color:${s.win_rate_pct >= 50 ? '#16a34a' : '#dc2626'}">${s.win_rate_pct}%</div><div class="kpi-sub">${s.wins}W / ${s.losses}L</div>`);
  _setEl('exp-kpi-trades', `<div class="kpi-val">${s.total_trades}</div><div class="kpi-sub">total trades</div>`);
  _setEl('exp-kpi-avg', `<div class="kpi-val" style="color:${_pnlColor(s.avg_pnl)}">${_fmtRs(s.avg_pnl)}</div><div class="kpi-sub">avg per trade</div>`);
  _setEl('exp-kpi-target', `<div class="kpi-val" style="color:#16a34a">${s.target_hits}</div><div class="kpi-sub">target hits</div>`);
  _setEl('exp-kpi-sl', `<div class="kpi-val" style="color:#dc2626">${s.sl_hits}</div><div class="kpi-sub">stop-loss hits</div>`);
}

function _renderTable(entries) {
  const tbody = document.getElementById('exp-table-body');
  if (!tbody) return;

  tbody.innerHTML = entries.map(e => `
    <tr>
      <td>${e.date}</td>
      <td>${_fmtNum(e.nifty_open)}</td>
      <td>${e.call_strike} <span style="color:var(--t3)">@${e.call_premium}</span></td>
      <td>${e.put_strike} <span style="color:var(--t3)">@${e.put_premium}</span></td>
      <td>${e.call_lots}C / ${e.put_lots}P</td>
      <td>${e.iv_pct}%</td>
      <td>${_fmtRs(e.entry_cost)}</td>
      <td>${_fmtRs(e.exit_value)}</td>
      <td style="color:${_pnlColor(e.day_pnl)};font-weight:600">${e.day_pnl >= 0 ? '+' : '-'}${_fmtRs(e.day_pnl)}</td>
      <td style="color:${_pnlColor(e.cum_pnl)};font-weight:600">${e.cum_pnl >= 0 ? '+' : '-'}${_fmtRs(e.cum_pnl)}</td>
      <td>${_exitBadge(e.exit_type)}</td>
    </tr>
  `).join('');
}

export async function loadExperiment() {
  const target = document.getElementById('exp-target')?.value || 15;
  const sl = document.getElementById('exp-sl')?.value || 5;

  _setEl('exp-loading', 'Loading backtest...');
  _setEl('exp-error', '');
  const errEl = document.getElementById('exp-error');
  if (errEl) errEl.style.display = 'none';

  const data = await apiFetch(`/api/experience/fno/experiment-backtest?target_pct=${target}&sl_pct=${sl}`);
  _setEl('exp-loading', '');

  if (!data) {
    if (errEl) { errEl.textContent = 'Backtest endpoint unreachable'; errEl.style.display = 'block'; }
    return;
  }
  if (data.error) {
    if (errEl) { errEl.textContent = data.error; errEl.style.display = 'block'; }
    return;
  }

  _renderSummary(data.summary);
  _renderTable(data.entries);
  _renderChart(data.entries);
}

export async function fetchExpData() {
  _setEl('exp-fetch-status', 'Fetching from Kite API...');
  const data = await kiteFetch('/api/experiment/fetch-data', { method: 'POST' });
  if (!data) {
    _setEl('exp-fetch-status', '✗ Cannot reach Kite middleware');
    return;
  }
  if (data.success) {
    _setEl('exp-fetch-status', `✓ ${data.rows} trading days fetched`);
    loadExperiment();
  } else {
    _setEl('exp-fetch-status', `✗ ${data.error}`);
  }
}
