// ── createShow — section switching factory ──────────────────────────────────
// Matches the inline show(sId, el) function from ds.html verbatim.
// Returns a configured show function with loaders dict already closed over.
export function createShow(loaders) {
  return function show(sId, el) {
    document.querySelectorAll('.section').forEach(s=>s.classList.remove('active'));
    document.querySelectorAll('.nav-item').forEach(n=>n.classList.remove('active'));
    document.getElementById('s-'+sId)?.classList.add('active');
    el?.classList.add('active');
    if (loaders[sId]) loaders[sId]();
  };
}
