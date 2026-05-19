// ── Shared DOM + formatting utilities ────────────────────────────────────────

// crypto.randomUUID() requires HTTPS — use fallback for HTTP deployments
export function randomUUID() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID();
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
    const r = Math.random() * 16 | 0;
    return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16);
  });
}
export const fmt    = (v, d = 2) => v == null || v === '' ? '—' : parseFloat(v).toFixed(d);
export const fmtPct = v => v == null ? '—' : parseFloat(v).toFixed(2) + '%';
export const fmtMs  = v => v == null ? '—' : Math.round(v) + ' ms';

export function setEl(id, html) {
  const el = document.getElementById(id);
  if (el) el.innerHTML = html;
}

export function appendResult(containerId, html) {
  const el = document.getElementById(containerId);
  if (el) el.innerHTML = html;
}

export function badge(status) {
  const map = { ok: 'ok', warn: 'warn', alert: 'err', error: 'err', run: 'run', running: 'run' };
  const cls = map[String(status || '').toLowerCase()] || 'neu';
  return `<span class="badge ${cls}">${status || '—'}</span>`;
}
