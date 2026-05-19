// ── Trade Diagnostics ──────────────────────────────────────
import { api } from './api.js';
import { setEl } from './utils.js';
import { mkChart, C } from './charts.js';
import { createCache } from '../shared/api-cache.js';

const cachedApi = createCache(api);

export async function loadDiagnostics() {
  try {
    const [bRows, mRows] = await Promise.all([
      cachedApi('/api/v1/experience/rita/backtest-daily', 120000),
      api('/api/v1/market-signals?timeframe=daily&periods=2000'),
    ]);
    if (!bRows?.length) { setEl('diag-tbody', '<tr><td colspan="10" class="empty">No backtest data found — run the pipeline first.</td></tr>'); return; }

    // ── Build date→signal lookup ──────────────────────────
    const sigMap = {};
    (mRows || []).forEach(r => { if (r.date) sigMap[r.date.slice(0,10)] = r; });

    // ── Detect allocation-change rows ─────────────────────
    const changes = [];
    for (let i = 1; i < bRows.length; i++) {
      const prev = bRows[i-1], cur = bRows[i];
      const pa = parseFloat(prev.allocation) || 0;
      const ca = parseFloat(cur.allocation)  || 0;
      if (Math.abs(ca - pa) < 0.01) continue;

      const sig   = sigMap[cur.date.slice(0,10)] || {};
      const close = parseFloat(cur.close_price) || 0;
      const atrRaw = parseFloat(sig.atr_14);
      const atrPct = (!isNaN(atrRaw) && close) ? (atrRaw / close * 100) : NaN;
      const type   = ca > pa ? 'open' : ca === 0 ? 'close' : 'adjust';

      changes.push({
        idx:      i,
        date:     cur.date,
        fromAlloc: pa,
        toAlloc:   ca,
        type,
        close,
        rsi:      parseFloat(sig.rsi_14),
        macd:     parseFloat(sig.macd),
        macdSig:  parseFloat(sig.macd_signal),
        atrPct,
        trend:    parseFloat(sig.trend_score),
        bbPct:    parseFloat(sig.bb_pct_b),
        holdDays: null,
        returnPct: null,
      });
    }

    // ── Pair each open/adjust with the next change ────────
    for (let i = 0; i < changes.length; i++) {
      const c = changes[i];
      if (c.type === 'close') continue;
      const next = changes[i + 1];
      if (next) {
        c.holdDays  = next.idx - c.idx;
        const exitClose = parseFloat(bRows[next.idx].close_price) || 0;
        c.returnPct = c.close && exitClose ? (exitClose / c.close - 1) * c.toAlloc * 100 : null;
      }
    }

    // ── KPIs ─────────────────────────────────────────────
    const entries   = changes.filter(c => c.type !== 'close');
    const withRet   = entries.filter(c => c.returnPct !== null);
    const wins      = withRet.filter(c => c.returnPct > 0);
    const avgHold   = withRet.length ? (withRet.reduce((s,c) => s+(c.holdDays||0), 0) / withRet.length) : 0;
    const avgRet    = withRet.length ? (withRet.reduce((s,c) => s+c.returnPct, 0) / withRet.length) : 0;
    const wr        = withRet.length ? (wins.length / withRet.length * 100) : 0;

    setEl('diag-total', entries.length);
    const wrEl = document.getElementById('diag-wr');
    wrEl.textContent = wr.toFixed(0) + '%';
    wrEl.className = 'kpi-value ' + (wr >= 50 ? 'pos' : 'neg');
    setEl('diag-wr-sub', `${wins.length} of ${withRet.length} closed`);
    setEl('diag-hold', avgHold.toFixed(1) + 'd');
    const retEl = document.getElementById('diag-ret');
    retEl.textContent = (avgRet >= 0 ? '+' : '') + avgRet.toFixed(2) + '%';
    retEl.className = 'kpi-value ' + (avgRet >= 0 ? 'pos' : 'neg');

    // ── Price + Allocation chart ──────────────────────────
    mkChart('chart-diag-price', {
      data: {
        labels: bRows.map(r => r.date),
        datasets: [
          { type: 'line', label: 'NIFTY Close',
            data: bRows.map(r => parseFloat(r.close_price) || null),
            borderColor: C.run, backgroundColor: 'transparent',
            pointRadius: 0, borderWidth: 2, yAxisID: 'yP', order: 1 },
          { type: 'bar', label: 'Allocation %',
            data: bRows.map(r => (parseFloat(r.allocation) || 0) * 100),
            backgroundColor: bRows.map(r => {
              const a = parseFloat(r.allocation) || 0;
              return a >= 1 ? 'rgba(0,86,184,0.22)' : a >= 0.5 ? 'rgba(0,86,184,0.10)' : 'rgba(0,0,0,0.02)';
            }),
            borderWidth: 0, yAxisID: 'yA', order: 2 },
        ]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: { legend: { position: 'top', labels: { font: { size: 11 } } } },
        scales: {
          x:  { grid: { display: false }, ticks: { maxTicksLimit: 10, font: { family: C.mono, size: 10 } } },
          yP: { position: 'left',  grid: { color: 'rgba(0,0,0,.04)' }, ticks: { callback: v => v.toFixed(0), font: { family: C.mono, size: 10 } } },
          yA: { position: 'right', min: 0, max: 100, grid: { display: false }, ticks: { callback: v => v+'%', font: { family: C.mono, size: 10 } } },
        }
      }
    });

    // ── Trade table ───────────────────────────────────────
    const fmtAlloc = v => `${Math.round(v * 100)}%`;
    const fmtRsi   = v => isNaN(v) ? '—' : `<span style="color:${v>70?'var(--danger)':v<30?'var(--build)':'var(--t2)'}">${v.toFixed(1)}</span>`;
    const fmtAtr   = v => isNaN(v) ? '—' : `<span style="color:${v>1.5?'var(--danger)':v<0.8?'var(--build)':'var(--t2)'}">${v.toFixed(2)}%</span>`;
    const fmtTrend = v => isNaN(v) ? '—' : `<span style="color:${v>0.2?'var(--build)':v<-0.2?'var(--danger)':'var(--t2)'}">${v.toFixed(2)}</span>`;
    const fmtBb    = v => isNaN(v) ? '—' : v.toFixed(2);
    const fmtRet   = (v, type) => {
      if (type === 'close') return '<span style="color:var(--t3)">exit</span>';
      if (v === null)       return '<span style="color:var(--t3)">open</span>';
      const rc = v>=0?'var(--build)':'var(--danger)';
      return `<span style="color:${rc};font-weight:600">${v>=0?'+':''}${v.toFixed(2)}%</span>`;
    };
    const changeTag = c => {
      if (c.type === 'open')   return `<span style="font-family:var(--fm);font-size:11px;padding:2px 7px;border-radius:3px;background:var(--build-bg);color:var(--build)">▲ ${fmtAlloc(c.fromAlloc)}→${fmtAlloc(c.toAlloc)}</span>`;
      if (c.type === 'close')  return `<span style="font-family:var(--fm);font-size:11px;padding:2px 7px;border-radius:3px;background:var(--neg-bg);color:var(--danger)">▼ ${fmtAlloc(c.fromAlloc)}→${fmtAlloc(c.toAlloc)}</span>`;
      return `<span style="font-family:var(--fm);font-size:11px;padding:2px 7px;border-radius:3px;background:var(--surface2);color:var(--t2)">⟳ ${fmtAlloc(c.fromAlloc)}→${fmtAlloc(c.toAlloc)}</span>`;
    };
    const rowBg = c => {
      if (c.returnPct === null || c.type === 'close') return '';
      return c.returnPct >= 0 ? 'background:rgba(26,107,60,0.04)' : 'background:rgba(155,28,28,0.04)';
    };

    document.getElementById('diag-tbody').innerHTML = changes.map((c, i) => `
      <tr style="${rowBg(c)}">
        <td style="font-family:var(--fm);color:var(--t3)">${i+1}</td>
        <td style="font-family:var(--fm)">${c.date}</td>
        <td>${changeTag(c)}</td>
        <td style="font-family:var(--fm)">${c.close ? c.close.toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2}) : '—'}</td>
        <td>${fmtRsi(c.rsi)}</td>
        <td>${fmtAtr(c.atrPct)}</td>
        <td>${fmtTrend(c.trend)}</td>
        <td style="font-family:var(--fm)">${fmtBb(c.bbPct)}</td>
        <td style="font-family:var(--fm)">${c.holdDays !== null ? c.holdDays : '—'}</td>
        <td>${fmtRet(c.returnPct, c.type)}</td>
      </tr>`).join('');

    setEl('diag-table-sub', `${changes.length} allocation changes · ${entries.length} entries/adjustments · ${changes.length - entries.length} exits`);

  } catch(e) {
    console.warn('diagnostics error', e);
    setEl('diag-tbody', `<tr><td colspan="10" class="empty" style="color:var(--danger)">Error: ${e.message}</td></tr>`);
  }
}
