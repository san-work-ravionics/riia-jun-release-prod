// ── Local dev auth bypass ──────────────────────────────────────────────────────
// On localhost ONLY, mints a `rita-dev` JWT via POST /auth/token (password
// "rita-dev") and stores it as `rita_token`, so local testing skips Google OAuth.
// The backend honours subject "rita-dev" only when env=development (see auth.py
// get_current_user). This is a no-op on any non-local host — production is
// completely unaffected.

const LOCAL_HOSTS = ['localhost', '127.0.0.1', '0.0.0.0'];

export function isLocalDev() {
  return LOCAL_HOSTS.includes(window.location.hostname);
}

const _apiBase = () => (window.RITA_API_BASE || '').replace(/\/$/, '');

// Seeds a dev token into sessionStorage when running locally and none is present.
// Returns true if a usable token exists afterwards, false otherwise.
export async function ensureDevToken() {
  if (!isLocalDev()) return false;
  if (sessionStorage.getItem('rita_token')) return true;
  try {
    const r = await fetch(_apiBase() + '/auth/token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: 'rita-dev', password: 'rita-dev' }),
    });
    if (!r.ok) return false;
    const data = await r.json();
    if (!data.access_token) return false;
    sessionStorage.setItem('rita_token', data.access_token);
    return true;
  } catch {
    return false;
  }
}
