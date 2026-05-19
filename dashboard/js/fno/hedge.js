// ── Hedge History + Hedge Radar ────────────────────────────────────────────────
import { state } from './state.js';
import { fmt, fmtPnl, pnlClass } from './utils.js';
import { apiBase } from './api.js';

// Mirror of RITA_API_KEY from api.js — same default empty string.
// Declared here to avoid a circular import (api.js imports hedge.js).
const RITA_API_KEY = '';

export async function loadHedgeHistory() {
  if (state.hedgeHistoryLoaded) return;
  try {
    const resp = await fetch(apiBase() + '/api/v1/portfolio/hedge-history',
      RITA_API_KEY ? { headers: { 'X-API-Key': RITA_API_KEY } } : {});
    if (!resp.ok) throw new Error(`API ${resp.status}`);
    state.hedgeHistory = await resp.json();
    state.hedgeHistoryLoaded = true;
    document.getElementById('hist-loading').style.display = 'none';
    document.getElementById('hist-content').style.display = 'block';
    renderHedgeHistory();
  } catch (e) {
    document.getElementById('hist-loading').textContent = 'Failed to load hedge history: ' + e.message;
  }
}

export function renderHedgeHistory() {
  const days    = state.hedgeHistory.days    || [];
  const anchors = state.hedgeHistory.anchors || [];
  const rs      = state.hedgeHistory.reactive_score || {};
  const budget  = state.hedgeHistory.budget  || {};

  // ── KPIs ──────────────────────────────────────────────────────────────────
  const totalPremPeak = Math.max(...days.map(d => d.total_premium), 0);
  const reactPct = rs.reactive_pct || 0;
  const reactClass = reactPct >= 60 ? 'neg' : reactPct >= 30 ? 'warn' : 'pos';
  document.getElementById('hist-kpis').innerHTML = `
    <div class="kpi">
      <div class="kpi-label">Days Analysed</div>
      <div class="kpi-value">${days.length}</div>
      <div class="kpi-sub">${days.length > 0 ? days[0].date + ' → ' + days[days.length-1].date : '—'}</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Reactive Score</div>
      <div class="kpi-value ${reactClass}">${reactPct}%</div>
      <div class="kpi-sub ${reactClass}">${rs.label || '—'} · ${rs.reactive_opts||0}/${rs.total_new_opts||0} new opts</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Budget Peak</div>
      <div class="kpi-value ${budget.max_pct > 5 ? 'neg' : budget.max_pct > 3 ? 'warn' : 'pos'}">${budget.max_pct}%</div>
      <div class="kpi-sub">on ${budget.max_date} · avg ${budget.avg_pct}%</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Anchor Positions</div>
      <div class="kpi-value ${anchors.length > 0 ? 'warn' : 'pos'}">${anchors.length}</div>
      <div class="kpi-sub">${anchors.length > 0 ? 'Held 4+ days, declining quality' : 'None detected'}</div>
    </div>`;

  // ── Timeline chart ─────────────────────────────────────────────────────────
  const labels   = days.map(d => d.is_down_day ? d.date + ' ▼' : d.date);
  const nearData = days.map(d => d.near_atm_premium);
  const midData  = days.map(d => d.mid_otm_premium);
  const farData  = days.map(d => d.far_otm_premium);
  const niftyData = days.map(d => d.nifty_close);

  // Down-day bar borders
  const barBorder = days.map(d => d.is_down_day ? 'rgba(155,28,28,0.6)' : 'transparent');
  const barBorderW = days.map(d => d.is_down_day ? 2 : 0);

  if (state.hedgeTimelineChart) { state.hedgeTimelineChart.destroy(); state.hedgeTimelineChart = null; }
  const ctx = document.getElementById('hedge-timeline-chart');
  if (ctx) {
    requestAnimationFrame(() => { state.hedgeTimelineChart = new Chart(ctx, {
      data: {
        labels,
        datasets: [
          {
            type: 'bar', label: 'Near-ATM (≤5%)', data: nearData,
            backgroundColor: 'rgba(26,107,60,0.70)', stack: 'prem',
            borderColor: barBorder, borderWidth: barBorderW, borderRadius: 2,
          },
          {
            type: 'bar', label: 'Mid-OTM (5–10%)', data: midData,
            backgroundColor: 'rgba(146,72,10,0.65)', stack: 'prem',
            borderColor: barBorder, borderWidth: barBorderW,
          },
          {
            type: 'bar', label: 'Far-OTM (>10%)', data: farData,
            backgroundColor: 'rgba(155,28,28,0.75)', stack: 'prem',
            borderColor: barBorder, borderWidth: barBorderW,
          },
          {
            type: 'line', label: 'NIFTY Close', data: niftyData,
            borderColor: 'var(--p02)', backgroundColor: 'transparent',
            borderWidth: 2, pointRadius: 4, pointHoverRadius: 6,
            tension: 0.3, yAxisID: 'yNifty',
          },
        ]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: ctx => {
                if (ctx.dataset.yAxisID === 'yNifty')
                  return `NIFTY: ${ctx.raw.toLocaleString('en-IN', {minimumFractionDigits:2})}`;
                return `${ctx.dataset.label}: ₹${fmt(ctx.raw)}`;
              }
            }
          }
        },
        scales: {
          x: { grid: { display: false }, ticks: { font: { family: 'IBM Plex Mono', size: 11 } } },
          y: {
            stacked: true, position: 'left',
            grid: { color: 'rgba(0,0,0,.05)' },
            ticks: { font: { family: 'IBM Plex Mono', size: 10 }, callback: v => `₹${(v/1000).toFixed(0)}K` }
          },
          yNifty: {
            position: 'right', grid: { display: false },
            ticks: { font: { family: 'IBM Plex Mono', size: 10 }, callback: v => v.toLocaleString('en-IN') }
          }
        }
      }
    }); }); // end requestAnimationFrame
  }

  // ── Reactive analysis ──────────────────────────────────────────────────────
  const rSumEl = document.getElementById('reactive-summary');
  if (rSumEl) {
    const barW = rs.reactive_pct || 0;
    const labelColor = reactPct >= 60 ? 'var(--neg)' : reactPct >= 30 ? 'var(--p03)' : 'var(--p01)';
    rSumEl.innerHTML = `
      <div style="display:flex;align-items:baseline;gap:8px;margin-bottom:8px;">
        <span style="font-family:var(--fm);font-size:26px;font-weight:600;color:${labelColor}">${reactPct}%</span>
        <span style="font-family:var(--fm);font-size:11px;color:var(--t3);">of new positions added reactively (on NIFTY down days)</span>
      </div>
      <div style="background:var(--surface2);border-radius:100px;height:8px;overflow:hidden;margin-bottom:6px;">
        <div style="width:${barW}%;height:100%;background:${labelColor};border-radius:100px;transition:width .5s;"></div>
      </div>
      <div style="font-family:var(--fm);font-size:10px;color:var(--t3);">${rs.reactive_opts||0} reactive · ${(rs.total_new_opts||0)-(rs.reactive_opts||0)} proactive/neutral</div>`;
  }

  const rTbody = document.getElementById('reactive-tbody');
  if (rTbody) {
    rTbody.innerHTML = days.map(d => {
      const chgClass = d.nifty_chg_pct < 0 ? 'neg' : 'pos';
      const isDown   = d.is_down_day;
      const ctx      = isDown
        ? `<span style="color:var(--neg);font-weight:600;">↓ Down day — hedges added reactively</span>`
        : d.new_opts_count > 0
          ? `<span style="color:var(--p01);">↑ Calm — proactive additions</span>`
          : `<span style="color:var(--t4);">No new positions</span>`;
      return `<tr style="${isDown ? 'background:rgba(155,28,28,0.04)' : ''}">
        <td class="val">${d.date}</td>
        <td class="val ${chgClass}">${d.nifty_chg_pct >= 0 ? '+' : ''}${d.nifty_chg_pct.toFixed(1)}%</td>
        <td class="val">${d.new_opts_count}</td>
        <td class="val ${d.reactive_new_count > 0 ? 'neg' : ''}">${d.reactive_new_count}</td>
        <td>${ctx}</td>
      </tr>`;
    }).join('');
  }

  // ── Budget bars ────────────────────────────────────────────────────────────
  const budgetSumEl = document.getElementById('budget-summary');
  if (budgetSumEl) {
    const overDays = budget.days_over_5pct || 0;
    budgetSumEl.innerHTML = `
      <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;">
        <div style="text-align:center;background:var(--surface2);padding:10px;border-radius:var(--r);">
          <div style="font-family:var(--fm);font-size:18px;font-weight:600;">${budget.avg_pct}%</div>
          <div style="font-family:var(--fm);font-size:10px;color:var(--t3);margin-top:2px;">Avg Budget</div>
        </div>
        <div style="text-align:center;background:var(--surface2);padding:10px;border-radius:var(--r);">
          <div style="font-family:var(--fm);font-size:18px;font-weight:600;color:${budget.max_pct>5?'var(--neg)':budget.max_pct>3?'var(--p03)':'var(--p01)'}">${budget.max_pct}%</div>
          <div style="font-family:var(--fm);font-size:10px;color:var(--t3);margin-top:2px;">Peak (${budget.max_date})</div>
        </div>
        <div style="text-align:center;background:var(--surface2);padding:10px;border-radius:var(--r);">
          <div style="font-family:var(--fm);font-size:18px;font-weight:600;color:${overDays>0?'var(--neg)':'var(--p01)'}">${overDays}</div>
          <div style="font-family:var(--fm);font-size:10px;color:var(--t3);margin-top:2px;">Days over 5%</div>
        </div>
      </div>`;
  }

  const budgetBarsEl = document.getElementById('budget-bars');
  if (budgetBarsEl) {
    const maxBudget = Math.max(...days.map(d => d.hedge_budget_pct), 6);
    budgetBarsEl.innerHTML = days.map(d => {
      const pct    = d.hedge_budget_pct;
      const w      = (pct / maxBudget * 100).toFixed(1);
      const col    = pct > 5 ? 'var(--neg)' : pct > 3 ? 'var(--p03)' : 'var(--p01)';
      const thresh = (5 / maxBudget * 100).toFixed(1);
      return `<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
        <span style="font-family:var(--fm);font-size:10px;color:var(--t3);width:50px;flex-shrink:0;">${d.date}</span>
        <div style="flex:1;position:relative;height:14px;background:var(--surface2);border-radius:100px;overflow:visible;">
          <div style="width:${w}%;height:100%;background:${col};border-radius:100px;opacity:0.8;"></div>
          <div style="position:absolute;left:${thresh}%;top:-3px;width:2px;height:20px;background:var(--neg);opacity:0.4;"></div>
        </div>
        <span style="font-family:var(--fm);font-size:10px;font-weight:600;color:${col};width:36px;text-align:right;flex-shrink:0;">${pct}%</span>
      </div>`;
    }).join('');
  }

  // ── Anchor positions ───────────────────────────────────────────────────────
  document.getElementById('anchor-sub').textContent =
    `${anchors.length} position${anchors.length !== 1 ? 's' : ''} held 4+ days with below-par hedge quality`;

  const aTbody = document.getElementById('anchor-tbody');
  if (aTbody) {
    if (anchors.length === 0) {
      aTbody.innerHTML = '<tr><td colspan="9" style="text-align:center;color:var(--t3);padding:20px;font-family:var(--fm);font-size:12px;">No anchor positions detected.</td></tr>';
    } else {
      aTbody.innerHTML = anchors.map(a => {
        const decayClass  = a.pct_decay < -60 ? 'neg' : a.pct_decay < -30 ? 'warn' : '';
        const otmClass    = a.pct_otm_at_entry > 10 ? 'neg' : a.pct_otm_at_entry > 5 ? 'warn' : '';
        // Mini sparkline using text chars
        const trail = a.ltp_history.map((v, i, arr) => {
          if (i === 0) return v;
          return arr[i] < arr[i-1] ? `${v}↓` : `${v}↑`;
        });
        const hqsArrow = a.hqs_current < a.hqs_first ? '↓' : a.hqs_current > a.hqs_first ? '↑' : '→';
        const hqsColor = a.hqs_current < 40 ? 'var(--neg)' : a.hqs_current < 65 ? 'var(--p03)' : 'var(--p01)';
        return `<tr>
          <td>${a.full}</td>
          <td class="val">${a.days_held}d</td>
          <td class="val ${otmClass}">${a.pct_otm_at_entry.toFixed(1)}%</td>
          <td class="val">${a.entry_avg.toFixed(2)}</td>
          <td class="val">${a.current_ltp.toFixed(2)}</td>
          <td class="val ${decayClass}">${a.pct_decay >= 0 ? '+' : ''}${a.pct_decay.toFixed(1)}%</td>
          <td style="font-family:var(--fm);font-size:10px;"><span style="color:${hqsColor};font-weight:600;">${a.hqs_first}${hqsArrow}${a.hqs_current}</span></td>
          <td class="${pnlClass(a.current_pnl)}">${fmtPnl(a.current_pnl)}</td>
          <td style="font-family:var(--fm);font-size:9px;color:var(--t3);">${a.date_history.join(' ')}</td>
        </tr>`;
      }).join('');
    }
  }

  // ── Daily summary table ────────────────────────────────────────────────────
  const dTbody = document.getElementById('hist-day-tbody');
  if (dTbody) {
    dTbody.innerHTML = days.map(d => {
      const chgClass  = d.nifty_chg_pct < 0 ? 'neg' : 'pos';
      const budgClass = d.hedge_budget_pct > 5 ? 'neg' : d.hedge_budget_pct > 3 ? 'warn' : '';
      const rowStyle  = d.is_down_day ? 'background:rgba(155,28,28,0.04);' : '';
      return `<tr style="${rowStyle}">
        <td class="val">${d.date}${d.is_down_day ? ' ▼' : ''}</td>
        <td class="val">${d.nifty_close.toLocaleString('en-IN',{minimumFractionDigits:2})}</td>
        <td class="val ${chgClass}">${d.nifty_chg_pct >= 0 ? '+' : ''}${d.nifty_chg_pct.toFixed(1)}%</td>
        <td class="val">₹${fmt(d.total_premium)}</td>
        <td class="val" style="color:var(--p01);">₹${fmt(d.near_atm_premium)}</td>
        <td class="val" style="color:var(--neg);">₹${fmt(d.far_otm_premium)}</td>
        <td class="val ${budgClass}">${d.hedge_budget_pct}%</td>
        <td class="val" style="color:var(--p01);">${d.hqs_counts.green}</td>
        <td class="val" style="color:var(--p03);">${d.hqs_counts.yellow}</td>
        <td class="val" style="color:var(--neg);">${d.hqs_counts.red}</td>
        <td class="val ${d.reactive_new_count > 0 ? 'neg' : ''}">${d.new_opts_count}${d.reactive_new_count > 0 ? ` (${d.reactive_new_count} react)` : ''}</td>
      </tr>`;
    }).join('');
  }
}

// ── HEDGE RADAR ───────────────────────────────────────────────────────────────
export function renderHedgeRadar() {
  const allPos = (state.hedgeQuality.positions || []).filter(p =>
    (state.currentUnd === 'ALL' || p.und === state.currentUnd) &&
    (state.currentExpiry === 'ALL' || p.exp === state.currentExpiry)
  );

  const totalPrem   = allPos.reduce((s,p) => s + p.premium_total, 0);
  const redPos      = allPos.filter(p => p.hqs_tier === 'red');
  const yellowPos   = allPos.filter(p => p.hqs_tier === 'yellow');
  const greenPos    = allPos.filter(p => p.hqs_tier === 'green');
  const redPrem     = redPos.reduce((s,p) => s + p.premium_total, 0);
  const redPremPct  = totalPrem > 0 ? Math.round(redPrem / totalPrem * 100) : 0;
  const totalPnl    = allPos.reduce((s,p) => s + p.pnl, 0);
  const totalQty    = allPos.reduce((s,p) => s + p.qty, 0);
  const avgDelta    = totalQty > 0
    ? (allPos.reduce((s,p) => s + p.delta_abs * p.qty, 0) / totalQty).toFixed(3)
    : '—';

  // ── KPIs ──
  const kpisEl = document.getElementById('hqs-kpis');
  if (kpisEl) {
    const deltaWarn = parseFloat(avgDelta) < 0.15;
    kpisEl.innerHTML = `
      <div class="kpi">
        <div class="kpi-label">Premium Deployed</div>
        <div class="kpi-value">₹${(totalPrem/100000).toFixed(2)}L</div>
        <div class="kpi-sub">${allPos.length} long option${allPos.length!==1?'s':''}</div>
      </div>
      <div class="kpi">
        <div class="kpi-label">Lottery Ticket %</div>
        <div class="kpi-value ${redPos.length>0?'neg':'pos'}">${redPremPct}%</div>
        <div class="kpi-sub ${redPos.length>0?'neg':''}">${redPos.length} position${redPos.length!==1?'s':''} flagged 🔴</div>
      </div>
      <div class="kpi">
        <div class="kpi-label">Avg Delta</div>
        <div class="kpi-value ${deltaWarn?'warn':'pos'}">${avgDelta}</div>
        <div class="kpi-sub">${deltaWarn?'Low — high decay risk':'Acceptable range'}</div>
      </div>
      <div class="kpi">
        <div class="kpi-label">Hedge P&amp;L</div>
        <div class="kpi-value ${pnlClass(totalPnl)}">${fmtPnl(totalPnl)}</div>
        <div class="kpi-sub">${greenPos.length}🟢 ${yellowPos.length}🟡 ${redPos.length}🔴</div>
      </div>`;
  }

  // ── Alert banner ──
  const bannerEl = document.getElementById('hqs-alert-banner');
  if (bannerEl) {
    if (redPos.length > 0) {
      const redPnl = redPos.reduce((s,p) => s + p.pnl, 0);
      bannerEl.innerHTML = `<div class="alert-bar red">
        <span style="font-size:16px;">⚠</span>
        <span><strong>${redPos.length} Lottery Ticket position${redPos.length!==1?'s':''}</strong>
        — currently down ${fmtPnl(Math.abs(redPnl))} with high theta decay.
        Consider closing or rolling before further decay.</span>
      </div>`;
    } else if (yellowPos.length > 0) {
      bannerEl.innerHTML = `<div class="alert-bar yellow">
        <span style="font-size:16px;">◈</span>
        <span><strong>${yellowPos.length} Watch position${yellowPos.length!==1?'s':''}</strong>
        — monitor DTE and strike distance. Roll if approaching the danger zone.</span>
      </div>`;
    } else if (allPos.length > 0) {
      bannerEl.innerHTML = `<div class="alert-bar green">
        <span style="font-size:16px;">✓</span>
        <span>All long option positions are within acceptable hedge quality parameters.</span>
      </div>`;
    } else {
      bannerEl.innerHTML = '';
    }
  }

  // ── Tier breakdown bar card ──
  const tierCard = document.getElementById('hqs-tier-card');
  if (tierCard && allPos.length > 0) {
    const redPct    = Math.round(redPos.length / allPos.length * 100);
    const yellowPct = Math.round(yellowPos.length / allPos.length * 100);
    const greenPct  = 100 - redPct - yellowPct;
    tierCard.innerHTML = `
      <div class="card-hdr">
        <span class="card-title">Portfolio Hedge Quality Distribution</span>
        <span class="card-sub">${allPos.length} long options scored</span>
      </div>
      <div class="card-body">
        <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:18px;margin-bottom:14px;">
          <div style="text-align:center;">
            <div style="font-family:var(--fm);font-size:22px;font-weight:600;color:var(--neg);">${redPos.length}</div>
            <div style="font-family:var(--fm);font-size:10px;color:var(--t3);text-transform:uppercase;letter-spacing:.06em;margin-top:2px;">🔴 Lottery Ticket</div>
            <div style="font-family:var(--fm);font-size:11px;color:var(--neg);margin-top:4px;">₹${fmt(redPrem)} premium</div>
          </div>
          <div style="text-align:center;">
            <div style="font-family:var(--fm);font-size:22px;font-weight:600;color:var(--p03);">${yellowPos.length}</div>
            <div style="font-family:var(--fm);font-size:10px;color:var(--t3);text-transform:uppercase;letter-spacing:.06em;margin-top:2px;">🟡 Watch</div>
            <div style="font-family:var(--fm);font-size:11px;color:var(--p03);margin-top:4px;">₹${fmt(yellowPos.reduce((s,p)=>s+p.premium_total,0))} premium</div>
          </div>
          <div style="text-align:center;">
            <div style="font-family:var(--fm);font-size:22px;font-weight:600;color:var(--p01);">${greenPos.length}</div>
            <div style="font-family:var(--fm);font-size:10px;color:var(--t3);text-transform:uppercase;letter-spacing:.06em;margin-top:2px;">🟢 Good Hedge</div>
            <div style="font-family:var(--fm);font-size:11px;color:var(--p01);margin-top:4px;">₹${fmt(greenPos.reduce((s,p)=>s+p.premium_total,0))} premium</div>
          </div>
        </div>
        <div class="hqs-tier-bar">
          <div class="hqs-tier-seg red"    style="width:${redPct}%"></div>
          <div class="hqs-tier-seg yellow" style="width:${yellowPct}%"></div>
          <div class="hqs-tier-seg green"  style="width:${Math.max(0,greenPct)}%"></div>
        </div>
        <div style="display:flex;justify-content:space-between;font-family:var(--fm);font-size:10px;color:var(--t3);margin-top:6px;">
          <span>${redPct}% Lottery Ticket</span>
          <span>${yellowPct}% Watch</span>
          <span>${100-redPct-yellowPct}% Good</span>
        </div>
      </div>`;
  }

  // ── Scored positions table ──
  const tbody = document.getElementById('hqs-tbody');
  if (!tbody) return;

  tbody.innerHTML = allPos.map(p => `
    <tr>
      <td>${p.full}</td>
      <td><span class="exp-badge ${p.exp.toLowerCase()}">${p.exp}</span></td>
      <td><span class="inst-badge ${p.type.toLowerCase()}">${p.type}</span></td>
      <td class="val">${p.strike}</td>
      <td class="val">${fmt(p.qty)}</td>
      <td class="val">${p.avg.toFixed(2)}</td>
      <td class="val">${p.ltp.toFixed(2)}</td>
      <td class="${pnlClass(p.pnl)}">${fmtPnl(p.pnl)}</td>
      <td class="val ${p.pct_otm>10?'neg':p.pct_otm>5?'warn':''}">${p.pct_otm.toFixed(1)}%</td>
      <td class="val ${p.dte<14?'neg':p.dte<21?'warn':''}">${p.dte}d</td>
      <td class="val ${p.delta_abs<0.10?'neg':p.delta_abs<0.20?'warn':''}">${p.delta_abs.toFixed(3)}</td>
      <td class="val">₹${fmt(p.premium_total)}</td>
      <td><span class="hqs-score ${p.hqs_tier}">${p.hqs}<span style="font-size:9px;opacity:.6;">/100</span></span></td>
      <td><span class="hqs-badge ${p.hqs_tier}">${{green:'🟢',yellow:'🟡',red:'🔴'}[p.hqs_tier]} ${p.hqs_label}</span></td>
    </tr>`).join('');

  // ── Footer totals ──
  const footerEl = document.getElementById('hqs-footer');
  if (footerEl) {
    footerEl.innerHTML = `
      <span class="lbl">Total Premium Deployed:</span>
      <span class="val">₹${fmt(totalPrem)}</span>
      <span class="lbl" style="margin-left:20px;">Lottery Ticket Premium:</span>
      <span class="val neg">₹${fmt(redPrem)}</span>
      <span class="lbl" style="margin-left:20px;">Net Hedge P&amp;L:</span>
      <span class="val ${pnlClass(totalPnl)}">${fmtPnl(totalPnl)}</span>`;
  }

  // ── Update nav badge ──
  const badge = document.getElementById('nav-hedge-badge');
  if (badge) {
    const n = redPos.length;
    if (n > 0) {
      badge.textContent = n;
      badge.style.display = 'inline';
    } else {
      badge.style.display = 'none';
    }
  }
}
