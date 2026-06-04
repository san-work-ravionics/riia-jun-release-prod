// ── FnO My Portfolio — Phase 3 Overview redesign ──────────────────────────────
// 3-source parallel fetch: portfolio + geography-overview + hedge-plan
// KPI strip · allocation doughnut · hedge status card · 6-column holdings table
import { apiFetch } from './api.js';
import { mkChart, C } from '../shared/charts.js';
import { setEl } from '../shared/utils.js';
import { _sectionLoaders } from './nav.js';
import { state } from './state.js';

// ── helpers ──────────────────────────────────────────────────────────────────
const _fmt2   = v => (v == null ? '—' : parseFloat(v).toFixed(2));
const _fmtPct = v => (v == null ? '—' : parseFloat(v).toFixed(2) + '%');
const _fmtEur = v => (v == null || v === 0
  ? '—'
  : '€' + parseFloat(v).toLocaleString('en-EU', { maximumFractionDigits: 0 }));

// ── KPI strip ────────────────────────────────────────────────────────────────
function _renderKpis(portfolio, instMap, hedgePlan) {
  const holdings   = portfolio.holdings || [];
  const totalValue = portfolio.total_value_eur;

  // KPI 1 — Portfolio Value
  if (totalValue == null || totalValue === 0) {
    setEl('fno-mp-kpi-value',
      `<div class="kpi-val">—</div><div class="kpi-sub">Not set — add in Portfolio Builder</div>`);
  } else {
    setEl('fno-mp-kpi-value',
      `<div class="kpi-val">${_fmtEur(totalValue)}</div><div class="kpi-sub">total portfolio value</div>`);
  }

  // KPI 2 — Holdings count
  setEl('fno-mp-kpi-holdings',
    `<div class="kpi-val">${holdings.length}</div><div class="kpi-sub">instruments</div>`);

  // KPI 3 — Wtd 1Y Return (indicative)
  const validHoldings = holdings.filter(h => instMap[h.instrument_id]?.return_1y_pct != null);
  if (validHoldings.length === 0) {
    setEl('fno-mp-kpi-return',
      `<div class="kpi-val">—</div><div class="kpi-sub">weighted avg (indicative)</div>`);
  } else {
    const totalValidPct = validHoldings.reduce((s, h) => s + h.allocation_pct, 0) || 1;
    const wtdReturn = validHoldings.reduce((s, h) =>
      s + (h.allocation_pct / totalValidPct) * instMap[h.instrument_id].return_1y_pct, 0);
    setEl('fno-mp-kpi-return',
      `<div class="kpi-val">${_fmtPct(wtdReturn)}</div><div class="kpi-sub">weighted avg (indicative)</div>`);
  }

  // KPI 4 — Avg Risk (indicative)
  const validRisk = holdings.filter(h => instMap[h.instrument_id]?.risk_score != null);
  if (validRisk.length === 0) {
    setEl('fno-mp-kpi-risk',
      `<div class="kpi-val">—</div><div class="kpi-sub">weighted avg (indicative)</div>`);
  } else {
    const totalRiskPct = validRisk.reduce((s, h) => s + h.allocation_pct, 0) || 1;
    const avgRisk = validRisk.reduce((s, h) =>
      s + (h.allocation_pct / totalRiskPct) * instMap[h.instrument_id].risk_score, 0);
    setEl('fno-mp-kpi-risk',
      `<div class="kpi-val">${_fmt2(avgRisk)}</div><div class="kpi-sub">weighted avg (indicative)</div>`);
  }

  // KPI 5 — Hedge Coverage (indicative)
  if (!hedgePlan) {
    setEl('fno-mp-kpi-hedged',
      `<div class="kpi-val">—</div><div class="kpi-sub">from saved plan (indicative)</div>`);
  } else {
    const coverage = hedgePlan.coverage != null ? hedgePlan.coverage + '%' : '—';
    setEl('fno-mp-kpi-hedged',
      `<div class="kpi-val">${coverage}</div><div class="kpi-sub">from saved plan (indicative)</div>`);
  }
}

// ── Allocation doughnut chart ─────────────────────────────────────────────────
function _renderAllocChart(holdings, instMap) {
  const regionBuckets = { India: 0, US: 0, EU: 0, Other: 0 };
  for (const h of holdings) {
    const region = instMap[h.instrument_id]?.region ?? 'Other';
    regionBuckets[region] = (regionBuckets[region] || 0) + h.allocation_pct;
  }

  const labels = Object.keys(regionBuckets).filter(k => regionBuckets[k] > 0);
  const values = labels.map(k => regionBuckets[k]);

  if (labels.length === 0) {
    // All geo failed — show Other: 100%
    labels.push('Other');
    values.push(100);
  }

  const colors = [C.green, C.blue, C.purple, C.muted];
  mkChart('fno-mp-alloc-chart', {
    type: 'doughnut',
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: colors.slice(0, labels.length),
        borderWidth: 2,
        borderColor: 'var(--surface)'
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: 'bottom',
          labels: { font: { size: 11 }, color: 'var(--t2)', boxWidth: 12 }
        },
        tooltip: {
          callbacks: {
            label: ctx => ` ${ctx.label}: ${ctx.parsed.toFixed(1)}%`
          }
        }
      }
    }
  });
}

// ── Hedge status card ─────────────────────────────────────────────────────────
function _renderHedgeCard(hedgePlan, holdings) {
  const strategyLabel = { pp: 'Protective Put', ps: 'Put Spread', collar: 'Collar' };
  let html;

  if (!hedgePlan) {
    html = `
      <div style="font-size:14px;color:var(--t3);margin-bottom:8px">No hedge configured</div>
      <div style="font-size:12px;color:var(--t3);margin-bottom:12px">No saved hedge plan found.</div>
      <button class="btn btn-sm" onclick="fnoMpGoHedge()">Configure Hedge →</button>
      <p style="font-size:11px;color:var(--t3);margin-top:12px">Values are indicative — not financial advice</p>
    `;
  } else {
    const hedgedIds    = new Set(hedgePlan.hedged_ids || []);
    const hedgedCount  = (holdings || []).filter(h => hedgedIds.has(h.instrument_id)).length;
    const strategy     = strategyLabel[hedgePlan.scenario_tab] || hedgePlan.scenario_tab || '—';
    const coverage     = hedgePlan.coverage != null ? hedgePlan.coverage + '%' : '—';
    const updatedAt    = hedgePlan.updated_at ? new Date(hedgePlan.updated_at).toLocaleDateString() : '—';

    html = `
      <div style="font-size:12px;color:var(--t2);margin-bottom:8px;font-family:var(--fm)">
        <div><strong>Strategy:</strong> ${strategy}</div>
        <div><strong>Coverage:</strong> ${coverage}</div>
        <div><strong>Hedged:</strong> ${hedgedCount} of ${(holdings || []).length} instruments</div>
        <div><strong>Last updated:</strong> ${updatedAt}</div>
      </div>
      <button class="btn btn-sm" onclick="fnoMpGoHedge()">Update Hedge →</button>
      <p style="font-size:11px;color:var(--t3);margin-top:12px">Values are indicative — not financial advice</p>
    `;
  }

  setEl('fno-mp-hedge-card', html);
}

// ── Holdings table ────────────────────────────────────────────────────────────
function _renderHoldingsTable(holdings, instMap, hedgePlan, totalValue) {
  const hedgedIds   = new Set((hedgePlan?.hedged_ids) || []);
  const strategyLabel = { pp: 'Protective Put', ps: 'Put Spread', collar: 'Collar' };
  const strategyStr = strategyLabel[hedgePlan?.scenario_tab] || '—';

  const rows = holdings.map(h => {
    const info    = instMap[h.instrument_id] || {};
    const posEur  = (totalValue && h.allocation_pct != null)
      ? _fmtEur(totalValue * h.allocation_pct / 100)
      : '—';
    const ret1y   = info.return_1y_pct != null ? _fmtPct(info.return_1y_pct) : '—';
    const risk    = info.risk_score != null ? _fmt2(info.risk_score) : '—';
    // Stale hedged_ids: silently skip — table iterates holdings, not hedged_ids
    const isHedged  = hedgedIds.has(h.instrument_id);
    const hedgedCell = isHedged
      ? `<span style="color:#16a34a">${strategyStr}</span>`
      : '—';
    const alloc   = h.allocation_pct != null ? _fmtPct(h.allocation_pct) : '—';

    return `<tr>
      <td style="padding:8px 12px">${h.instrument_id}</td>
      <td style="padding:8px 12px;text-align:right;font-family:'IBM Plex Mono',monospace">${alloc}</td>
      <td style="padding:8px 12px;text-align:right;font-family:'IBM Plex Mono',monospace">${posEur}</td>
      <td style="padding:8px 12px;text-align:right;font-family:'IBM Plex Mono',monospace">${ret1y}</td>
      <td style="padding:8px 12px;text-align:right;font-family:'IBM Plex Mono',monospace">${risk}</td>
      <td style="padding:8px 12px;text-align:center">${hedgedCell}</td>
    </tr>`;
  }).join('');

  setEl('fno-mp-holdings-body', rows);

  // Footer total allocation (alloc_pct = 0 guard: || 1 not needed for sum, only for division)
  const totalAlloc = holdings.reduce((s, h) => s + (h.allocation_pct || 0), 0);
  setEl('fno-mp-total', _fmtPct(totalAlloc));
}

// ── Main loader ───────────────────────────────────────────────────────────────
export async function loadFnoMyPortfolio() {
  // Reset placeholders
  const emptyEl = document.getElementById('fno-mp-empty');
  const errEl   = document.getElementById('fno-mp-error');
  if (emptyEl) emptyEl.style.display = 'none';
  if (errEl)   errEl.style.display   = 'none';

  const token = sessionStorage.getItem('auth_token');
  const authHeaders = token ? { Authorization: `Bearer ${token}` } : {};

  // ── 3-source parallel fetch ───────────────────────────────────────────────
  const [portfolioRes, geoRes, hedgeRes] = await Promise.allSettled([
    apiFetch('/api/v1/experience/user-portfolio',       { headers: authHeaders }),
    apiFetch('/api/v1/experience/rita/geography-overview', {}),
    apiFetch('/api/v1/experience/fno/hedge-plan',       { headers: authHeaders })
  ]);

  // ── Source 1: Portfolio (required) ────────────────────────────────────────
  // apiFetch returns data|null; null = error or non-2xx
  const portfolio = portfolioRes.status === 'fulfilled' ? portfolioRes.value : null;

  if (!portfolio) {
    // Could be 404 (no portfolio) or network error
    if (emptyEl) emptyEl.style.display = '';
    return;
  }

  // Populate meta strip
  setEl('fno-mp-name',    portfolio.name      || '—');
  setEl('fno-mp-updated', portfolio.updated_at
    ? new Date(portfolio.updated_at).toLocaleString()
    : '—');

  const holdings = portfolio.holdings || [];
  if (holdings.length === 0) {
    if (emptyEl) emptyEl.style.display = '';
    return;
  }

  // ── Source 2: Geography Overview (optional) ───────────────────────────────
  const geoData = (geoRes.status === 'fulfilled') ? geoRes.value : null;
  const instMap = {};
  if (geoData?.regions) {
    for (const reg of geoData.regions) {
      for (const inst of (reg.instruments ?? [])) {
        instMap[inst.id] = {
          return_1y_pct: inst.return_1y_pct,
          risk_score:    inst.risk_score,
          region:        reg.region   // propagated from parent GeoRegion object
        };
      }
    }
  }
  // If geo failed: instMap remains {} — all geo-derived fields degrade to "—"

  // ── Source 3: Hedge Plan (optional) ───────────────────────────────────────
  // 404 = no plan (not an error) — apiFetch returns null for 404
  const hedgePlan = (hedgeRes.status === 'fulfilled') ? hedgeRes.value : null;

  // ── Render all components ─────────────────────────────────────────────────
  _renderKpis(portfolio, instMap, hedgePlan);
  _renderAllocChart(holdings, instMap);
  _renderHedgeCard(hedgePlan, holdings);
  _renderHoldingsTable(holdings, instMap, hedgePlan, portfolio.total_value_eur);
}

window.loadFnoMyPortfolio = loadFnoMyPortfolio;

// ── Analytics-state Overview (F30 Phase 3) ────────────────────────────────────
export function renderOverviewFromState() {
  // renderGeoOverview() in dashboard.js handles the instrument view.
  // renderDashKpis() handles the merged KPI row.
  // Nothing left to do here for the overview from state.
}

export function fnoSelectInstrument(id) {
  // Delegate to setUnderlying so the geo-overview highlight and positions table both update.
  if (typeof window.setUnderlying === 'function') window.setUnderlying(id);
}
