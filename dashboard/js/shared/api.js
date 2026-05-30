// ── Shared API client ─────────────────────────────────────────────────────────
// api()      → throws on error — use for writes/actions
// apiFetch() → returns null on error — use for reads

export const apiBase = () => (window.RITA_API_BASE || '').replace(/\/$/, '');

export async function api(path, method = 'GET', body = null) {
  const token = sessionStorage.getItem('auth_token');
  const opts = { method, headers: { 'Content-Type': 'application/json', ...(token ? { 'Authorization': `Bearer ${token}` } : {}) } };
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch(apiBase() + path, opts);
  if (!r.ok) {
    if (r.status === 401) {
      sessionStorage.removeItem('auth_token');
      sessionStorage.setItem('post_login_redirect', window.location.href);
      window.location.href = '/auth/google/login';
      return;
    }
    const err = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(err.detail || r.statusText);
  }
  return r.json();
}

export async function apiFetch(url, options = {}) {
  const traceId = window.SESSION_TRACE_ID || Math.random().toString(16).slice(2);
  try {
    const r = await fetch(apiBase() + url, {
      ...options,
      headers: { 'X-Request-ID': traceId, ...(options.headers || {}) },
    });
    if (!r.ok) { console.warn(`[api] ${url} → ${r.status}`, traceId); return null; }
    return await r.json();
  } catch (e) {
    console.warn(`[api] ${url} fetch error`, e, traceId);
    return null;
  }
}
