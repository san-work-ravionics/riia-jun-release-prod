// ── FnO API — thin re-export wrapper ──────────────────────────────────────────
// HTTP primitives come from the shared layer. This file re-exports them so
// existing consumers (rr.js, hedge.js, manoeuvre.js) need no import changes.
export { apiBase, api, apiFetch } from '../shared/api.js';

// API key — set to match PORTFOLIO_API_KEY env var if configured.
// Leave empty string for local dev where the env var is not set.
// Kept here (not in shared) because only fno uses the X-API-Key header.
export const RITA_API_KEY = '';
