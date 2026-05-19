// ── Navigation ────────────────────────────────────────────────────────────────

export const SECTIONS = ['overview','monitoring','cicd','agent-builds','game-compliance','test','deploy','observability','chat','dailyops','users','alerts','source-availability','functional-kpis'];

const loadedSections = new Set(['overview']);

// Populated by main.js after all loader modules are imported
export const sectionLoaders = {};

export function nav(el, id) {
  document.querySelectorAll('.ni').forEach(n => n.classList.remove('on'));
  el.classList.add('on');
  SECTIONS.forEach(s => {
    const sec = document.getElementById('sec-' + s);
    if (sec) sec.classList.toggle('on', s === id);
  });
  // Live data sections always reload; others load once
  const liveReload = ['chat', 'observability'];
  if (liveReload.includes(id)) {
    loadSection(id);
  } else if (!loadedSections.has(id)) {
    loadedSections.add(id);
    loadSection(id);
  }
}

export function loadSection(id) {
  const fn = sectionLoaders[id];
  if (fn) fn();
}
