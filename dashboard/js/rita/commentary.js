// ── AI Commentary — typewriter narrative for overview and strategy pages ──────
import { api } from './api.js';

// Module-level typewriter cancel token — incremented each call to cancel in-flight animation
let _twToken = 0;

/**
 * Internal typewriter renderer.
 * @param {string} titleId  - DOM id of the title element
 * @param {string} textId   - DOM id of the text element
 * @param {string} title    - Heading to set immediately
 * @param {string} text     - Body text to type character-by-character
 * @param {number} speed    - Milliseconds per character (default 10)
 */
function _showCommentaryNarrator(titleId, textId, title, text, speed = 10) {
  const titleEl = document.getElementById(titleId);
  const textEl  = document.getElementById(textId);
  if (!titleEl || !textEl) return;

  titleEl.textContent = title;
  textEl.textContent  = '';

  // Cancel any in-flight typewriter
  _twToken += 1;
  const myToken = _twToken;

  let i = 0;
  function step() {
    if (_twToken !== myToken) return;   // cancelled by a newer call
    if (i < text.length) {
      textEl.textContent += text[i];
      i += 1;
      setTimeout(step, speed);
    }
  }
  step();
}

/**
 * Show the overview commentary narrator box.
 * @param {string} text - Narrative text to display
 */
export function showOverviewCommentary(text) {
  const box = document.getElementById('commentary-overview-box');
  if (box) box.style.display = '';
  _showCommentaryNarrator(
    'commentary-overview-title',
    'commentary-overview-text',
    'Agent Commentary',
    text,
    10
  );
}

/**
 * Show the strategy commentary narrator box.
 * @param {string} text - Narrative text to display
 */
export function showStrategyCommentary(text) {
  const box = document.getElementById('commentary-strategy-box');
  if (box) box.style.display = '';
  _showCommentaryNarrator(
    'commentary-strategy-title',
    'commentary-strategy-text',
    'Agent Commentary',
    text,
    10
  );
}

/**
 * Load and display overview commentary.
 * Called at end of loadMarketSignals() after loadGeoPanels().
 * Shows '—' on failure; never throws.
 */
export async function loadOverviewCommentary() {
  try {
    const res = await api('/api/v1/commentary', 'POST', { app: 'rita', page: 'overview' });
    const text = (res && res.commentary) ? res.commentary : '—';
    showOverviewCommentary(text);
  } catch (_) {
    showOverviewCommentary('—');
  }
}
