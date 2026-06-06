// ── My Portfolio — allocation builder ──────────────────────
import { api } from './api.js';
import { setEl } from './utils.js';
import { ensureDevToken, isLocalDev } from '../shared/dev-auth.js';

let _instrumentIds = [];

function _updateTotal() {
  let total = 0;
  for (const id of _instrumentIds) {
    const el = document.getElementById(`mp-input-${id}`);
    if (el) total += parseInt(el.value || '0', 10);
  }
  const display = document.getElementById('mp-total-display');
  const bar     = document.getElementById('mp-alloc-bar');
  const btn     = document.getElementById('mp-save-btn');
  if (display) {
    display.textContent = `Total: ${total}%`;
    display.classList.toggle('mp-total-ok',  total === 100);
    display.classList.toggle('mp-total-err', total !== 100);
  }
  if (bar) bar.value = total;
  if (btn) btn.disabled = (total !== 100);
}

function _renderSavedDisplay(data) {
  const el = document.getElementById('mp-saved-display');
  if (!el) return;
  const updatedAt = data.updated_at
    ? new Date(data.updated_at).toLocaleString()
    : '—';
  const rows = (data.holdings || []).map(h =>
    `<tr><td>${h.instrument_id}</td><td>${h.allocation_pct}%</td></tr>`
  ).join('');
  el.innerHTML = `
    <h3 class="mp-saved-title">Saved: ${data.name || 'My Portfolio'}</h3>
    <p class="mp-saved-updated">Last saved: ${updatedAt}</p>
    <table class="mp-saved-table">
      <thead><tr><th>Instrument</th><th>Allocation</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
  el.style.display = '';
}

export async function loadMyPortfolio() {
  _instrumentIds = [];

  // ── Step 1: load instrument list ──────────────────────────
  let instruments = [];
  try {
    const geo = await api('/api/v1/experience/rita/geography-overview');
    for (const region of (geo.regions || [])) {
      for (const inst of (region.instruments || [])) {
        if (inst.id !== 'ATHER') instruments.push(inst);
      }
    }
  } catch (_) {
    setEl('mp-builder', 'Unable to load available instruments. Please refresh.');
    return;
  }

  _instrumentIds = instruments.map(i => i.id);

  // ── Step 2: render instrument cards ───────────────────────
  const cards = instruments.map(i => `
    <div class="mp-card">
      <label for="mp-input-${i.id}" class="mp-label">${i.name}</label>
      <input type="number" id="mp-input-${i.id}"
             min="0" max="100" step="1" value="0"
             oninput="window._mpUpdateTotal()">
    </div>`).join('');
  setEl('mp-instruments', cards);

  // expose _updateTotal for inline oninput
  window._mpUpdateTotal = _updateTotal;

  // ── Step 3: load saved portfolio ──────────────────────────
  const savedEl = document.getElementById('mp-saved-display');
  if (savedEl) savedEl.style.display = 'none';
  setEl('mp-status-msg', '');

  try {
    const portfolio = await api('/api/v1/experience/user-portfolio');
    // 200 — pre-fill inputs
    for (const h of (portfolio.holdings || [])) {
      const inp = document.getElementById(`mp-input-${h.instrument_id}`);
      if (inp) inp.value = h.allocation_pct;
    }
    _renderSavedDisplay(portfolio);
  } catch (err) {
    if (err.message === 'No active portfolio found' || err.message.includes('No active portfolio')) {
      // 404 — first time user, leave inputs at 0, keep saved display hidden
    } else if (err.message) {
      setEl('mp-status-msg', `<span class="mp-err">${err.message}</span>`);
    }
  }

  _updateTotal();
}

export async function savePortfolio() {
  // ── Auth gate ──────────────────────────────────────────────
  await ensureDevToken();
  const token = sessionStorage.getItem('auth_token');
  if (!token) {
    if (!isLocalDev()) {
      sessionStorage.setItem('post_login_redirect', window.location.href);
      window.location.href = '/auth/google/login?state=rita';
    }
    return;
  }

  // ── Build payload ─────────────────────────────────────────
  const holdings = _instrumentIds.map(id => {
    const el = document.getElementById(`mp-input-${id}`);
    return { instrument_id: id, allocation_pct: parseInt(el ? el.value || '0' : '0', 10) };
  });

  const nameEl = document.getElementById('mp-portfolio-name');
  const name   = (nameEl && nameEl.value.trim()) ? nameEl.value.trim() : 'My Portfolio';

  setEl('mp-status-msg', '');

  try {
    const result = await api('/api/v1/user-portfolio', 'POST', { name, holdings });
    if (result) {
      setEl('mp-status-msg', '<span class="mp-ok">Portfolio saved successfully.</span>');
      _renderSavedDisplay(result);
    }
  } catch (err) {
    setEl('mp-status-msg', `<span class="mp-err">${err.message || 'Save failed.'}</span>`);
  }
}
