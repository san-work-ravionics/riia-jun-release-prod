// ── Shared navigation registry base ─────────────────────────────────────────
// Usage: const nav = createNavRegistry(); nav.register('key', loaderFn); nav.load('key');
export function createNavRegistry() {
  const loaders = {};
  const loaded  = new Set();
  return {
    loaders,
    register(key, fn)  { loaders[key] = fn; },
    load(key)          { if (!loaded.has(key) && loaders[key]) { loaded.add(key); loaders[key](); } },
    reset(key)         { loaded.delete(key); },
  };
}
