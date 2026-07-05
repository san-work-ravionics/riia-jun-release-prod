// ── Invest Game App — Navigation ─────────────────────────────────────────────
// Show/hide sections, sidebar toggle, active state management.

let _currentSection = 'investgame';
const _sectionLoaders = {};

export function registerLoader(name, fn) {
  _sectionLoaders[name] = fn;
}

export function show(name, navEl) {
  document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  const sec = document.getElementById('sec-' + name);
  if (sec) sec.classList.add('active');
  if (navEl) navEl.classList.add('active');
  _currentSection = name;
  if (_sectionLoaders[name]) requestAnimationFrame(() => _sectionLoaders[name]());
}

export function toggleSidebar() {
  const sidebar = document.getElementById('sidebar');
  const overlay = document.getElementById('sidebar-overlay');
  if (!sidebar) return;
  const open = sidebar.classList.toggle('open');
  if (overlay) overlay.style.display = open ? 'block' : 'none';
}

export function getCurrentSection() {
  return _currentSection;
}
