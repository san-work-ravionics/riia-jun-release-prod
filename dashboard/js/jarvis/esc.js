// Jarvis — HTML escaping. Every server string goes through esc() (or textContent) before innerHTML.
const _MAP = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

export function esc(v) {
  if (v === null || v === undefined) return '';
  return String(v).replace(/[&<>"']/g, ch => _MAP[ch]);
}
