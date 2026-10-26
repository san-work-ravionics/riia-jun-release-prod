// Jarvis — F44 stub page (user 2026-10-26: home-page tile + stub now; the module is built in P4).
import { api } from '../shared/api.js';
import { ensureDevToken } from '../shared/dev-auth.js';

function _set(id, text, cls) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = text;
  if (cls) el.className = cls;
}

async function loadStatus() {
  _set('jv-signed-in', sessionStorage.getItem('auth_token') ? 'yes' : 'no',
       sessionStorage.getItem('auth_token') ? 'ok' : 'warn');
  try {
    const health = await api('/health');
    const mcp = health && health.mcp;
    if (mcp) _set('jv-mcp', `${mcp.tools_registered} tools · auth ${mcp.auth}`, mcp.auth === 'on' ? 'ok' : 'warn');
    else _set('jv-mcp', 'unavailable', 'warn');
  } catch {
    _set('jv-mcp', 'unavailable', 'warn');
  }
}

document.addEventListener('DOMContentLoaded', async () => {
  await ensureDevToken();  // localhost: mint the dev token before the first call (production: jarvis.html login gate)
  await loadStatus();
});
