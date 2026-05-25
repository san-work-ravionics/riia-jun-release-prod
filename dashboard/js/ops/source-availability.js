// ── Source Availability ───────────────────────────────────────────────────────

const _fmtName = s => s.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());

export async function loadSourceAvailability() {
  const chartEl = document.getElementById('source-availability-chart');
  if (!chartEl) return;

  try {
    const res = await fetch('/ops/metrics/source-availability.json');
    const data = res.ok ? await res.json() : null;

    if (!data || typeof data.sources !== 'object' || Object.keys(data.sources).length === 0) {
      chartEl.innerHTML = '<div class="empty">No experience layer data yet</div>';
      return;
    }

    const cols = Object.keys(data.sources).length;
    const cells = Object.entries(data.sources).map(([name, src]) => {
      const total   = (src.ok || 0) + (src.empty || 0) + (src.error || 0) || 1;
      const ok_pct  = src.ok_pct ?? ((src.ok || 0) / total * 100);
      const cls     = ok_pct >= 90 ? 'ok' : ok_pct >= 70 ? 'warn' : 'danger';
      const label   = ok_pct >= 90 ? 'OK' : ok_pct >= 70 ? 'Warn' : 'Error';
      const msg     = `${src.ok ?? 0} ok · ${src.empty ?? 0} empty · ${src.error ?? 0} err`;
      return `<div class="drift-cell ${cls}">
        <div class="drift-cell-name">${_fmtName(name)}</div>
        <div class="drift-cell-status ${cls}">${label}</div>
        <div class="drift-cell-msg">${ok_pct.toFixed(0)}% availability<br>${msg}</div>
      </div>`;
    });

    chartEl.innerHTML = `<div style="display:grid;grid-template-columns:repeat(${cols},1fr);gap:8px">${cells.join('')}</div>`;
  } catch (e) {
    console.error('[RITA] loadSourceAvailability failed', e);
    if (chartEl) chartEl.innerHTML = '<div class="empty">Source availability data unavailable</div>';
  }
}
