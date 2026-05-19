// ── Risk-Reward section ───────────────────────────────────────────────────────
import { state } from './state.js';
import { fmtPnl, pnlClass } from './utils.js';
import { apiBase } from './api.js';

// Bull = FUT Long, CE Long, PE Short  |  Bear = FUT Short, CE Short, PE Long
export function getBullBear(p) {
  if (p.type === 'FUT') return p.side === 'Long' ? 'bull' : 'bear';
  if (p.type === 'CE')  return p.side === 'Long' ? 'bull' : 'bear';
  if (p.type === 'PE')  return p.side === 'Short' ? 'bull' : 'bear';
  return 'bull';
}

// ── localStorage history ──────────────────────────────────────────────────────
export function loadHistory() {
  try { return JSON.parse(localStorage.getItem('rrHistory') || '[]'); } catch { return []; }
}

export function saveToday() {
  const history = loadHistory();
  const todayStr = state.marketData.NIFTY && state.marketData.NIFTY.date;
  if (!todayStr) return;
  const niftyPnl  = state.positions.filter(p => p.und === 'NIFTY').reduce((s, p) => s + p.pnl, 0);
  const bnknPnl   = state.positions.filter(p => p.und === 'BANKNIFTY').reduce((s, p) => s + p.pnl, 0);
  const existing  = history.find(h => h.date === todayStr);
  if (!existing || !existing.nifty) {
    const idx = history.findIndex(h => h.date === todayStr);
    const entry = { date: todayStr, nifty: state.marketData.NIFTY.close, banknifty: (state.marketData.BANKNIFTY || {}).close, asml: (state.marketData.ASML || {}).close || null, niftyPnl, bnknPnl };
    if (idx >= 0) history[idx] = entry; else history.push(entry);
    if (history.length > 30) history.shift();
    try { localStorage.setItem('rrHistory', JSON.stringify(history)); } catch {}
  }
}

export async function syncPriceHistory() {
  try {
    const serverDays = await fetch(apiBase() + '/api/v1/portfolio/price-history').then(r => r.json());
    if (!Array.isArray(serverDays) || !serverDays.length) return;
    const history = loadHistory();
    let changed = false;
    serverDays.forEach(sd => {
      const existing = history.find(h => h.date === sd.date);
      if (!existing) {
        history.push({ date: sd.date, nifty: sd.nifty, banknifty: sd.banknifty,
                       niftyPnl: sd.niftyPnl ?? null, bnknPnl: sd.bnknPnl ?? null,
                       niftyRPnl: sd.niftyRPnl ?? null, bnknRPnl: sd.bnknRPnl ?? null });
        changed = true;
      } else {
        if (!existing.nifty || !existing.banknifty) {
          existing.nifty = sd.nifty; existing.banknifty = sd.banknifty; changed = true;
        }
        if (sd.niftyPnl != null && (existing.niftyPnl == null || existing.niftyPnl === undefined)) {
          existing.niftyPnl = sd.niftyPnl; existing.bnknPnl = sd.bnknPnl ?? null; changed = true;
        }
        if (sd.niftyRPnl != null) {
          existing.niftyRPnl = sd.niftyRPnl; existing.bnknRPnl = sd.bnknRPnl ?? null; changed = true;
        }
      }
    });
    if (changed) {
      history.sort((a, b) => new Date(a.date.replace(/-/g, ' ')) - new Date(b.date.replace(/-/g, ' ')));
      if (history.length > 60) history.splice(0, history.length - 60);
      try { localStorage.setItem('rrHistory', JSON.stringify(history)); } catch {}
    }
  } catch (e) { /* non-critical */ }
}

export function getProgressDir(und, mode) {
  const history = loadHistory();
  if (history.length < 2) return 'neutral';
  const key = und === 'NIFTY' ? 'nifty' : 'banknifty';
  const todayC = history[history.length - 1][key];
  const yestC  = history[history.length - 2][key];
  const { sl, target } = state.scenarioLevels[und][mode];
  const isBull = target > sl;
  const todayPct = isBull ? (todayC - sl) / (target - sl) : (sl - todayC) / (sl - target);
  const yestPct  = isBull ? (yestC  - sl) / (target - sl) : (sl - yestC)  / (sl - target);
  return todayPct > yestPct ? 'toward' : todayPct < yestPct ? 'away' : 'neutral';
}

export function computeScen(sl, target, current, delta) {
  const isBull = target > sl;
  const pct = isBull
    ? Math.max(0, Math.min(100, (current - sl)   / (target - sl)   * 100))
    : Math.max(0, Math.min(100, (sl   - current) / (sl   - target) * 100));
  const risk    = Math.abs(current - sl);
  const reward  = Math.abs(target  - current);
  const rr      = reward / risk;
  const pnlTgt  = Math.round(delta * (target - current));
  const pnlSL   = Math.round(delta * (sl     - current));
  return { isBull, pct, risk, reward, rr, pnlTgt, pnlSL };
}

export function renderScenCard(und, mode) {
  const current = state.marketData[und].close;
  const isBull  = mode === 'bull';
  const { sl, target } = state.scenarioLevels[und][mode];
  const sc  = computeScen(sl, target, current, state.portDelta[und]);
  const dir = getProgressDir(und, mode);
  const pct = sc.pct.toFixed(1);
  const rrColor    = sc.rr >= 1 ? 'var(--pos)' : 'var(--neg)';
  const dirLabel   = dir === 'toward' ? '↑ Moving toward target' : dir === 'away' ? '↓ Moving away from target' : '— No prior data (opens daily)';
  const dirColor   = dir === 'toward' ? 'var(--pos)' : dir === 'away' ? 'var(--p03)' : 'var(--t3)';
  const groupPnl   = state.positions.filter(p => p.und === und && getBullBear(p) === mode).reduce((s, p) => s + p.pnl, 0);
  const cls        = isBull ? 'bull' : 'bear';
  return `<div class="scen-card ${cls}">
    <div class="scen-hdr">
      <div class="scen-title">${isBull ? 'Bull View' : 'Bear View'}</div>
      <span class="scen-badge ${cls}">${isBull ? 'BULLISH' : 'BEARISH'}</span>
    </div>
    <div class="scen-bar-labels">
      <span>SL: ${sl.toLocaleString('en-IN')}</span>
      <span>Target: ${target.toLocaleString('en-IN')}</span>
    </div>
    <div class="scen-bar-wrap">
      <div class="scen-bar-outer">
        <div class="scen-bar-fill ${dir}" style="width:${pct}%"></div>
      </div>
      <div class="scen-bar-marker ${dir}" style="left:${pct}%"></div>
      <div class="scen-bar-current ${dir}" style="left:${pct}%">▲ ${current.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</div>
    </div>
    <div class="scen-progress" style="color:${dirColor}">${dirLabel} &nbsp;·&nbsp; ${pct}%</div>
    <div class="scen-stats">
      <div class="scen-stat"><div class="scen-stat-lbl">Risk (pts)</div><div class="scen-stat-val neg">${sc.risk.toFixed(0)}</div></div>
      <div class="scen-stat"><div class="scen-stat-lbl">Reward (pts)</div><div class="scen-stat-val pos">${sc.reward.toFixed(0)}</div></div>
      <div class="scen-stat"><div class="scen-stat-lbl">R : R</div><div class="scen-stat-val" style="color:${rrColor}">1 : ${sc.rr.toFixed(2)}</div></div>
      <div class="scen-stat"><div class="scen-stat-lbl">Progress</div><div class="scen-stat-val" style="color:${dirColor}">${pct}%</div></div>
    </div>
    <div class="scen-impact">
      <div class="scen-impact-row">
        <span class="scen-impact-lbl">Current ${isBull ? 'bull' : 'bear'} bets P&amp;L:</span>
        <span class="${groupPnl >= 0 ? 'pos' : 'neg'}" style="font-family:var(--fm);font-size:12px;font-weight:600">${fmtPnl(groupPnl)}</span>
      </div>
      <div class="scen-impact-row">
        <span class="scen-impact-lbl">Portfolio Δ at Target (${target.toLocaleString('en-IN')}):</span>
        <span class="${sc.pnlTgt >= 0 ? 'pos' : 'neg'}" style="font-family:var(--fm);font-size:12px;font-weight:600">${fmtPnl(sc.pnlTgt)}</span>
      </div>
      <div class="scen-impact-row">
        <span class="scen-impact-lbl">Portfolio Δ at Stop Loss (${sl.toLocaleString('en-IN')}):</span>
        <span class="${sc.pnlSL >= 0 ? 'pos' : 'neg'}" style="font-family:var(--fm);font-size:12px;font-weight:600">${fmtPnl(sc.pnlSL)}</span>
      </div>
    </div>
  </div>`;
}

export function renderView(und, mode) {
  const isBull = mode === 'bull';
  const tagCls = isBull ? 'bull' : 'bear';
  const label  = isBull ? '▲ Bull View' : '▼ Bear View';
  return `
    <div class="rr-view-hdr">
      <span class="rr-view-tag ${tagCls}">${label}</span>
      <div class="line"></div>
    </div>
    <div class="rr-view-grid">
      <div>${renderScenCard(und, mode)}</div>
      <div>${renderBullBearTable(und, mode)}</div>
    </div>`;
}

export function renderBullBearKpis(und) {
  const exp = p => state.currentExpiry === 'ALL' || p.exp === state.currentExpiry;
  const bullPnl = state.positions.filter(p => p.und === und && exp(p) && getBullBear(p) === 'bull').reduce((s, p) => s + p.pnl, 0);
  const bearPnl = state.positions.filter(p => p.und === und && exp(p) && getBullBear(p) === 'bear').reduce((s, p) => s + p.pnl, 0);
  const bullCnt = state.positions.filter(p => p.und === und && exp(p) && getBullBear(p) === 'bull').length;
  const bearCnt = state.positions.filter(p => p.und === und && exp(p) && getBullBear(p) === 'bear').length;
  const spot    = state.marketData[und].close;
  return `<div class="kpi-row c4" style="margin-bottom:16px;">
    <div class="kpi"><div class="kpi-label">Current P&amp;L</div><div class="kpi-value ${pnlClass(bullPnl + bearPnl)}">${fmtPnl(bullPnl + bearPnl)}</div><div class="kpi-sub">Bull + Bear combined</div></div>
    <div class="kpi"><div class="kpi-label">Bull Bets P&amp;L</div><div class="kpi-value ${pnlClass(bullPnl)}">${fmtPnl(bullPnl)}</div><div class="kpi-sub">${bullCnt} pos · FUT Long · CE Long · PE Short</div></div>
    <div class="kpi"><div class="kpi-label">Bear Bets P&amp;L</div><div class="kpi-value ${pnlClass(bearPnl)}">${fmtPnl(bearPnl)}</div><div class="kpi-sub">${bearCnt} pos · FUT Short · CE Short · PE Long</div></div>
    <div class="kpi"><div class="kpi-label">${und === 'BANKNIFTY' ? 'BANKNIFTY' : 'NIFTY'} Spot</div><div class="kpi-value" style="font-family:var(--fm)">${spot.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</div><div class="kpi-sub">${state.marketData[und].date}</div></div>
  </div>`;
}

export function renderBullBearTable(und, mode) {
  const grp    = state.positions.filter(p => p.und === und && (state.currentExpiry === 'ALL' || p.exp === state.currentExpiry) && getBullBear(p) === mode);
  const isBull = mode === 'bull';
  const total  = grp.reduce((s, p) => s + p.pnl, 0);
  return `<div class="card" style="margin-bottom:14px;">
    <div class="card-hdr">
      <span class="card-title" style="color:${isBull ? 'var(--p01)' : 'var(--neg)'}">${isBull ? '▲' : '▼'} ${und} ${isBull ? 'Bull' : 'Bear'} Positions</span>
      <span class="card-sub">${grp.length} pos · ${fmtPnl(total)} · ${isBull ? 'FUT Long · CE Long · PE Short' : 'FUT Short · CE Short · PE Long'}</span>
    </div>
    <div class="card-body" style="padding:0">
      <div class="tbl-wrap">
        <table>
          <thead><tr><th>Instrument</th><th>Exp</th><th>Type</th><th>Side</th><th>Qty</th><th>Avg</th><th>LTP</th><th>P&amp;L</th></tr></thead>
          <tbody>${grp.map(p => `<tr>
            <td>${p.full}</td>
            <td><span class="exp-badge ${p.exp.toLowerCase()}">${p.exp}</span></td>
            <td><span class="inst-badge ${p.type.toLowerCase()}">${p.type}</span></td>
            <td><span class="side-badge ${p.side.toLowerCase()}">${p.side}</span></td>
            <td class="val">${p.qty.toLocaleString ? p.qty.toLocaleString('en-IN') : p.qty}</td>
            <td class="val">${p.type === 'FUT' ? '₹' + p.avg.toLocaleString('en-IN', { minimumFractionDigits: 2 }) : p.avg.toFixed(2)}</td>
            <td class="val">${p.type === 'FUT' ? '₹' + p.ltp.toLocaleString('en-IN', { minimumFractionDigits: 2 }) : p.ltp.toFixed(2)}</td>
            <td class="${pnlClass(p.pnl)}">${fmtPnl(p.pnl)}</td>
          </tr>`).join('')}</tbody>
        </table>
      </div>
      <div class="tbl-footer">
        <span class="lbl">${isBull ? 'Bull' : 'Bear'} Total:</span>
        <span class="val ${pnlClass(total)}">${fmtPnl(total)}</span>
      </div>
    </div>
  </div>`;
}

export function renderRRHistory() {
  const history = loadHistory();
  if (!history.length) return `<div class="info-note" style="margin-top:18px;">Daily history will appear here after you open the page on a second day. Data is saved automatically in browser localStorage.</div>`;
  const rows = [...history].reverse().map((h, i) => {
    const isToday = h.date === state.marketData.NIFTY.date;
    const nBull = computeScen(state.scenarioLevels.NIFTY.bull.sl,     state.scenarioLevels.NIFTY.bull.target,     h.nifty,     state.portDelta.NIFTY).pct;
    const nBear = computeScen(state.scenarioLevels.NIFTY.bear.sl,     state.scenarioLevels.NIFTY.bear.target,     h.nifty,     state.portDelta.NIFTY).pct;
    const bBull = computeScen(state.scenarioLevels.BANKNIFTY.bull.sl, state.scenarioLevels.BANKNIFTY.bull.target, h.banknifty, state.portDelta.BANKNIFTY).pct;
    const bBear = computeScen(state.scenarioLevels.BANKNIFTY.bear.sl, state.scenarioLevels.BANKNIFTY.bear.target, h.banknifty, state.portDelta.BANKNIFTY).pct;
    const prev  = history[history.length - 1 - (i + 1)];
    const arrow = (cur, prevVal) => !prev ? '—' : cur > prevVal ? '<span style="color:var(--pos)">↑</span>' : cur < prevVal ? '<span style="color:var(--p03)">↓</span>' : '=';
    const prevNBull = prev ? computeScen(state.scenarioLevels.NIFTY.bull.sl,     state.scenarioLevels.NIFTY.bull.target,     prev.nifty,     state.portDelta.NIFTY).pct     : null;
    const prevNBear = prev ? computeScen(state.scenarioLevels.NIFTY.bear.sl,     state.scenarioLevels.NIFTY.bear.target,     prev.nifty,     state.portDelta.NIFTY).pct     : null;
    const prevBBull = prev ? computeScen(state.scenarioLevels.BANKNIFTY.bull.sl, state.scenarioLevels.BANKNIFTY.bull.target, prev.banknifty, state.portDelta.BANKNIFTY).pct : null;
    const prevBBear = prev ? computeScen(state.scenarioLevels.BANKNIFTY.bear.sl, state.scenarioLevels.BANKNIFTY.bear.target, prev.banknifty, state.portDelta.BANKNIFTY).pct : null;
    const hasPnl    = h.niftyPnl != null;
    const totalPnl  = hasPnl ? h.niftyPnl + h.bnknPnl : null;
    const hasRPnl   = h.niftyRPnl != null;
    const totalRPnl = hasRPnl ? h.niftyRPnl + h.bnknRPnl : null;
    const pnlCell   = (v) => v == null ? `<td class="val" style="color:var(--t3)">—</td>`
      : `<td class="${v >= 0 ? 'pos' : 'neg'}">${fmtPnl(v)}</td>`;
    const arrowPnl  = (cur, p) => !p || p.niftyPnl == null ? '' :
      cur > (p.niftyPnl + p.bnknPnl) ? '<span style="color:var(--pos)">↑</span>' :
      cur < (p.niftyPnl + p.bnknPnl) ? '<span style="color:var(--p03)">↓</span>' : '=';
    const s = isToday ? 'font-weight:600;background:var(--surface2)' : '';
    if (!h.nifty || !h.banknifty) return '';
    return `<tr style="${s}">
      <td class="val">${h.date}${isToday ? ' ◀' : ''}</td>
      <td class="val">${h.nifty.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</td>
      <td class="val">${h.banknifty.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</td>
      ${pnlCell(hasPnl ? h.niftyPnl : null)}
      ${pnlCell(hasPnl ? h.bnknPnl : null)}
      ${hasPnl ? `<td class="${totalPnl >= 0 ? 'pos' : 'neg'}" style="font-weight:600">${arrowPnl(totalPnl, prev)} ${fmtPnl(totalPnl)}</td>` : `<td class="val" style="color:var(--t3)">—</td>`}
      ${pnlCell(totalRPnl)}
      <td class="val">${arrow(nBull, prevNBull)} ${nBull.toFixed(1)}%</td>
      <td class="val">${arrow(nBear, prevNBear)} ${nBear.toFixed(1)}%</td>
      <td class="val">${arrow(bBull, prevBBull)} ${bBull.toFixed(1)}%</td>
      <td class="val">${arrow(bBear, prevBBear)} ${bBear.toFixed(1)}%</td>
    </tr>`;
  }).join('');
  return `<div class="card" style="margin-top:18px;">
    <div class="card-hdr">
      <span class="card-title">Daily Progress History</span>
      <span class="card-sub">Unrealized P&amp;L = open positions MTM · Realized P&amp;L = closed positions that day · Progress % = SL→Target distance</span>
    </div>
    <div class="card-body" style="padding:0">
      <div class="tbl-wrap">
        <table>
          <thead><tr><th>Date</th><th>NIFTY</th><th>BANKNIFTY</th><th>N Unreal</th><th>BN Unreal</th><th>Total Unreal</th><th>Realized</th><th>N-Bull%</th><th>N-Bear%</th><th>BN-Bull%</th><th>BN-Bear%</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </div>
  </div>`;
}

export function renderScenarios() {
  document.getElementById('nifty-scen-section').style.display     = state.currentUnd === 'BANKNIFTY' ? 'none' : '';
  document.getElementById('banknifty-scen-section').style.display = state.currentUnd === 'NIFTY'     ? 'none' : '';

  if (state.currentUnd !== 'BANKNIFTY') {
    document.getElementById('nifty-rr-kpis').innerHTML  = renderBullBearKpis('NIFTY');
    document.getElementById('nifty-rr-views').innerHTML = renderView('NIFTY', 'bull') + renderView('NIFTY', 'bear');
  }
  if (state.currentUnd !== 'NIFTY') {
    document.getElementById('banknifty-rr-kpis').innerHTML  = renderBullBearKpis('BANKNIFTY');
    document.getElementById('banknifty-rr-views').innerHTML = renderView('BANKNIFTY', 'bull') + renderView('BANKNIFTY', 'bear');
  }

  const summaryDefs = ['NIFTY', 'BANKNIFTY'].flatMap(und => ['bull', 'bear'].map(mode => ({
    und, mode: mode.charAt(0).toUpperCase() + mode.slice(1),
    sl:     state.scenarioLevels[und][mode].sl,
    target: state.scenarioLevels[und][mode].target,
    cur:    state.marketData[und].close,
    delta:  state.portDelta[und]
  }))).filter(r => state.currentUnd === 'ALL' || r.und === state.currentUnd);

  const summaryRows = summaryDefs.map(r => {
    const sc      = computeScen(r.sl, r.target, r.cur, r.delta);
    const dir     = getProgressDir(r.und, r.mode.toLowerCase());
    const isBull  = r.mode === 'Bull';
    const dirIcon = dir === 'toward' ? '<span style="color:var(--pos)">↑</span>' : dir === 'away' ? '<span style="color:var(--p03)">↓</span>' : '—';
    const groupPnl = state.positions.filter(p => p.und === r.und && getBullBear(p) === r.mode.toLowerCase()).reduce((s, p) => s + p.pnl, 0);
    const undBg = r.und === 'NIFTY' ? 'var(--p02-bg)' : 'var(--p04-bg)';
    const undClr = r.und === 'NIFTY' ? 'var(--p02)' : 'var(--p04)';
    return `<tr>
      <td>
        <span style="font-family:var(--fm);font-size:10px;font-weight:600;padding:2px 7px;border-radius:3px;background:${undBg};color:${undClr};">${r.und}</span>
        <span style="font-family:var(--fm);font-size:10px;font-weight:600;padding:2px 7px;border-radius:3px;background:${isBull ? 'var(--p01-bg)' : 'var(--neg-bg)'};color:${isBull ? 'var(--p01)' : 'var(--neg)'};">${r.mode}</span>
      </td>
      <td class="val">${r.sl.toLocaleString('en-IN')}</td>
      <td class="val" style="font-weight:600">${r.cur.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</td>
      <td class="val">${r.target.toLocaleString('en-IN')}</td>
      <td class="val">${dirIcon} ${sc.pct.toFixed(1)}%</td>
      <td class="val" style="color:${sc.rr >= 1 ? 'var(--pos)' : 'var(--neg)'};font-weight:600">1 : ${sc.rr.toFixed(2)}</td>
      <td class="${pnlClass(groupPnl)}">${fmtPnl(groupPnl)}</td>
      <td class="${sc.pnlTgt >= 0 ? 'pos' : 'neg'}">${fmtPnl(sc.pnlTgt)}</td>
      <td class="${sc.pnlSL >= 0 ? 'pos' : 'neg'}">${fmtPnl(sc.pnlSL)}</td>
    </tr>`;
  }).join('');

  document.getElementById('scen-summary-card').innerHTML = `
    <div class="card-hdr">
      <span class="card-title">Risk-Reward Summary</span>
      <span class="card-sub">Net Δ: NIFTY ${state.portDelta.NIFTY} · BANKNIFTY ${state.portDelta.BANKNIFTY} · ↑ = moving toward target</span>
    </div>
    <div class="card-body" style="padding:0">
      <div class="tbl-wrap">
        <table>
          <thead><tr>
            <th>Scenario</th><th>Stop Loss</th><th>Current</th><th>Target</th>
            <th>Progress</th><th>R:R</th><th>Current P&amp;L</th><th>At Target</th><th>At Stop</th>
          </tr></thead>
          <tbody>${summaryRows}</tbody>
        </table>
      </div>
    </div>`;

  document.getElementById('rr-history').innerHTML = renderRRHistory();
}
