// ── Health / Status ────────────────────────────────────────
import { api } from './api.js';
import { fmt, fmtPct, setEl } from './utils.js';
import { mkChart, C } from './charts.js';
import { createCache } from '../shared/api-cache.js';
import { t } from '../shared/i18n.js';

const cachedApi = createCache(api);

export async function loadHealth() {
  try {
    const d = await cachedApi('/health', 15000);
    const dot = document.getElementById('status-dot');
    const txt = document.getElementById('status-text');
    dot.className = 'status-dot ok';
    txt.textContent = d.model_exists ? t('health.model_loaded') : t('health.api_online');

    // Sidebar footer
    setEl('sb-model-info', d.model_exists
      ? `Model: ${d.model_age_days}d old`
      : 'Model: not trained');

    // Model status card
    setEl('model-badge', d.model_exists ? t('health.model_loaded') : t('health.missing'));
    document.getElementById('model-badge').className = 'badge ' + (d.model_exists ? 'ok' : 'warn');
    setEl('model-details', `
      <div style="display:flex;flex-direction:column;gap:5px;font-size:12px;color:var(--t2)">
        <div style="display:flex;justify-content:space-between"><span>${t('health.model_file')}</span><span class="badge ${d.model_exists ? 'ok' : 'err'}">${d.model_exists ? t('health.present') : t('health.missing')}</span></div>
        <div style="display:flex;justify-content:space-between"><span>${t('health.age')}</span><span style="font-family:var(--fm)">${d.model_age_days != null ? d.model_age_days + ' days' : '—'}</span></div>
        <div style="display:flex;justify-content:space-between"><span>${t('health.last_run')}</span><span style="font-family:var(--fm);font-size:11px">${d.last_pipeline_run || '—'}</span></div>
        <div style="display:flex;justify-content:space-between"><span>${t('health.csv_loaded')}</span><span class="badge ${d.csv_loaded ? 'ok' : 'err'}">${d.csv_loaded ? t('status.active') : t('ui.no_data')}</span></div>
      </div>
    `);

    // Data freshness
    const fresh = d.data_freshness || {};
    const daysOld = fresh.days_since_latest;
    const freshOk = daysOld != null && daysOld < 30;
    document.getElementById('data-badge').className = 'badge ' + (freshOk ? 'ok' : 'warn');
    setEl('data-badge', freshOk ? t('status.active') : (daysOld != null ? daysOld + 'd old' : '—'));
    setEl('data-details', `
      <div style="display:flex;flex-direction:column;gap:5px;font-size:12px;color:var(--t2)">
        <div style="display:flex;justify-content:space-between"><span>${t('health.latest_date')}</span><span style="font-family:var(--fm)">${fresh.latest_date || '—'}</span></div>
        <div style="display:flex;justify-content:space-between"><span>${t('health.days_old')}</span><span style="font-family:var(--fm)">${daysOld != null ? daysOld : '—'}</span></div>
        <div style="display:flex;justify-content:space-between"><span>${t('kpi.regime')}</span><span class="badge ${freshOk ? 'ok' : 'warn'}">${fresh.status || '—'}</span></div>
      </div>
    `);

    // Sharpe trend sparkline
    const trendWrap = document.getElementById('sharpe-trend-wrap');
    if (d.sharpe_trend_last5 && d.sharpe_trend_last5.length > 1) {
      if (trendWrap) { trendWrap.style.display = ''; trendWrap.innerHTML = ''; }
      requestAnimationFrame(() => mkChart('chart-sharpe-trend', {
        type: 'line',
        data: {
          labels: d.sharpe_trend_last5.map((_, i) => 'R' + (i + 1)),
          datasets: [{
            data: d.sharpe_trend_last5,
            borderColor: C.run,
            backgroundColor: 'rgba(0,86,184,0.08)',
            fill: true,
            tension: 0.3,
            pointRadius: 4,
            pointBackgroundColor: C.run,
            borderWidth: 2,
          }]
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: {
            x: { grid: { color: 'rgba(0,0,0,.04)' } },
            y: { grid: { color: 'rgba(0,0,0,.04)' }, ticks: { callback: v => v.toFixed(3) } }
          }
        }
      }));
    } else if (trendWrap) {
      trendWrap.style.display = '';
      trendWrap.innerHTML = `<span style="font-size:11px;color:var(--t3)">${t('health.not_enough_runs')}</span>`;
    }
  } catch (e) {
    const dot = document.getElementById('status-dot');
    dot.className = 'status-dot err';
    document.getElementById('status-text').textContent = t('health.api_offline');
  }
}

export async function loadPerfSummary() {
  try {
    const d = await cachedApi('/api/v1/performance-summary', 120000);
    const activeInst = (d._active_instrument_id || 'this instrument').toUpperCase();
    const stale = d._run_instrument_id && d._active_instrument_id &&
                  d._run_instrument_id !== d._active_instrument_id;
    if (stale) {
      ['kpi-return','kpi-cagr','kpi-sharpe','kpi-mdd','kpi-winrate'].forEach(id => {
        setEl(id, '—');
        const el = document.getElementById(id);
        if (el) el.className = 'kpi-value';
      });
      setEl('kpi-bnh', `No ${activeInst} results yet`);
      setEl('kpi-cagr-bnh', '');
      setEl('kpi-days', `Run pipeline for ${activeInst}`);
      return;
    }
    // No completed backtest data for this instrument
    if (d.portfolio_total_return_pct == null) {
      ['kpi-return','kpi-cagr','kpi-sharpe','kpi-mdd','kpi-winrate'].forEach(id => {
        setEl(id, '—');
        const el = document.getElementById(id);
        if (el) el.className = 'kpi-value';
      });
      setEl('kpi-bnh', `No ${activeInst} backtest yet`);
      setEl('kpi-cagr-bnh', '');
      setEl('kpi-days', `Run pipeline for ${activeInst}`);
      if (document.getElementById('constraints-badge')) {
        document.getElementById('constraints-badge').className = 'badge warn';
        setEl('constraints-badge', 'No Data');
        setEl('constraints-details', '');
      }
      return;
    }

    setEl('kpi-return', fmtPct(d.portfolio_total_return_pct));
    document.getElementById('kpi-return').className = 'kpi-value ' + (parseFloat(d.portfolio_total_return_pct) > 0 ? 'pos' : 'neg');
    setEl('kpi-bnh', `vs B&H ${fmtPct(d.benchmark_total_return_pct)}`);
    setEl('kpi-cagr', fmtPct(d.portfolio_cagr_pct));
    setEl('kpi-cagr-bnh', `B&H ${fmtPct(d.benchmark_cagr_pct)}`);
    setEl('kpi-sharpe', fmt(d.sharpe_ratio, 3));
    document.getElementById('kpi-sharpe').className = 'kpi-value ' + (parseFloat(d.sharpe_ratio) >= 1 ? 'pos' : 'neg');
    setEl('kpi-mdd', fmtPct(d.max_drawdown_pct));
    document.getElementById('kpi-mdd').className = 'kpi-value ' + (Math.abs(parseFloat(d.max_drawdown_pct)) < 10 ? 'pos' : 'neg');
    setEl('kpi-winrate', fmtPct(d.win_rate_pct));
    setEl('kpi-days', `${d.total_days} days`);
    if (d.backtest_start_date && d.backtest_end_date) {
      setEl('kpi-bt-range', `${d.backtest_start_date} → ${d.backtest_end_date}`);
      setEl('kpi-bt-days', `${d.total_days} days`);
    }

    // Re-render constraints using the same performance data that drives the KPIs.
    // loadMetrics() may use a different (stale) source — performance-summary wins.
    const sharpe = parseFloat(d.sharpe_ratio);
    const mdd    = parseFloat(d.max_drawdown_pct);
    const cagr   = parseFloat(d.portfolio_cagr_pct);
    const sharpeOk = !isNaN(sharpe) && sharpe >= 1;
    const mddOk    = !isNaN(mdd)    && Math.abs(mdd) < 10;
    const allMet   = sharpeOk && mddOk;
    if (document.getElementById('constraints-badge')) {
      document.getElementById('constraints-badge').className = 'badge ' + (allMet ? 'ok' : 'err');
      setEl('constraints-badge', allMet ? t('health.all_met') : t('health.not_met'));
      setEl('constraints-details', `
        <div style="display:flex;flex-direction:column;gap:5px;font-size:12px;color:var(--t2)">
          <div style="display:flex;justify-content:space-between"><span>${t('health.sharpe_gate')}</span><span class="badge ${sharpeOk ? 'ok' : 'err'}">${sharpeOk ? t('health.all_met') : t('health.not_met')}</span></div>
          <div style="display:flex;justify-content:space-between"><span>${t('health.mdd_gate')}</span><span class="badge ${mddOk ? 'ok' : 'err'}">${mddOk ? t('health.all_met') : t('health.not_met')}</span></div>
          <div style="display:flex;justify-content:space-between"><span>${t('health.cagr')}</span><span style="font-family:var(--fm)">${fmtPct(isNaN(cagr) ? null : cagr)}</span></div>
          <div style="display:flex;justify-content:space-between"><span>${t('health.total_days')}</span><span style="font-family:var(--fm)">${d.total_days || '—'}</span></div>
        </div>
      `);
    }
  } catch (e) { /* performance data not yet available */ }
}

export async function loadDrift() {
  try {
    const d = await api('/api/v1/drift');
    const h = (d.summary && d.summary.overall) || 'unknown';
    const cls = h === 'ok' ? 'ok' : h === 'warn' ? 'warn' : 'err';
    const alerts = [];
    const r = d.checks || {};
    if (r.sharpe_drift) alerts.push({ cls: r.sharpe_drift.status === 'ok' ? 'ok' : 'warn', msg: 'Sharpe drift: ' + r.sharpe_drift.message, tag: r.sharpe_drift.status });
    if (r.return_degradation) alerts.push({ cls: r.return_degradation.status === 'ok' ? 'ok' : 'warn', msg: 'Return trend: ' + r.return_degradation.message, tag: r.return_degradation.status });
    if (r.data_freshness) alerts.push({ cls: r.data_freshness.status === 'ok' ? 'ok' : 'warn', msg: 'Data: ' + r.data_freshness.message, tag: r.data_freshness.status });
    if (r.pipeline_health) alerts.push({ cls: r.pipeline_health.status === 'ok' ? 'ok' : 'warn', msg: 'Pipeline: ' + r.pipeline_health.message, tag: r.pipeline_health.status });

    setEl('home-alerts', alerts.length ? `
      <div class="alert-strip">
        ${alerts.map(a => `
          <div class="alert-row ${a.cls}">
            <span class="alert-icon">${a.cls === 'ok' ? '✓' : '⚠'}</span>
            <span class="alert-msg">${a.msg}</span>
            <span class="alert-tag">${a.tag}</span>
          </div>
        `).join('')}
      </div>` : '');
  } catch (e) { }
}

export async function loadProgress() {
  try {
    const d = await api('/progress');
    const steps = d.steps || [];
    steps.forEach((s, i) => {
      const el = document.getElementById('seg-' + (i + 1));
      if (el) {
        el.classList.remove('done', 'active');
        if (s.status === 'completed') el.classList.add('done');
        else if (s.status === 'in_progress') el.classList.add('active');
      }
    });
  } catch (e) { }
}
