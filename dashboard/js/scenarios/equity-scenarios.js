// Equity Scenarios — static-JSON data layer
// Data: /dashboard/data/scenarios/{alerts,portfolio,tradebook}.json
// Move to API endpoints once DB models are ready.

const DATA = `${window.location.origin}/dashboard/data/scenarios`;

async function loadJSON(file) {
  const r = await fetch(`${DATA}/${file}`);
  if (!r.ok) throw new Error(`Cannot load ${file} (${r.status})`);
  return r.json();
}

// ── Formatters ────────────────────────────────────────────────────────────────

const INR  = v => '₹' + Number(v).toLocaleString('en-IN', { maximumFractionDigits: 2, minimumFractionDigits: 2 });
const PCT  = v => (v >= 0 ? '+' : '') + Number(v).toFixed(2) + '%';
const KPCT = v => (v >= 0 ? '+' : '') + Number(v).toFixed(2) + '%';

function daysAgo(dateStr) {
  const ms = Date.now() - new Date(dateStr).getTime();
  const d = Math.floor(ms / 86_400_000);
  if (d === 0) return 'today';
  if (d === 1) return 'yesterday';
  return `${d}d ago`;
}

// ── Status logic ──────────────────────────────────────────────────────────────

function computeStatus(ltp, sl, target, dayChg) {
  if (!sl && !target) return { code: 'no-alerts',   label: 'No Alerts',    cls: 'neu' };
  if (!sl)            return { code: 'no-sl',        label: 'No SL',        cls: 'warn' };

  if (!target) {
    const buf = (ltp - sl) / sl * 100;
    if (buf < 0)   return { code: 'sl-breach', label: 'Below SL',  cls: 'err' };
    if (buf < 2)   return { code: 'near-sl',   label: 'Near SL',   cls: dayChg < 0 ? 'err' : 'warn' };
    return               { code: 'watch',      label: 'Watch',      cls: 'warn' };
  }

  const range  = target - sl;
  const pctInR = (ltp - sl) / range;

  if (pctInR < 0)    return { code: 'sl-breach',      label: 'Below SL',      cls: 'err' };
  if (pctInR < 0.15) return { code: dayChg < 0 ? 'urgent' : 'near-sl',
                               label: dayChg < 0 ? 'Near SL ▼' : 'Near SL',
                               cls:   dayChg < 0 ? 'err' : 'warn' };
  if (pctInR > 0.85) return { code: 'near-target',    label: 'Near Target',   cls: 'ok' };
  if (pctInR >= 0.5) return { code: 'in-range-upper', label: 'In Range',      cls: 'ok' };
  return               { code: 'in-range-lower',       label: 'In Range',      cls: 'warn' };
}

function buildRecommendation(status, ltp, sl, target, dayChg, avgCost) {
  const isTrailing = sl != null && avgCost < sl;
  const dayStr     = `${(dayChg ?? 0) >= 0 ? '+' : ''}${(dayChg ?? 0).toFixed(2)}%`;

  switch (status.code) {
    case 'urgent':
      return { cls: 'urgent',
               text: `⚡ Falling ${dayStr} today. Only ${INR(ltp - sl)} above SL. Review position.` };
    case 'sl-breach':
      return { cls: 'urgent',
               text: `🔴 Price below SL level. Exit or reassess immediately.` };
    case 'near-sl':
      return { cls: 'watch',
               text: isTrailing
                 ? `⚠ Near trailing stop — protecting entry gains. Day ${dayStr}. Hold, watch closely.`
                 : `⚠ Near SL. Day ${dayStr}. ${dayChg > 0 ? 'Positive momentum — hold.' : 'Consider reviewing.'}` };
    case 'near-target':
      return { cls: 'good',
               text: `✓ Approaching target ${INR(target)}. Consider partial profit booking.` };
    case 'in-range-upper':
      return { cls: 'good',
               text: `✓ Healthy position. ${target ? `Target ${INR(target)} within reach.` : ''} Hold.` };
    case 'in-range-lower':
      return { cls: 'watch',
               text: isTrailing
                 ? `~ Lower half of range. Trailing stop protecting ${INR(ltp - avgCost)}/share gain. Hold.`
                 : `~ Lower half of range. Monitor SL ${INR(sl)}. Day ${dayStr}.` };
    case 'no-sl':
      return { cls: 'watch',
               text: `⚠ No active SL. ${target ? `Target ${INR(target - ltp)} away (${INR(target)}).` : ''} Set a stop loss.` };
    case 'watch':
      return { cls: 'watch',
               text: `~ SL at ${INR(sl)}. Buffer ${INR(ltp - sl)} (${((ltp - sl) / sl * 100).toFixed(1)}%). Hold.` };
    default:
      return { cls: 'info', text: 'Hold. Monitor alerts.' };
  }
}

// ── 9-dot position indicator helpers ─────────────────────────────────────────

function calcFilled(sl, target, ltp, avg) {
  if (!sl && !target) return 0;
  if (!sl && target)  return Math.round(Math.max(0, Math.min(1, ltp / target)) * 9);
  if (sl && !target) {
    const buf = (ltp - sl) / sl;
    return buf < 0 ? 0 : Math.min(6, Math.round(buf / 0.05));
  }
  const rawPct = (ltp - sl) / (target - sl);
  return rawPct < 0 ? 0 : Math.min(9, Math.round(rawPct * 9));
}

function buildDotHtml(filled) {
  const zones = ['loss','loss','loss','ctrl','ctrl','ctrl','gain','gain','gain'];
  return zones.map((z, i) => {
    const sep = (i === 2 || i === 5) ? '<span class="dot-sep"></span>' : '';
    return `<span class="dot dot-${z}${i < filled ? ' dot-lit' : ''}"></span>${sep}`;
  }).join('');
}

function dotStatLine(sl, target, ltp, avg) {
  if (!sl && !target) return 'No alerts configured';
  if (!sl && target)  return `LTP ${INR(ltp)} · TGT ${INR(target)} · ${((target - ltp) / target * 100).toFixed(1)}% to target`;
  if (sl && !target)  return `LTP ${INR(ltp)} · SL ${INR(sl)} · ${((ltp - sl) / sl * 100).toFixed(1)}% buffer · no target`;
  const isTrailing = avg < sl;
  const t = isTrailing ? ` · trailing stop (locked ${INR(sl - avg)}/sh)` : '';
  return `SL ${INR(sl)} · LTP ${INR(ltp)} · TGT ${INR(target)}${t}`;
}

// ── Trade analysis ────────────────────────────────────────────────────────────

function analyseeTrades(trades) {
  if (!trades.length) return { nEntries: 0, firstDate: null, strategy: 'No trades' };
  const prices  = trades.map(t => t.price);
  const firstDt = trades[0].trade_time.split('T')[0];
  let strategy;
  if (trades.length === 1) {
    strategy = 'Single entry';
  } else {
    const first = prices[0];
    const last  = prices[prices.length - 1];
    if (last < first - 1)      strategy = 'Averaged down';
    else if (last > first + 1) strategy = 'Averaged up';
    else                       strategy = 'Multiple entries';
  }
  return { nEntries: trades.length, firstDate: firstDt, strategy };
}

// ── Urgency sort ──────────────────────────────────────────────────────────────

function urgencyScore(holding, alert) {
  if (!alert) return 99;
  const { sl, target } = alert;
  const { ltp, day_chg_pct } = holding;
  if (!sl && !target) return 9;
  if (!sl)            return 5;
  if (!target) return (ltp - sl) / sl < 0.02 ? 1 : 3;
  const pct = (ltp - sl) / (target - sl);
  if (pct < 0)                        return 0;
  if (pct < 0.15 && day_chg_pct < 0) return 1;
  if (pct < 0.15)                     return 2;
  if (pct < 0.3)                      return 3;
  if (pct > 0.85)                     return 6;
  return 7;
}

// ── Table row renderer ────────────────────────────────────────────────────────

function renderRow(holding, alert, tradeInfo, idx) {
  const { symbol, qty, avg_cost, ltp, invested, pnl, net_chg_pct, day_chg_pct } = holding;
  const sl     = alert?.sl     ?? null;
  const target = alert?.target ?? null;
  const name   = alert?.name   ?? symbol;

  const status     = computeStatus(ltp, sl, target, day_chg_pct);
  const rowCls     = status.cls === 'err'  ? 'row-danger'
                   : status.cls === 'warn' ? 'row-warn'
                   : status.cls === 'ok'   ? 'row-ok'
                   : 'row-neu';
  const dayDir     = day_chg_pct > 0.05 ? 'pos' : day_chg_pct < -0.05 ? 'neg' : 'neu';
  const dayArrow   = day_chg_pct > 0.05 ? '▲'   : day_chg_pct < -0.05 ? '▼'   : '—';
  const pnlCls     = pnl >= 0 ? 'pos' : 'neg';
  const isTrailing = sl != null && avg_cost < sl;
  const filled     = calcFilled(sl, target, ltp, avg_cost);

  return `
  <tr class="sc-row ${rowCls}" data-detail="detail-${idx}">
    <td>
      <span class="sc-sym">${symbol}${isTrailing ? '<span class="trailing-pill">T</span>' : ''}</span>
      <span class="badge badge-${status.cls} sc-inline-badge">${status.label}</span>
    </td>
    <td class="sc-val">${INR(avg_cost)}</td>
    <td><span class="sc-val">${INR(ltp)}</span> <span class="sc-day ${dayDir}">${dayArrow} ${PCT(day_chg_pct)}</span></td>
    <td><span class="sc-pnl ${pnlCls}">${INR(pnl)}</span> <span class="sc-day ${pnlCls}">(${KPCT(net_chg_pct)})</span></td>
    <td class="sc-val">${INR(invested)}</td>
    <td class="sc-pos-cell"><div class="pos-dots">${buildDotHtml(filled)}</div></td>
  </tr>`;
}

function renderDetailRow(holding, alert, tradeInfo, idx) {
  const { qty, avg_cost, ltp, invested, day_chg_pct } = holding;
  const sl     = alert?.sl     ?? null;
  const target = alert?.target ?? null;
  const name   = alert?.name   ?? holding.symbol;

  const status = computeStatus(ltp, sl, target, day_chg_pct);
  const rec    = buildRecommendation(status, ltp, sl, target, day_chg_pct, avg_cost);
  const { nEntries, firstDate, strategy } = tradeInfo;
  const daysIn = firstDate ? daysAgo(firstDate) : '—';

  return `
  <tr class="sc-detail-row" id="detail-${idx}">
    <td colspan="6">
      <div class="sc-detail-panel">
        <div class="sc-detail-top">
          <span class="sc-detail-name">${name}</span>
          <span class="pos-dots-stat">${qty} shares · ${daysIn} · ${strategy}</span>
        </div>
        <div class="pos-dots-stat" style="margin-bottom:8px">${dotStatLine(sl, target, ltp, avg_cost)}</div>
        <div class="sc-detail-meta">
          <span class="trade-chip">${nEntries} ${nEntries === 1 ? 'entry' : 'entries'}</span>
          ${firstDate ? `<span class="trade-chip">First buy <strong>${firstDate}</strong></span>` : ''}
          <span class="trade-chip">Invested <strong>${INR(invested)}</strong></span>
        </div>
        <div class="rec rec-${rec.cls}">${rec.text}</div>
      </div>
    </td>
  </tr>`;
}

// ── Page init ─────────────────────────────────────────────────────────────────

export async function init() {
  try {
    const [alertsData, portfolioData, tradebookData] = await Promise.all([
      loadJSON('alerts.json'),
      loadJSON('portfolio.json'),
      loadJSON('tradebook.json'),
    ]);

    const alerts    = alertsData.instruments.filter(a => a.status === 'enabled');
    const triggered = alertsData.triggered ?? [];
    const holdings  = portfolioData.holdings;
    const trades    = tradebookData.trades;

    // ── Summary KPIs
    const totalInvested = holdings.reduce((s, h) => s + h.invested, 0);
    const totalValue    = holdings.reduce((s, h) => s + h.cur_val,  0);
    const totalPnl      = holdings.reduce((s, h) => s + h.pnl,      0);
    const totalPnlPct   = totalInvested > 0 ? (totalPnl / totalInvested * 100) : 0;

    setEl('kpi-invested', INR(totalInvested));
    setEl('kpi-value',    INR(totalValue));
    setEl('kpi-pnl',      INR(totalPnl));
    setEl('kpi-pnl-pct',  KPCT(totalPnlPct));
    document.getElementById('kpi-pnl').className     = 'kpi-val ' + (totalPnl >= 0 ? 'pos' : 'neg');
    document.getElementById('kpi-pnl-pct').className = 'kpi-sub ' + (totalPnl >= 0 ? 'pos' : 'neg');
    setEl('last-updated', `Updated: ${portfolioData.last_updated}`);

    // ── Status counts
    const statuses = holdings.map(h => {
      const a = alerts.find(x => x.symbol === h.symbol);
      return computeStatus(h.ltp, a?.sl ?? null, a?.target ?? null, h.day_chg_pct);
    });
    const urgentCnt = statuses.filter(s => ['urgent','sl-breach'].includes(s.code)).length;
    const watchCnt  = statuses.filter(s => ['near-sl','watch','in-range-lower'].includes(s.code)).length;
    const noSlCnt   = statuses.filter(s => s.code === 'no-sl').length;

    const strip = document.getElementById('alert-strip');
    strip.innerHTML = `
      <span class="badge badge-${urgentCnt > 0 ? 'err' : 'neu'}">${urgentCnt} urgent</span>
      <span class="badge badge-${watchCnt  > 0 ? 'warn' : 'neu'}">${watchCnt} watch</span>
      <span class="badge badge-${noSlCnt   > 0 ? 'warn' : 'neu'}">${noSlCnt} no SL</span>
      <span class="strip-spacer"></span>
      <span class="strip-info">${holdings.length} active positions · ${alerts.length} alert configs</span>`;

    const statusLabel = urgentCnt > 0 ? `${urgentCnt} Urgent` : watchCnt > 0 ? `${watchCnt} Watch` : 'All Clear';
    const statusCls   = urgentCnt > 0 ? 'neg' : watchCnt > 0 ? 'warn-col' : 'pos';
    setEl('kpi-status', statusLabel);
    setEl('kpi-status-sub', `${watchCnt} watch · ${noSlCnt} no SL`);
    document.getElementById('kpi-status').className = 'kpi-val ' + statusCls;

    // ── Sort by urgency
    const sorted = [...holdings].sort((a, b) => {
      const aa = alerts.find(x => x.symbol === a.symbol);
      const ba = alerts.find(x => x.symbol === b.symbol);
      return urgencyScore(a, aa) - urgencyScore(b, ba);
    });

    // ── Render table rows
    const tbody = document.getElementById('scenarios-grid');
    tbody.innerHTML = sorted.map((h, idx) => {
      const alert      = alerts.find(a => a.symbol === h.symbol);
      const instTrades = trades
        .filter(t => t.symbol === h.symbol)
        .sort((a, b) => a.trade_time.localeCompare(b.trade_time));
      const tradeInfo  = analyseeTrades(instTrades);
      return renderRow(h, alert, tradeInfo, idx) + renderDetailRow(h, alert, tradeInfo, idx);
    }).join('');

    // ── Row expand / collapse
    tbody.addEventListener('click', e => {
      const row = e.target.closest('.sc-row');
      if (!row) return;
      const detailRow = document.getElementById(row.dataset.detail);
      if (!detailRow) return;
      const isOpen = detailRow.classList.contains('open');
      detailRow.classList.toggle('open', !isOpen);
      const chevron = row.querySelector('.sc-chevron');
      if (chevron) chevron.classList.toggle('open', !isOpen);
    });

    // ── Triggered chips
    const tGrid = document.getElementById('triggered-grid');
    tGrid.innerHTML = triggered.map(t => `
      <div class="triggered-chip">
        <strong>${t.symbol}</strong>
        <span>${t.alert_name}</span>
        <span class="tc-price">${t.sl ? `SL ${INR(t.sl)}` : ''}${t.target ? ` TGT ${INR(t.target)}` : ''}</span>
        · ${t.created_on}
      </div>`).join('') || '<span style="color:var(--t4);font-size:12px">None</span>';

  } catch (err) {
    console.error('[equity-scenarios]', err);
    document.getElementById('scenarios-grid').innerHTML =
      `<tr><td colspan="6" class="load-err">Failed to load data: ${err.message}</td></tr>`;
  }
}

function setEl(id, html) {
  const el = document.getElementById(id);
  if (el) el.innerHTML = html;
}

// init() is called by fno/main.js via _sectionLoaders when the section is activated
