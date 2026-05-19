// Session-scoped API response cache. Cleared on page reload.
const _store = new Map();

export function createCache(apiFn) {
  return async function cachedApi(path, ttlMs = 30000) {
    const now = Date.now();
    const cached = _store.get(path);
    if (cached && now < cached.expiresAt) {
      return cached.data;
    }
    const data = await apiFn(path);
    _store.set(path, { data, expiresAt: now + ttlMs });
    return data;
  };
}
