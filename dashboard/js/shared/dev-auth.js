// ── Local dev auth bypass ──────────────────────────────────────────────────────
// On localhost ONLY, mints a JWT via POST /auth/token and stores it as
// auth_token in sessionStorage, so local testing skips Google OAuth.
// This is a no-op on any non-local host — production is unaffected.

const _LOCAL_HOSTS = ['localhost', '127.0.0.1', '0.0.0.0'];

export function isLocalDev() {
  return _LOCAL_HOSTS.includes(window.location.hostname);
}

const _apiBase = () => (window.RITA_API_BASE || '').replace(/\/$/, '');

export async function ensureDevToken() {
  if (!isLocalDev()) return false;
  if (sessionStorage.getItem('auth_token')) return true;
  try {
    const r = await fetch(_apiBase() + '/auth/token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: 'rita-dev', password: 'rita-dev' }),
    });
    if (!r.ok) return false;
    const data = await r.json();
    if (!data.access_token) return false;
    sessionStorage.setItem('auth_token', data.access_token);
    return true;
  } catch {
    return false;
  }
}
