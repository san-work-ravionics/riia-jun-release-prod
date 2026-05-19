// ── Functional KPI Sparklines ─────────────────────────────────────────────────

const KPI_DEFS = [
  { key: 'training_success_rate_pct', label: 'Training Success', unit: '%', sub: '24h success rate',
    color: v => v === 0 ? '' : v >= 80 ? 'ok' : v >= 50 ? 'warn' : 'danger' },
  { key: 'chat_low_confidence_pct',   label: 'Chat Low Conf.',   unit: '%', sub: '24h low-confidence',
    color: v => v === 0 ? '' : v <= 10 ? 'ok' : v <= 25 ? 'warn' : 'danger' },
  { key: 'experience_error_pct',      label: 'Experience Errors', unit: '%', sub: '24h error rate',
    color: v => v === 0 ? 'ok' : v <= 2 ? 'warn' : 'danger' },
  { key: 'error_rate_pct',            label: 'API Error Rate',   unit: '%', sub: '24h error rate',
    color: v => v === 0 ? 'ok' : v <= 2 ? 'warn' : 'danger' },
  { key: 'p95_latency_ms',            label: 'P95 Latency',      unit: 'ms', sub: '24h p95',
    color: v => v === 0 ? '' : v <= 500 ? 'ok' : v <= 1500 ? 'warn' : 'danger' },
];

function sparklineSVG(values) {
  const w = 100, h = 28;
  const max = Math.max(...values, 1);
  const pts = values.map((v, i) => {
    const x = values.length > 1 ? (i / (values.length - 1)) * w : w / 2;
    const y = h - (v / max) * (h - 2) - 1;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  return `<svg width="${w}" height="${h}" style="display:block;margin-top:6px;opacity:.7">
    <polyline points="${pts}" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>
  </svg>`;
}

export async function loadFunctionalKPIs() {
  const container = document.getElementById('functional-kpis-container');

  try {
    const res = await fetch('/ops/metrics/functional-kpis.json');
    const data = res.ok ? await res.json() : null;

    if (!data || !data.series) {
      if (container) container.innerHTML = '<div class="empty">KPI data unavailable</div>';
      return;
    }

    const cards = KPI_DEFS.map(def => {
      const values = (data.series[def.key] || []).filter(v => v != null);
      const lastVal = values.length > 0 ? values[values.length - 1] : null;
      const allZero = values.every(v => v === 0);
      const cls = lastVal != null ? def.color(lastVal) : '';
      const valDisplay = lastVal != null
        ? (def.unit === 'ms' ? Math.round(lastVal) + ' ms' : lastVal.toFixed(1) + '%')
        : '—';
      const sparkline = (!allZero && values.length > 1) ? sparklineSVG(values) : '';

      return `<div class="kpi">
        <div class="kpi-ey">${def.label}</div>
        <div class="kpi-val ${cls}">${valDisplay}</div>
        <div class="kpi-sub">${def.sub}</div>
        ${sparkline}
      </div>`;
    });

    if (container) {
      container.style.cssText = '';
      container.innerHTML = `<div class="kpi-strip">${cards.join('')}</div>`;
    }
  } catch (e) {
    console.error('[RITA] loadFunctionalKPIs failed', e);
    if (container) container.innerHTML = '<div class="empty">KPI data unavailable</div>';
  }
}
