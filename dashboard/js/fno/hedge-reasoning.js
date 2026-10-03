// ── Hedge Advisor — Agent Reasoning Cascade ───────────────────────────────────

let _twToken = 0;

// ── Public API ────────────────────────────────────────────────────────────────
// F39: rendered inside the Hedge Workflow Recommendation step (hedge-workflow-
// recommendation.js owns the fetch and the instrument; this module only renders the
// original agent-reasoning screen). The old standalone page / dropdown / fetch were
// removed; the cascade, typewriter, per-step cards and Skip behaviour are unchanged.
// The old "Payoff Comparison" chart is omitted: the hedge-reasoning API has no
// payoff_curves field, so it never rendered.

/** Show/hide the loading spinner. */
export function haShowLoading(show) { _showLoading(show); }

/** Clear the screen (no instrument / no holdings). */
export function haClear() {
  _twToken += 1;
  _showLoading(false);
  _hideError();
  _hideResults();
  _showSkip(false);
}

/** Show an error message (hides results). */
export function haShowError(msg) {
  _showLoading(false);
  _hideResults();
  _showSkip(false);
  _showError(msg);
}

/**
 * Render the reasoning screen for `data`. instant=true (cached data on step re-entry)
 * skips the typewriter and renders every step at once.
 */
export function haShowReasoning(data, instant = false) {
  _twToken += 1; // cancel any in-flight typewriter cascade
  _hideError();
  _showLoading(false);
  if (!data || !data.steps || data.steps.length === 0) {
    haShowError('No reasoning data returned for this instrument.');
    return;
  }
  _showResults(true);
  const resultsEl = document.getElementById('ha-results');
  if (resultsEl) resultsEl._haData = data;
  if (instant) {
    _showSkip(false);
    _renderAllInstant(data);
  } else {
    _showSkip(true);
    _renderCascade(data);
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
  for (let i = 0; i < 7; i++) {
    const container = document.getElementById(`ha-step-${i}`);
    if (container) { container.style.opacity = '0'; container.style.display = 'none'; }
  }

  // Start the sequential cascade
  _cascadeStep(data, 0);
}

function _cascadeStep(data, idx) {
  const myToken = _twToken;
  if (idx >= data.steps.length) {
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
    case 5: return _stepGoalAnalyst(d);
    case 6: return _stepHedgeAdvisor(d);
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

function _stepGoalAnalyst(d) {
  const trigger = d.hedge_trigger || '--';
  const triggerCls = trigger === 'triggered' ? 'reasoning-indicator--positive' : 'reasoning-indicator--neutral';
  return `<div class="reasoning-data-row">
    <span class="reasoning-kpi"><strong>Horizon Fit:</strong> ${_v(d.horizon_label)}</span>
    <span class="reasoning-kpi"><strong>Annual Target:</strong> ${_v(d.annual_target_pct, '%')}</span>
    <span class="reasoning-kpi"><strong>Monthly Target:</strong> ${_v(d.monthly_target_pct, '%')}</span>
    <span class="reasoning-kpi"><strong>Last Month Return:</strong> ${_v(d.actual_monthly_return_pct, '%')}</span>
    <span class="reasoning-kpi"><strong>Excess:</strong> ${_v(d.excess_pct, '%')}</span>
    <span class="reasoning-kpi"><strong>Hedge Budget:</strong> ${_v(d.hedge_budget_pct, '%')}</span>
    <span class="reasoning-kpi ${triggerCls}"><strong>Hedge Trigger:</strong> ${trigger}</span>
  </div>`;
}

// The call-sell / put-buy legs are shown as panels beside the narrative by the workflow
// Recommendation step (hedge-workflow-recommendation.js) — no duplicate cards here.
function _stepHedgeAdvisor() {
  return '';
}

function _fmtEur(n) {
  if (n == null) return '--';
  const abs = Math.abs(n).toLocaleString('en-EU', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
  return n >= 0 ? `+€${abs}` : `−€${abs}`;
}

// ── Internal: Helpers ─────────────────────────────────────────────────────────

function _verdictColor(verdict) {
  if (!verdict) return 'reasoning-verdict--neutral';
  const v = verdict.toLowerCase();
  if (v.includes('bull') || v.includes('full') || v.includes('call sell') || v === 'triggered') return 'reasoning-verdict--positive';
  if (v.includes('bear') || v.includes('hold') || v.includes('put buy')) return 'reasoning-verdict--negative';
  if (v.includes('elevated') || v.includes('rich') || v.includes('not triggered')) return 'reasoning-verdict--warning';
  return 'reasoning-verdict--neutral';
}

function _indicatorColor(state) {
  if (!state) return 'neutral';
  const s = state.toLowerCase();
  if (s === 'bullish' || s === 'uptrend' || s === 'oversold' || s === 'near_lower_band' || s === 'complacent') return 'positive';
  if (s === 'bearish' || s === 'downtrend' || s === 'overbought' || s === 'near_upper_band' || s === 'fearful') return 'negative';
  return 'neutral';
}
