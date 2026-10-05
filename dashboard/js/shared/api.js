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
      const _isLocal = ['localhost', '127.0.0.1', '0.0.0.0'].includes(location.hostname);
      if (!_isLocal) {
        sessionStorage.setItem('post_login_redirect', window.location.href);
        window.location.href = '/auth/google/login';
        return;
      }
      throw new Error('Session expired — please log in again');
    }
    const err = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(_detailText(err.detail, r.statusText));
  }
  return r.json();
}

// FastAPI `detail` is a string, or (422) a list of {loc, msg} — flatten to readable text.
function _detailText(detail, fallback) {
  if (Array.isArray(detail)) {
    return detail.map(d => (d && d.msg) ? `${(d.loc || []).slice(1).join('.')} ${d.msg}`.trim() : String(d)).join('; ');
  }
  return detail ? String(detail) : fallback;
}

// apiUpload() → multipart POST (FormData). No Content-Type header: the browser adds the boundary.
// Mirrors api()'s 401 handling and throws Error(message) with a readable FastAPI `detail`.
export async function apiUpload(path, formData, method = 'POST') {
  const token = sessionStorage.getItem('auth_token');
  const r = await fetch(apiBase() + path, {
    method, body: formData, headers: token ? { 'Authorization': `Bearer ${token}` } : {},
  });
  if (!r.ok) {
    if (r.status === 401) {
      sessionStorage.removeItem('auth_token');
      const _isLocal = ['localhost', '127.0.0.1', '0.0.0.0'].includes(location.hostname);
      if (!_isLocal) {
        sessionStorage.setItem('post_login_redirect', window.location.href);
        window.location.href = '/auth/google/login';
        return;
      }
      throw new Error('Session expired — please log in again');
    }
    const err = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(_detailText(err.detail, r.statusText));
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
