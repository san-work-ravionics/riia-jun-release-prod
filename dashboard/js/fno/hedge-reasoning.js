// ── Hedge Advisor — Agent Reasoning Cascade ───────────────────────────────────
import { api } from './api.js';
import { mkChart, C } from '../shared/charts.js';
import { state } from './state.js';

// Module-level typewriter cancel token — increment to cancel in-flight animations
let _twToken = 0;
let _payoffChart = null;

// ── Public API ────────────────────────────────────────────────────────────────

/**
 * Entry point — called by section loader when user navigates to hedge-advisor page.
 * Populates instrument dropdown, then auto-runs analysis.
 */
export async function loadHedgeAdvisor() {
  _populateDropdown();
  await haAnalyse();
}

/**
 * Run hedge reasoning analysis for the selected instrument.
 * Fetches API, then renders cascading typewriter steps.
 */
export async function haAnalyse() {
  // Cancel any in-flight typewriter cascade
  _twToken += 1;

  const select = document.getElementById('ha-instrument-select');
  const instrument = select ? select.value : 'ASML';

  _showLoading(true);
  _hideError();
  _hideResults();
  _showSkip(false);

  try {
    const data = await api(`/api/v1/experience/fno/hedge-reasoning?instrument=${encodeURIComponent(instrument)}`);
    if (!data || !data.steps || data.steps.length === 0) {
      _showError('No reasoning data returned for this instrument.');
      _showLoading(false);
      return;
    }
    _showLoading(false);
    _showResults(true);
    _showSkip(true);
    _renderCascade(data);
  } catch (e) {
    _showLoading(false);
    _showError(e.message || 'Failed to fetch hedge reasoning.');
  }
}

/**
 * Skip to verdict — cancel typewriter, render all steps instantly + chart.
 */
export function haSkipToVerdict() {
  _twToken += 1;
  const resultsEl = document.getElementById('ha-results');
  if (!resultsEl) return;
  if (!resultsEl._haData) return;
  _renderAllInstant(resultsEl._haData);
}

// ── Internal: Dropdown ────────────────────────────────────────────────────────

function _populateDropdown() {
  const select = document.getElementById('ha-instrument-select');
  if (!select) return;

  const instruments = (state.portfolioGeoInstruments && state.portfolioGeoInstruments.length > 0)
    ? state.portfolioGeoInstruments.map(i => i.id || i.name || i)
    : ['ASML', 'NIFTY', 'BANKNIFTY', 'NVIDIA'];

  select.innerHTML = instruments.map(inst =>
    `<option value="${inst}"${inst === 'ASML' ? ' selected' : ''}>${inst}</option>`
  ).join('');
}

// ── Internal: UI State ────────────────────────────────────────────────────────

function _showLoading(show) {
  const el = document.getElementById('ha-loading');
  if (el) el.style.display = show ? '' : 'none';
}

function _showError(msg) {
  const el = document.getElementById('ha-error');
  if (el) { el.textContent = msg; el.style.display = ''; }
}

function _hideError() {
  const el = document.getElementById('ha-error');
  if (el) { el.textContent = ''; el.style.display = 'none'; }
}

function _hideResults() {
  const el = document.getElementById('ha-results');
  if (el) el.style.display = 'none';
}

function _showResults(show) {
  const el = document.getElementById('ha-results');
  if (el) el.style.display = show ? '' : 'none';
}

function _showSkip(show) {
  const el = document.getElementById('ha-skip-btn');
  if (el) el.style.display = show ? '' : 'none';
}

// ── Internal: Cascade Renderer ────────────────────────────────────────────────

function _renderCascade(data) {
  const resultsEl = document.getElementById('ha-results');
  if (resultsEl) resultsEl._haData = data;

  // Set timestamp
  const tsEl = document.getElementById('ha-timestamp');
  if (tsEl) tsEl.textContent = data.timestamp ? new Date(data.timestamp).toLocaleString() : '';

  // Reset all steps to hidden
  for (let i = 0; i < 6; i++) {
    const container = document.getElementById(`ha-step-${i}`);
    if (container) { container.style.opacity = '0'; container.style.display = 'none'; }
  }

  // Start the sequential cascade
  _cascadeStep(data, 0);
}

function _cascadeStep(data, idx) {
  const myToken = _twToken;
  if (idx >= data.steps.length) {
    // All steps done — render payoff chart and final verdict
    _renderPayoffChart(data);
    _renderFinalVerdict(data);
    return;
  }

  const step = data.steps[idx];
  const container = document.getElementById(`ha-step-${idx}`);
  if (!container) { _cascadeStep(data, idx + 1); return; }

  // Show container with fade-in
  container.style.display = '';
  container.style.transition = 'opacity 200ms ease';
  container.style.opacity = '1';

  // Render agent badge immediately
  const narrativeEl = document.getElementById(`ha-step-${idx}-narrative`);
  const dataEl = document.getElementById(`ha-step-${idx}-data`);
  const verdictEl = document.getElementById(`ha-step-${idx}-verdict`);

  if (dataEl) dataEl.style.opacity = '0';
  if (verdictEl) verdictEl.style.opacity = '0';

  // Typewriter the narrative
  const text = step.narrative || '';
  if (narrativeEl) narrativeEl.textContent = '';

  let i = 0;
  function typeStep() {
    if (_twToken !== myToken) return; // cancelled
    if (i < text.length) {
      narrativeEl.textContent += text[i];
      i++;
      setTimeout(typeStep, 10);
    } else {
      // Narrative complete — show data cards + verdict
      if (dataEl) {
        dataEl.innerHTML = _renderStepData(idx, step);
        dataEl.style.transition = 'opacity 200ms ease';
        dataEl.style.opacity = '1';
      }
      if (verdictEl) {
        verdictEl.textContent = step.verdict || '';
        verdictEl.style.transition = 'opacity 200ms ease, transform 200ms ease';
        verdictEl.style.opacity = '1';
        verdictEl.style.transform = 'scale(1)';
        verdictEl.classList.add(_verdictColor(step.verdict));
      }
      // 300ms pause, then next step
      setTimeout(() => {
        if (_twToken !== myToken) return;
        _cascadeStep(data, idx + 1);
      }, 300);
    }
  }
  typeStep();
}

// ── Internal: Skip / Instant Render ───────────────────────────────────────────

function _renderAllInstant(data) {
  // Set timestamp
  const tsEl = document.getElementById('ha-timestamp');
  if (tsEl) tsEl.textContent = data.timestamp ? new Date(data.timestamp).toLocaleString() : '';

  for (let i = 0; i < data.steps.length; i++) {
    const step = data.steps[i];
    const container = document.getElementById(`ha-step-${i}`);
    if (!container) continue;

    container.style.display = '';
    container.style.opacity = '1';

    const narrativeEl = document.getElementById(`ha-step-${i}-narrative`);
    const dataEl = document.getElementById(`ha-step-${i}-data`);
    const verdictEl = document.getElementById(`ha-step-${i}-verdict`);

    if (narrativeEl) narrativeEl.textContent = step.narrative || '';
    if (dataEl) {
      dataEl.innerHTML = _renderStepData(i, step);
      dataEl.style.opacity = '1';
    }
    if (verdictEl) {
      verdictEl.textContent = step.verdict || '';
      verdictEl.style.opacity = '1';
      verdictEl.style.transform = 'scale(1)';
      verdictEl.classList.add(_verdictColor(step.verdict));
    }
  }

  _renderPayoffChart(data);
  _renderFinalVerdict(data);
}

// ── Internal: Per-Step Data Cards ─────────────────────────────────────────────

function _renderStepData(idx, step) {
  const d = step.data;
  if (!d) return '';

  switch (idx) {
    case 0: return _stepRegime(d);
    case 1: return _stepTechnicals(d);
    case 2: return _stepSentiment(d);
    case 3: return _stepAllocation(d);
    case 4: return _stepVolatility(d);
    case 5: return _stepHedgeAdvisor(d);
    default: return '';
  }
}

function _v(val, suffix = '') {
  return val != null ? `${val}${suffix}` : '--';
}

function _stepRegime(d) {
  return `<div class="reasoning-data-row">
    <span class="reasoning-kpi"><strong>EMA Ratio:</strong> ${_v(d.ema_ratio)}</span>
    <span class="reasoning-kpi"><strong>Bear Days:</strong> ${_v(d.consecutive_bear_days)}</span>
    <span class="reasoning-kpi"><strong>Regime:</strong> ${_v(d.regime)}</span>
    <span class="reasoning-kpi"><strong>Model:</strong> ${_v(d.model)}</span>
  </div>`;
}

function _stepTechnicals(d) {
  const items = [
    { label: 'RSI', val: _v(d.rsi), state: d.rsi_state },
    { label: 'MACD', val: _v(d.macd), state: d.macd_state },
    { label: 'BB %B', val: _v(d.bollinger_pct_b), state: d.bollinger_state },
    { label: 'Trend', val: _v(d.trend_score), state: d.trend_state },
    { label: 'ATR %', val: _v(d.atr_pct, '%'), state: d.atr_state },
  ];
  return `<div class="reasoning-data-row">${items.map(i =>
    `<span class="reasoning-kpi reasoning-indicator reasoning-indicator--${_indicatorColor(i.state)}"><strong>${i.label}:</strong> ${i.val}</span>`
  ).join('')}</div>`;
}

function _stepSentiment(d) {
  const signals = d.signals || {};
  const rows = Object.entries(signals).map(([key, sig]) => {
    const score = sig && sig.score != null ? sig.score : '--';
    const weight = sig && sig.weight != null ? sig.weight : 1;
    return `<span class="reasoning-kpi"><strong>${key}:</strong> ${score > 0 ? '+' : ''}${score} (w${weight})</span>`;
  }).join('');
  return `<div class="reasoning-data-row">${rows}
    <span class="reasoning-kpi reasoning-kpi--total"><strong>Total:</strong> ${_v(d.total_score)}/${_v(d.max_score)} ${_v(d.overall_sentiment)}</span>
  </div>`;
}

function _stepAllocation(d) {
  const rules = d.override_rules || [];
  const ruleHtml = rules.map(r =>
    `<span class="reasoning-rule reasoning-rule--${r.status === 'pass' ? 'pass' : 'fail'}">${r.status === 'pass' ? '&#9745;' : '&#9746;'} ${r.rule}</span>`
  ).join(' ');
  return `<div class="reasoning-data-row">
    <span class="reasoning-kpi"><strong>Allocation:</strong> ${_v(d.recommendation)} (${_v(d.allocation_pct, '%')})</span>
  </div>
  <div class="reasoning-data-row reasoning-rules">${ruleHtml}</div>`;
}

function _stepVolatility(d) {
  return `<div class="reasoning-data-row">
    <span class="reasoning-kpi"><strong>253d Vol:</strong> ${_v(d.ann_vol_253d, '%')}</span>
    <span class="reasoning-kpi"><strong>30d Vol:</strong> ${_v(d.ann_vol_30d, '%')}</span>
    <span class="reasoning-kpi"><strong>Regime:</strong> ${_v(d.vol_regime)}</span>
    <span class="reasoning-kpi"><strong>Premium:</strong> ${_v(d.premium_assessment)}</span>
    <span class="reasoning-kpi"><strong>1Y Return:</strong> ${_v(d.return_1y_pct, '%')}</span>
  </div>`;
}

function _stepHedgeAdvisor(d) {
  const cs = d.call_sell || {};
  const pb = d.put_buy || {};
  const primary = d.primary_recommendation;
  return `<div class="reasoning-strategy-cards">
    <div class="reasoning-card${primary === 'call_sell' ? ' reasoning-card--primary' : ''}">
      <div class="reasoning-card-title">${primary === 'call_sell' ? '&#9733; ' : ''}CALL SELL</div>
      <div class="reasoning-card-detail">${_v(cs.strike_label)}</div>
      <div class="reasoning-card-detail">Premium: ${_v(cs.premium_pct, '%')}</div>
      <div class="reasoning-card-detail">${cs.premium_eur != null ? _fmtEur(cs.premium_eur) : '--'}</div>
    </div>
    <div class="reasoning-card${primary === 'put_buy' ? ' reasoning-card--primary' : ''}">
      <div class="reasoning-card-title">${primary === 'put_buy' ? '&#9733; ' : ''}PUT BUY</div>
      <div class="reasoning-card-detail">${_v(pb.strike_label)}</div>
      <div class="reasoning-card-detail">Cost: ${_v(pb.premium_pct, '%')}</div>
      <div class="reasoning-card-detail">${pb.premium_eur != null ? _fmtEur(pb.premium_eur) : '--'}</div>
    </div>
  </div>`;
}

function _fmtEur(n) {
  if (n == null) return '--';
  const abs = Math.abs(n).toLocaleString('en-EU', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
  return n >= 0 ? `+€${abs}` : `−€${abs}`;
}

// ── Internal: Payoff Chart ────────────────────────────────────────────────────

function _renderPayoffChart(data) {
  const curves = data.payoff_curves;
  if (!curves || !curves.price_range) return;

  // Check if all unhedged values are zero — "no hedge needed"
  const allZero = curves.unhedged && curves.unhedged.every(v => v === 0);
  if (allZero) {
    const canvas = document.getElementById('ha-payoff-chart');
    if (canvas && canvas.parentNode) {
      canvas.parentNode.innerHTML = '<div class="reasoning-no-chart">No hedge needed — position is flat.</div>';
    }
    return;
  }

  const annotation = (data.spot_price && window.ChartAnnotation) ? {
    annotation: {
      annotations: {
        spotLine: {
          type: 'line',
          xMin: data.spot_price,
          xMax: data.spot_price,
          borderColor: C.t3,
          borderWidth: 1,
          borderDash: [4, 4],
          label: {
            display: true,
            content: `Spot: ${data.spot_price}`,
            position: 'start',
            font: { family: C.mono, size: 10 },
            color: C.t3,
          }
        }
      }
    }
  } : {};

  const config = {
    type: 'line',
    data: {
      labels: curves.price_range,
      datasets: [
        {
          label: 'Unhedged',
          data: curves.unhedged,
          borderColor: C.t3,
          borderWidth: 1.5,
          borderDash: [4, 4],
          pointRadius: 0,
          fill: false,
        },
        {
          label: 'Call Sell (Covered Call)',
          data: curves.call_sell,
          borderColor: C.build,
          borderWidth: 2,
          pointRadius: 0,
          fill: false,
        },
        {
          label: 'Put Buy (Protective Put)',
          data: curves.put_buy,
          borderColor: C.run,
          borderWidth: 2,
          pointRadius: 0,
          fill: false,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: 'bottom', labels: { font: { family: C.mono, size: 10 } } },
        ...annotation,
      },
      scales: {
        x: {
          title: { display: true, text: 'Price', font: { family: C.mono, size: 10 } },
          ticks: { font: { family: C.mono, size: 9 }, maxTicksLimit: 8 },
          grid: { display: false },
        },
        y: {
          title: { display: true, text: 'P&L', font: { family: C.mono, size: 10 } },
          ticks: { font: { family: C.mono, size: 9 } },
          grid: { color: 'rgba(0,0,0,.04)' },
        },
      },
      animation: { duration: 600 },
    },
  };

  _payoffChart = mkChart('ha-payoff-chart', config);
}

// ── Internal: Final Verdict ───────────────────────────────────────────────────

function _renderFinalVerdict(data) {
  const el = document.getElementById('ha-final-verdict');
  const confEl = document.getElementById('ha-confidence');

  if (el) {
    const rec = data.recommendation || 'no_hedge';
    const labels = { call_sell: 'CALL SELL', put_buy: 'PUT BUY', no_hedge: 'NO HEDGE' };
    el.textContent = labels[rec] || rec.toUpperCase();
    el.className = 'reasoning-final-verdict reasoning-final-verdict--' + rec.replace('_', '-');
  }
  if (confEl) {
    confEl.textContent = data.confidence ? `Confidence: ${data.confidence}` : '';
  }
}

// ── Internal: Helpers ─────────────────────────────────────────────────────────

function _verdictColor(verdict) {
  if (!verdict) return 'reasoning-verdict--neutral';
  const v = verdict.toLowerCase();
  if (v.includes('bull') || v.includes('full') || v.includes('call sell')) return 'reasoning-verdict--positive';
  if (v.includes('bear') || v.includes('hold') || v.includes('put buy')) return 'reasoning-verdict--negative';
  if (v.includes('elevated') || v.includes('rich')) return 'reasoning-verdict--warning';
  return 'reasoning-verdict--neutral';
}

function _indicatorColor(state) {
  if (!state) return 'neutral';
  const s = state.toLowerCase();
  if (s === 'bullish' || s === 'uptrend' || s === 'oversold' || s === 'near_lower_band' || s === 'complacent') return 'positive';
  if (s === 'bearish' || s === 'downtrend' || s === 'overbought' || s === 'near_upper_band' || s === 'fearful') return 'negative';
  return 'neutral';
}
