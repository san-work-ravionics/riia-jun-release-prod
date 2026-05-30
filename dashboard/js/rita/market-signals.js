// ── Market Signals ─────────────────────────────────────────
import { api } from './api.js';
import { setEl } from './utils.js';
import { mkChart, C } from './charts.js';
import { loadOverviewCommentary } from './commentary.js';
import { t } from '../shared/i18n.js';

let _msTimeframe = 'daily';

function _getInstrument() {
  return (localStorage.getItem('ritaInstrument') || 'NIFTY').toUpperCase();
}

/** Update the trailing-return hint on the Financial Goal section. */
export async function loadGoalHint() {
  try {
    const inst = _getInstrument();
    const rows = await api(`/api/v1/market-signals?timeframe=daily&periods=252&instrument=${inst}`);
    if (!rows || rows.length < 2) return;
    const first = rows[0], last = rows[rows.length - 1];
    const ret12m = ((parseFloat(last.Close) / parseFloat(first.Close)) - 1) * 100;
    const hint = document.getElementById('historical-avg-hint');
    if (hint && !isNaN(ret12m)) {
      hint.textContent = `${inst} last 12 months (${first.date} → ${last.date}): ${ret12m.toFixed(1)}%`;
    }
  } catch (_) {}
}

export function switchMsTab(tf) {
  _msTimeframe = tf;
  ['daily','weekly','monthly'].forEach(t => {
    const el = document.getElementById('tab-' + t);
    if (el) el.classList.toggle('active', t === tf);
  });
  loadMarketSignals();
}

export async function loadMarketSignals() {
  const periods = _msTimeframe === 'monthly' ? 60 : _msTimeframe === 'weekly' ? 104 : 252;
  const inst = _getInstrument();
  setEl('ms-data-range', `Loading ${inst}…`);
  try {
    const rows = await api(`/api/v1/market-signals?timeframe=${_msTimeframe}&periods=${periods}&instrument=${inst}`);
    if (!rows || !rows.length) {
      setEl('ms-data-range', `No data available for ${inst}`);
      setEl('ms-last-updated', '—');
      return;
    }

    const last = rows[rows.length - 1];
    const dates = rows.map(r => r.date);

    // ── Data range label ────────────────────────────────────
    const firstDate = rows.find(r => r.date)?.date || '—';
    const tfLabel = _msTimeframe === 'monthly' ? t('ms.timeframe_monthly') : _msTimeframe === 'weekly' ? t('ms.timeframe_weekly') : t('ms.timeframe_daily');
    setEl('ms-data-range', `${tfLabel} · ${firstDate} → ${last.date || '—'} &nbsp;|&nbsp; ${rows.length} bars`);
    const _luRaw = last.date ? new Date(last.date + 'T00:00:00') : null;
    setEl('ms-last-updated', (_luRaw && !isNaN(_luRaw.getTime()))
      ? 'Last updated: ' + _luRaw.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
        + ' ' + _luRaw.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
      : '—');
    const pvSub = document.getElementById('ms-pv-subtitle');
    if (pvSub) pvSub.textContent = `— close price · ${tfLabel.toLowerCase()} volume`;

    // x-axis tick formatter — monthly shows "YYYY-MM", weekly shows "MM-DD", daily shows "MM-DD"
    const _xFmt = _msTimeframe === 'monthly'
      ? (v) => typeof v === 'string' ? v.slice(0, 7) : v
      : (v) => typeof v === 'string' ? v.slice(5)    : v;
    const _xTicks = _msTimeframe === 'monthly' ? 12 : _msTimeframe === 'weekly' ? 16 : 12;

    // ── Signal summary KPIs ─────────────────────────────────
    const rsi = parseFloat(last.rsi_14);
    setEl('ms-rsi-val', isNaN(rsi) ? '—' : rsi.toFixed(1));
    document.getElementById('ms-rsi-val').className = 'kpi-value ' + (rsi > 60 ? 'neg' : rsi < 30 ? 'pos' : 'neu');
    setEl('ms-rsi-sig', rsi > 60 ? t('ms.overbought') : rsi < 30 ? t('ms.oversold') : t('ms.neutral'));

    const macdVal = parseFloat(last.macd);
    const sigVal  = parseFloat(last.macd_signal);
    const macdBull = macdVal > sigVal;
    setEl('ms-macd-val', isNaN(macdVal) ? '—' : macdVal.toFixed(2));
    document.getElementById('ms-macd-val').className = 'kpi-value ' + (macdBull ? 'pos' : 'neg');
    setEl('ms-macd-sig', macdBull ? t('ms.bullish_crossover') : t('ms.bearish_crossover'));

    const bbPct = parseFloat(last.bb_pct_b);
    setEl('ms-bb-val', isNaN(bbPct) ? '—' : bbPct.toFixed(2));
    document.getElementById('ms-bb-val').className = 'kpi-value ' + (bbPct > 0.8 ? 'neg' : bbPct < 0.2 ? 'pos' : 'neu');
    setEl('ms-bb-sig', bbPct > 0.8 ? t('ms.near_upper_band') : bbPct < 0.2 ? t('ms.near_lower_band') : t('ms.mid_band'));

    const price  = parseFloat(last.Close);
    const ema5   = parseFloat(last.ema_5);
    const ema13  = parseFloat(last.ema_13);
    const ema26  = parseFloat(last.ema_26);
    const abv5   = price > ema5;
    const abv13  = price > ema13;
    const abv26  = price > ema26;
    setEl('ms-ema5-val',  isNaN(ema5)  ? '—' : ema5.toFixed(0));
    document.getElementById('ms-ema5-val').className  = 'kpi-value ' + (abv5  ? 'pos' : 'neg');
    setEl('ms-ema5-sig',  abv5  ? t('ms.above_ema5')  : t('ms.below_ema5'));
    setEl('ms-ema13-val', isNaN(ema13) ? '—' : ema13.toFixed(0));
    document.getElementById('ms-ema13-val').className = 'kpi-value ' + (abv13 ? 'pos' : 'neg');
    setEl('ms-ema13-sig', abv13 ? t('ms.above_ema13') : t('ms.below_ema13'));
    setEl('ms-ema26-val', isNaN(ema26) ? '—' : ema26.toFixed(0));
    document.getElementById('ms-ema26-val').className = 'kpi-value ' + (abv26 ? 'pos' : 'neg');
    setEl('ms-ema26-sig', abv26 ? t('ms.above_ema26') : t('ms.below_ema26'));

    // Update historical avg hint on the Financial Goal section
    const histHint = document.getElementById('historical-avg-hint');
    if (histHint && rows.length >= 2 && _msTimeframe === 'daily') {
      const ret12m = ((parseFloat(last.Close) / parseFloat(rows[0].Close)) - 1) * 100;
      if (!isNaN(ret12m))
        histHint.textContent = `${inst} last 12 months (${rows[0].date} → ${last.date}): ${ret12m.toFixed(1)}%`;
    }

    const atrRaw  = parseFloat(last.atr_14);
    const atrPct  = (!isNaN(atrRaw) && price) ? (atrRaw / price * 100) : NaN;
    setEl('ms-atr-val', isNaN(atrPct) ? '—' : atrPct.toFixed(2) + '%');
    document.getElementById('ms-atr-val').className = 'kpi-value ' + (atrPct > 1.5 ? 'neg' : atrPct < 0.8 ? 'pos' : 'neu');
    setEl('ms-atr-sig', atrPct > 1.5 ? t('ms.high_volatility') : atrPct < 0.8 ? t('ms.compressed') : t('ms.normal_range'));

    const trendVal = parseFloat(last.trend_score);
    setEl('ms-trend-val', isNaN(trendVal) ? '—' : trendVal.toFixed(2));
    document.getElementById('ms-trend-val').className = 'kpi-value ' + (trendVal > 0.2 ? 'pos' : trendVal < -0.2 ? 'neg' : 'neu');
    setEl('ms-trend-sig', trendVal > 0.5 ? t('ms.strong_uptrend') : trendVal > 0.2 ? t('ms.mild_uptrend') : trendVal < -0.5 ? t('ms.strong_downtrend') : trendVal < -0.2 ? t('ms.mild_downtrend') : t('ms.sideways'));

    // ── Price + Volume chart ────────────────────────────────
    mkChart('chart-ms-pv', {
      type: 'bar',
      data: {
        labels: dates,
        datasets: [
          { type: 'line', label: 'Close', data: rows.map(r => r.Close),
            borderColor: C.run, backgroundColor: 'transparent',
            pointRadius: 0, borderWidth: 2, yAxisID: 'yPrice', order: 1 },
          { type: 'bar', label: 'Volume', data: rows.map(r => r.Volume),
            backgroundColor: 'rgba(0,86,184,0.18)', borderWidth: 0,
            yAxisID: 'yVol', order: 2 },
        ]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { position: 'top', labels: { font: { size: 11 } } } },
        scales: {
          x: { grid: { display: false }, ticks: { maxTicksLimit: _xTicks, callback: _xFmt, font: { family: C.mono, size: 10 } } },
          yPrice: { position: 'left',  grid: { color: 'rgba(0,0,0,.04)' }, ticks: { callback: v => v.toFixed(0), font: { family: C.mono, size: 10 } } },
          yVol:   { position: 'right', grid: { display: false }, ticks: { callback: v => v >= 1e7 ? (v/1e7).toFixed(0)+'Cr' : v >= 1e5 ? (v/1e5).toFixed(0)+'L' : v, font: { family: C.mono, size: 10 } } },
        }
      }
    });

    // ── Alerts strip ────────────────────────────────────────
    const alerts = [];
    const mkAlert = (cls, txt) => `<span class="badge ${cls}" style="font-size:11px;padding:4px 10px">${txt}</span>`;

    // RSI
    if      (rsi > 60)       alerts.push(mkAlert('err',  `RSI Overbought ${rsi.toFixed(1)}`));
    else if (rsi > 55)       alerts.push(mkAlert('warn', `RSI Approaching OB ${rsi.toFixed(1)}`));
    else if (rsi < 30)       alerts.push(mkAlert('ok',   `RSI Oversold ${rsi.toFixed(1)}`));
    else if (rsi < 40)       alerts.push(mkAlert('warn', `RSI Approaching OS ${rsi.toFixed(1)}`));

    // MACD
    if      (macdBull)       alerts.push(mkAlert('ok',  t('ms.macd_bullish')));
    else                     alerts.push(mkAlert('err', t('ms.macd_bearish')));

    // BB
    if      (bbPct > 0.8)    alerts.push(mkAlert('err',  `BB Near Upper Band ${bbPct.toFixed(2)}`));
    else if (bbPct < 0.2)    alerts.push(mkAlert('ok',   `BB Near Lower Band ${bbPct.toFixed(2)}`));

    // EMA 5 vs EMA 13 current state
    const curEma5 = parseFloat(last.ema_5), curEma13 = parseFloat(last.ema_13);
    if (!isNaN(curEma5) && !isNaN(curEma13)) {
      if   (curEma5 > curEma13) alerts.push(mkAlert('ok',  'EMA5 > EMA13 Bullish'));
      else                      alerts.push(mkAlert('err', 'EMA5 < EMA13 Bearish'));
    }

    // Price vs EMA26 trend
    if (!isNaN(ema26)) {
      if   (price > ema26) alerts.push(mkAlert('ok',  `Price > EMA26 Uptrend`));
      else                 alerts.push(mkAlert('err', `Price < EMA26 Downtrend`));
    }

    // ATR%
    if (!isNaN(atrPct)) {
      if      (atrPct > 1.5) alerts.push(mkAlert('err',  `ATR High Volatility ${atrPct.toFixed(2)}%`));
      else if (atrPct < 0.8) alerts.push(mkAlert('ok',   `ATR Compressed ${atrPct.toFixed(2)}%`));
    }

    // Trend Score
    if (!isNaN(trendVal)) {
      if      (trendVal >  0.5) alerts.push(mkAlert('ok',  `Trend Strong Uptrend ${trendVal.toFixed(2)}`));
      else if (trendVal >  0.2) alerts.push(mkAlert('ok',  `Trend Mild Uptrend ${trendVal.toFixed(2)}`));
      else if (trendVal < -0.5) alerts.push(mkAlert('err', `Trend Strong Downtrend ${trendVal.toFixed(2)}`));
      else if (trendVal < -0.2) alerts.push(mkAlert('err', `Trend Mild Downtrend ${trendVal.toFixed(2)}`));
      else                      alerts.push(mkAlert('neu', `Trend Sideways ${trendVal.toFixed(2)}`));
    }

    document.getElementById('ms-alerts').innerHTML = alerts.length
      ? alerts.join('')
      : mkAlert('neu', t('ms.no_signals'));

    loadGeoPanels();
    loadOverviewCommentary();

  } catch (e) {
    console.warn('market signals error', e);
    setEl('ms-loading', `<div class="empty" style="color:var(--danger)">Error: ${e.message}</div>`);
    document.getElementById('ms-loading').style.display = '';
    setEl('ms-last-updated', '—');
  }
}

const _GEO_REGION_NAMES = { India: 'India', US: 'United States', EU: 'Europe' };
const _GEO_INST_NAMES  = { 'Dow Jones Industrial Average': 'Dow Jones', 'Nasdaq Composite': 'Nasdaq' };

function _geoKpiClass(signal) {
  if (signal === 'bullish') return 'pos';
  if (signal === 'bearish') return 'neg';
  return 'neu';
}

export async function loadGeoPanels() {
  const container = document.getElementById('geo-panels');
  if (!container) return;
  try {
    const res = await fetch('/api/v1/experience/rita/geography-overview');
    if (!res.ok) throw new Error(res.statusText);
    const data = await res.json();
    if (!data.regions || data.regions.length === 0) {
      container.innerHTML = '<div class="card"><div class="empty">No geography data configured</div></div>';
      return;
    }
    const activeId = localStorage.getItem('ritaInstrument') || 'NIFTY';
    container.innerHTML = data.regions.map(r => {
      const label = _GEO_REGION_NAMES[r.region] || r.region;
      const instruments = r.instruments || [];
      if (!instruments.length) return '';
      return `
        <div class="card">
          <div class="card-hdr">
            <span class="card-title">${label}</span>
          </div>
          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(80px,1fr));gap:6px;padding:4px 0">
            ${instruments.map(i => `
              <div class="kpi geo-kpi${i.id === activeId ? ' geo-kpi-active' : ''}"
                   style="padding:5px 6px" data-id="${i.id}"
                   onclick="selectGeoInstrument('${i.id}')">
                <div class="kpi-label" style="font-size:10px;font-weight:600;line-height:1.3;min-height:2.6em">${_GEO_INST_NAMES[i.name] || i.name}</div>
                <div class="kpi-value ${_geoKpiClass(i.signal)}" style="font-size:13px">${i.close != null ? i.close.toFixed(2) : '—'}</div>
                <div class="kpi-delta" style="font-size:10px">${i.signal.charAt(0).toUpperCase() + i.signal.slice(1)}</div>
              </div>
            `).join('')}
          </div>
        </div>
      `;
    }).filter(Boolean).join('');
  } catch (e) {
    container.innerHTML = '<div class="card"><div class="empty">—</div></div>';
  }
}
