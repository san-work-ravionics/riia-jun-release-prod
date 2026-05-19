// ── Navigation ─────────────────────────────────────────────
// API base — reads window.RITA_API_BASE if set (staging/cross-origin), otherwise same origin.
const API = (window.RITA_API_BASE || '').replace(/\/$/, '');

export let _currentSection = 'market-signals';
export let _mcpPollTimer = null;
let _chatWarmedUp = false;

export async function warmupChat(force = false) {
  if (_chatWarmedUp && !force) return null;
  _chatWarmedUp = true;
  try {
    const inst = (localStorage.getItem('ritaInstrument') || 'NIFTY').toUpperCase();
    const res = await fetch(`${API}/api/v1/chat/warmup?instrument=${inst}`, { method: 'POST' });
    if (!res.ok) return null;
    const data = await res.json();
    return { chips: data.chips || _fallbackChips(), alerts: data.alerts || null };
  } catch {
    return { chips: _fallbackChips(), alerts: null };
  }
}

function _fallbackChips() {
  return [
    { label: 'Overall market sentiment today?',   query: 'What is the current market sentiment?' },
    { label: 'Is the market overbought/oversold?', query: 'Is the market overbought or oversold?' },
    { label: 'How has RITA performed historically?', query: 'How has RITA model performed historically?' },
    { label: '3-year return outlook?',             query: '3 year return estimate' },
  ];
}

// Section loaders map — populated by main.js after all modules are imported
export const _sectionLoaders = {};

export function show(name, navEl) {
  document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  const sec = document.getElementById('sec-' + name);
  if (sec) sec.classList.add('active');
  if (navEl) navEl.classList.add('active');
  _currentSection = name;
  if (_sectionLoaders[name]) requestAnimationFrame(() => _sectionLoaders[name]());

  // Auto-refresh MCP Calls page every 10s while active; stop when leaving
  clearInterval(_mcpPollTimer);
  if (name === 'mcp') {
    _mcpPollTimer = setInterval(_sectionLoaders['mcp'], 10000);
  }
}

export function getCurrentSection() {
  return _currentSection;
}
