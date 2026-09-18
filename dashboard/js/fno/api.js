// ── FnO API — thin re-export wrapper ──────────────────────────────────────────
// HTTP primitives come from the shared layer. This file re-exports them so
// existing consumers (rr.js, hedge.js, manoeuvre.js) need no import changes.
export { apiBase, api, apiFetch } from '../shared/api.js';

// API key — set to match PORTFOLIO_API_KEY env var if configured.
// Leave empty string for local dev where the env var is not set.
// Kept here (not in shared) because only fno uses the X-API-Key header.
export const RITA_API_KEY = '';

// ── Kite middleware client ────────────────────────────────────────────────────
export const kiteBase = () => (window.KITE_API_BASE || 'http://localhost:8000').replace(/\/$/, '');

export async function kiteFetch(path, options = {}) {
  const traceId = window.SESSION_TRACE_ID || Math.random().toString(16).slice(2);
  try {
    const r = await fetch(kiteBase() + path, {
      ...options,
      headers: { 'X-Request-ID': traceId, ...(options.headers || {}) },
    });
    if (!r.ok) { console.warn(`[kite] ${path} → ${r.status}`, traceId); return null; }
    return await r.json();
  } catch (e) {
    console.warn(`[kite] ${path} fetch error`, e, traceId);
    return null;
  }
}
