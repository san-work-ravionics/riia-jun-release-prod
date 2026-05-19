import { api } from './api.js';
import { DS_C } from './utils.js';
import { mkChart } from '../shared/charts.js';

const C = DS_C;

export async function loadTradeDiagnostics() {
  const wrap = document.getElementById('trade-diag-wrap');
  if (!wrap) return;
  wrap.innerHTML = '<div class="empty">Loading…</div>';
  try {
    const [bRows, mRows] = await Promise.all([
      api('/api/v1/experience/rita/backtest-daily'),
      api('/api/v1/market-signals?timeframe=daily&periods=2000'),
    ]);
    if (!bRows?.length) {
      wrap.innerHTML = '<div class="empty">No backtest data found — run the pipeline first.</div>';
      return;
    }

    const sigMap = {};
    (mRows || []).forEach(r => { if (r.date) sigMap[r.date.slice(0, 10)] = r; });

    const changes = [];
    for (let i = 1; i < bRows.length; i++) {
      const prev = bRows[i - 1], cur = bRows[i];
      const pa = parseFloat(prev.allocation) || 0;
      const ca = parseFloat(cur.allocation) || 0;
      if (Math.abs(ca - pa) < 0.01) continue;
      const sig = sigMap[cur.date.slice(0, 10)] || {};
      const close = parseFloat(cur.close_price) || 0;
      const atrRaw = parseFloat(sig.atr_14);
      const atrPct = (!isNaN(atrRaw) && close) ? (atrRaw / close * 100) : NaN;
      const type = ca > pa ? 'open' : ca === 0 ? 'close' : 'adjust';
      changes.push({
        idx: i, date: cur.date,
        fromAlloc: pa, toAlloc: ca, type, close,
        rsi: parseFloat(sig.rsi_14), macd: parseFloat(sig.macd),
        macdSig: parseFloat(sig.macd_signal), atrPct,
        trend: parseFloat(sig.trend_score), bbPct: parseFloat(sig.bb_pct_b),
        holdDays: null, returnPct: null,
      });
    }

    for (let i = 0; i < changes.length; i++) {
      const c = changes[i];
      if (c.type === 'close') continue;
      const next = changes[i + 1];
      if (next) {
        c.holdDays = next.idx - c.idx;
        const exitClose = parseFloat(bRows[next.idx].close_price) || 0;
        c.returnPct = c.close && exitClose ? (exitClose / c.close - 1) * c.toAlloc * 100 : null;
      }
    }

    const entries  = changes.filter(c => c.type !== 'close');
    const withRet  = entries.filter(c => c.returnPct !== null);
    const wins     = withRet.filter(c => c.returnPct > 0);
    const avgHold  = withRet.length ? (withRet.reduce((s, c) => s + (c.holdDays || 0), 0) / withRet.length) : 0;
    const avgRet   = withRet.length ? (withRet.reduce((s, c) => s + c.returnPct, 0) / withRet.length) : 0;
    const wr       = withRet.length ? (wins.length / withRet.length * 100) : 0;

    const wrColor  = wr >= 50 ? 'var(--build)' : 'var(--danger)';
    const retColor = avgRet >= 0 ? 'var(--build)' : 'var(--danger)';

    const kpiHtml = `
      <div class="kpi-row kpi-row-4" style="margin-bottom:16px">
        <div class="kpi"><div class="kpi-label">Total Decisions</div><div class="kpi-value">${entries.length}</div></div>
        <div class="kpi"><div class="kpi-label">Win Rate</div><div class="kpi-value" style="color:${wrColor}">${wr.toFixed(0)}%</div><div class="kpi-delta">${wins.length} of ${withRet.length} closed</div></div>
        <div class="kpi"><div class="kpi-label">Avg Hold</div><div class="kpi-value">${avgHold.toFixed(1)}d</div></div>
        <div class="kpi"><div class="kpi-label">Avg Return</div><div class="kpi-value" style="color:${retColor}">${(avgRet >= 0 ? '+' : '') + avgRet.toFixed(2)}%</div></div>
      </div>`;

    const fmtAlloc = v => `${Math.round(v * 100)}%`;
    const fmtRsi   = v => isNaN(v) ? '—' : `<span style="color:${v > 70 ? 'var(--danger)' : v < 30 ? 'var(--build)' : 'var(--t2)'}">${v.toFixed(1)}</span>`;
    const fmtAtr   = v => isNaN(v) ? '—' : `<span style="color:${v > 1.5 ? 'var(--danger)' : v < 0.8 ? 'var(--build)' : 'var(--t2)'}">${v.toFixed(2)}%</span>`;
    const fmtTrend = v => isNaN(v) ? '—' : `<span style="color:${v > 0.2 ? 'var(--build)' : v < -0.2 ? 'var(--danger)' : 'var(--t2)'}">${v.toFixed(2)}</span>`;
    const fmtBb    = v => isNaN(v) ? '—' : v.toFixed(2);
    const fmtRet   = (v, type) => {
      if (type === 'close') return '<span style="color:var(--t3)">exit</span>';
      if (v === null) return '<span style="color:var(--t3)">open</span>';
      const rc = v >= 0 ? 'var(--build)' : 'var(--danger)';
      return `<span style="color:${rc};font-weight:600">${v >= 0 ? '+' : ''}${v.toFixed(2)}%</span>`;
    };
    const changeTag = c => {
      if (c.type === 'open')   return `<span style="font-family:var(--fm);font-size:11px;padding:2px 7px;border-radius:3px;background:var(--build-bg);color:var(--build)">▲ ${fmtAlloc(c.fromAlloc)}→${fmtAlloc(c.toAlloc)}</span>`;
      if (c.type === 'close')  return `<span style="font-family:var(--fm);font-size:11px;padding:2px 7px;border-radius:3px;background:var(--danger-bg);color:var(--danger)">▼ ${fmtAlloc(c.fromAlloc)}→${fmtAlloc(c.toAlloc)}</span>`;
      return `<span style="font-family:var(--fm);font-size:11px;padding:2px 7px;border-radius:3px;background:var(--surface2);color:var(--t2)">⟳ ${fmtAlloc(c.fromAlloc)}→${fmtAlloc(c.toAlloc)}</span>`;
    };

    const tableHtml = `
      <div class="card">
        <div class="card-hdr">
          <span class="card-title">Allocation Changes with Market Signals</span>
          <span class="card-sub">${changes.length} changes · ${entries.length} entries/adjustments · ${changes.length - entries.length} exits</span>
        </div>
        <div class="tbl-wrap">
          <table>
            <thead><tr>
              <th>#</th><th>Date</th><th>Decision</th><th>Close</th>
              <th>RSI</th><th>ATR%</th><th>Trend</th><th>BB%</th>
              <th>Hold</th><th>Return</th>
            </tr></thead>
            <tbody>${changes.map((c, i) => {
              const rowBg = c.returnPct != null && c.type !== 'close'
                ? (c.returnPct >= 0 ? 'background:rgba(26,107,60,0.04)' : 'background:rgba(155,28,28,0.04)') : '';
              return `<tr style="${rowBg}">
                <td style="font-family:var(--fm);color:var(--t3)">${i + 1}</td>
                <td style="font-family:var(--fm)">${c.date}</td>
                <td>${changeTag(c)}</td>
                <td style="font-family:var(--fm)">${c.close ? c.close.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—'}</td>
                <td>${fmtRsi(c.rsi)}</td>
                <td>${fmtAtr(c.atrPct)}</td>
                <td>${fmtTrend(c.trend)}</td>
                <td style="font-family:var(--fm)">${fmtBb(c.bbPct)}</td>
                <td style="font-family:var(--fm)">${c.holdDays !== null ? c.holdDays : '—'}</td>
                <td>${fmtRet(c.returnPct, c.type)}</td>
              </tr>`;
            }).join('')}
            </tbody>
          </table>
        </div>
      </div>`;

    const chartHtml = `
      <div class="chart-wrap">
        <div class="chart-title">NIFTY Close Price &amp; Allocation</div>
        <div class="chart-box h260"><canvas id="chart-diag-price"></canvas></div>
      </div>`;

    wrap.innerHTML = kpiHtml + chartHtml + tableHtml;

    mkChart('chart-diag-price',
      {
        type: 'bar',
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
          plugins: { legend: { labels: { font: { family: "'IBM Plex Mono'", size: 10 } } } },
          interaction: { mode: 'index', intersect: false },
          scales: {
            x:  { grid: { display: false }, ticks: { maxTicksLimit: 10 } },
            yP: { position: 'left',  grid: { color: 'rgba(0,0,0,.04)' }, ticks: { callback: v => v.toFixed(0) } },
            yA: { position: 'right', min: 0, max: 100, grid: { display: false }, ticks: { callback: v => v + '%' } },
          }
        }
      }
    );

  } catch (e) {
    wrap.innerHTML = `<div class="empty">Error loading diagnostics: ${e.message}</div>`;
  }
}
