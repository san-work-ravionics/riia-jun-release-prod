// ── Source Availability ───────────────────────────────────────────────────────

export async function loadSourceAvailability() {
  const chartEl = document.getElementById('source-availability-chart');

  try {
    const res = await fetch('/ops/metrics/source-availability.json');
    const data = res.ok ? await res.json() : null;

    if (!data || typeof data.sources !== 'object' || Object.keys(data.sources).length === 0) {
      if (chartEl) chartEl.innerHTML = '<div class="empty">No experience layer data yet</div>';
      return;
    }

    const rows = Object.entries(data.sources).map(([name, src]) => {
      const total = (src.ok || 0) + (src.empty || 0) + (src.error || 0) || 1;
      const ok_pct    = (src.ok    || 0) / total * 100;
      const empty_pct = (src.empty || 0) / total * 100;
      const error_pct = (src.error || 0) / total * 100;

      const okSeg    = `<div style="background:#22c55e;width:${ok_pct.toFixed(2)}%;display:flex;align-items:center;justify-content:center;font-size:11px;color:#fff;">${ok_pct > 5 ? ok_pct.toFixed(0) + '%' : ''}</div>`;
      const emptySeg = `<div style="background:#f59e0b;width:${empty_pct.toFixed(2)}%;display:flex;align-items:center;justify-content:center;font-size:11px;color:#fff;">${empty_pct > 5 ? empty_pct.toFixed(0) + '%' : ''}</div>`;
      const errorSeg = `<div style="background:#ef4444;width:${error_pct.toFixed(2)}%;display:flex;align-items:center;justify-content:center;font-size:11px;color:#fff;">${error_pct > 5 ? error_pct.toFixed(0) + '%' : ''}</div>`;

      return `<div style="margin-bottom:10px;">
        <div style="font-size:12px;color:var(--t2);margin-bottom:4px;font-family:var(--fm)">${name}</div>
        <div style="display:flex;height:20px;width:100%;border-radius:3px;overflow:hidden;">
          ${okSeg}${emptySeg}${errorSeg}
        </div>
      </div>`;
    });

    if (chartEl) chartEl.innerHTML = rows.join('');
  } catch (e) {
    console.error('[RITA] loadSourceAvailability failed', e);
    if (chartEl) chartEl.innerHTML = '<div class="empty">Source availability data unavailable</div>';
  }
}
