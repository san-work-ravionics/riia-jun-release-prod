// ── FnO API — thin re-export wrapper ──────────────────────────────────────────
// HTTP primitives come from the shared layer. This file re-exports them so
// existing consumers (rr.js, hedge.js, manoeuvre.js) need no import changes.
export { apiBase, api, apiFetch } from '../shared/api.js';
