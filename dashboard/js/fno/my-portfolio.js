// ── FnO My Portfolio — read-only allocation display ──────────────────────────
import { apiBase } from './api.js';

export async function loadFnoMyPortfolio() {
  try {
    const token = sessionStorage.getItem('rita_token');
    const headers = { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) };
    const resp = await fetch(apiBase() + '/api/v1/experience/user-portfolio', { headers });

    if (resp.status === 401) {
      sessionStorage.removeItem('rita_token');
      window.location.href = '/';
      return;
    }

    if (resp.status === 404) {
      const empty = document.getElementById('fno-mp-empty');
      if (empty) empty.style.display = '';
      const table = document.getElementById('fno-mp-table');
      if (table) table.style.display = 'none';
      const total = document.getElementById('fno-mp-total');
      if (total) total.textContent = '—';
      return;
    }

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      const errEl = document.getElementById('fno-mp-error');
      if (errEl) {
        errEl.style.display = '';
        errEl.textContent = 'Unable to load portfolio — ' + (err.detail || resp.statusText);
      }
      const name = document.getElementById('fno-mp-name');
      if (name) name.textContent = '—';
      const updated = document.getElementById('fno-mp-updated');
      if (updated) updated.textContent = '—';
      const total = document.getElementById('fno-mp-total');
      if (total) total.textContent = '—';
      return;
    }

    const data = await resp.json();

    // Hide error/empty, show meta
    const errEl = document.getElementById('fno-mp-error');
    if (errEl) errEl.style.display = 'none';
    const emptyEl = document.getElementById('fno-mp-empty');
    if (emptyEl) emptyEl.style.display = 'none';
    const table = document.getElementById('fno-mp-table');
    if (table) table.style.display = '';

    // Populate name and updated_at
    const nameEl = document.getElementById('fno-mp-name');
    if (nameEl) nameEl.textContent = data.name || '—';
    const updatedEl = document.getElementById('fno-mp-updated');
    if (updatedEl) updatedEl.textContent = data.updated_at ? new Date(data.updated_at).toLocaleString() : '—';

    // Populate holdings rows
    const holdings = data.holdings || [];
    if (holdings.length === 0) {
      const emptyEl2 = document.getElementById('fno-mp-empty');
      if (emptyEl2) emptyEl2.style.display = '';
      if (table) table.style.display = 'none';
    } else {
      const tbody = document.getElementById('fno-mp-holdings-body');
      if (tbody) {
        tbody.innerHTML = holdings.map(h =>
          `<tr><td>${h.instrument_id}</td><td>${h.allocation_pct}%</td></tr>`
        ).join('');
      }
      // Compute total
      const totalPct = holdings.reduce((sum, h) => sum + (h.allocation_pct || 0), 0);
      const totalEl = document.getElementById('fno-mp-total');
      if (totalEl) totalEl.textContent = totalPct + '%';
    }

  } catch (e) {
    const errEl = document.getElementById('fno-mp-error');
    if (errEl) {
      errEl.style.display = '';
      errEl.textContent = 'Unable to load portfolio — ' + (e.message || 'unexpected error');
    }
    const name = document.getElementById('fno-mp-name');
    if (name) name.textContent = '—';
    const updated = document.getElementById('fno-mp-updated');
    if (updated) updated.textContent = '—';
    const total = document.getElementById('fno-mp-total');
    if (total) total.textContent = '—';
  }
}

window.loadFnoMyPortfolio = loadFnoMyPortfolio;
