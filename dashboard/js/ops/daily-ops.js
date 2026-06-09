// ── Daily Ops ─────────────────────────────────────────────────────────────────
import { apiFetch, apiBase, api } from './api.js';
import { t } from '../shared/i18n.js';

// ── Instrument availability ────────────────────────────────────────────────────

let _instruments = [];       // current state from DB
let _pendingChanges = {};    // instrument_id -> bool (toggled but not yet saved)

export async function loadInstruments() {
  const data = await apiFetch('/api/v1/instruments');
  const wrap = document.getElementById('dops-instruments');
  if (!data || !data.length) {
    wrap.innerHTML = `<div style="font-size:12px;color:var(--t3);">${t('ops.no_instruments')}</div>`;
    return;
  }
  _instruments = data;
  _pendingChanges = {};
  renderInstruments();
}

function renderInstruments() {
  const wrap = document.getElementById('dops-instruments');
  wrap.innerHTML = _instruments.map(inst => {
    const pending  = _pendingChanges.hasOwnProperty(inst.id);
    const isOn     = pending ? _pendingChanges[inst.id] : inst.data_ready;
    const changed  = pending && isOn !== inst.data_ready;
    return `
      <div style="display:flex;align-items:center;gap:8px;padding:8px 12px;border-radius:6px;
                  background:${isOn ? 'var(--build-bg,#e8f5e9)' : 'var(--bg2,#f5f5f5)'};
                  border:1.5px solid ${changed ? 'var(--warn,#e6a817)' : isOn ? 'var(--build,#1a6b3c)' : 'var(--bdr,#ddd)'};
                  cursor:pointer;"
           onclick="toggleInstrument('${inst.id}')"
           title="${isOn ? 'Click to disable' : 'Click to enable'}">
        <div style="width:10px;height:10px;border-radius:50%;background:${isOn ? 'var(--build,#1a6b3c)' : 'var(--t3,#aaa)'};flex-shrink:0;"></div>
        <div>
          <div style="font-size:12px;font-weight:600;color:var(--t1);">${inst.name || inst.id}</div>
          <div style="font-size:10px;color:var(--t3);">${inst.exchange || ''} · ${inst.id}</div>
        </div>
        ${changed ? '<span style="font-size:9px;font-family:var(--fm);color:var(--warn);margin-left:4px;">unsaved</span>' : ''}
      </div>`;
  }).join('');
}

export function toggleInstrument(instrumentId) {
  const inst = _instruments.find(i => i.id === instrumentId);
  if (!inst) return;
  const currentState = _pendingChanges.hasOwnProperty(instrumentId)
    ? _pendingChanges[instrumentId]
    : inst.data_ready;
  _pendingChanges[instrumentId] = !currentState;

  const hasChanges = Object.keys(_pendingChanges).some(
    id => _pendingChanges[id] !== (_instruments.find(i => i.id === id) || {}).data_ready
  );
  document.getElementById('btn-save-instruments').style.display = hasChanges ? '' : 'none';
  renderInstruments();
}

export async function saveInstruments() {
  const btn = document.getElementById('btn-save-instruments');
  btn.disabled = true;
  btn.textContent = t('ops.saving');

  const toSave = Object.entries(_pendingChanges).filter(
    ([id, val]) => val !== (_instruments.find(i => i.id === id) || {}).data_ready
  );

  let allOk = true;
  for (const [id, isAvailable] of toSave) {
    try {
      const r = await fetch(
        `${apiBase()}/api/v1/instruments/${id}/availability?is_available=${isAvailable}`,
        { method: 'PATCH', headers: { 'Content-Type': 'application/json' } }
      );
      if (!r.ok) { allOk = false; }
    } catch { allOk = false; }
  }

  if (allOk) {
    btn.textContent = t('ops.saved');
    setTimeout(() => { btn.style.display = 'none'; btn.textContent = t('btn.save'); btn.disabled = false; }, 1500);
    await loadInstruments();   // refresh from DB
  } else {
    btn.textContent = t('ops.error_retry');
    btn.disabled = false;
  }
}

export async function loadDailyOps() {
  const d = await apiFetch('/api/v1/portfolio/man-daily-status');
  if (!d) {
    document.getElementById('dops-kpi-strip').innerHTML =
      '<div class="kpi"><div class="kpi-ey">Status</div><div class="kpi-val danger">Unavailable</div></div>';
    return;
  }

  const months = d.active_months || [];
  const ss     = d.snapshot_status || {};

  // ── KPI strip ──
  const snappedToday  = months.filter(m => ss[m] && ss[m].snapshotted_today).length;
  const totalMonths   = months.length;
  const actionsToday  = d.actions_today || 0;
  const lastActionTs  = d.last_action_ts ? d.last_action_ts.replace('T',' ').replace('Z','') : '—';
  const statusClass   = snappedToday === totalMonths && totalMonths > 0 ? 'ok' : totalMonths > 0 ? 'warn' : 'ops';

  document.getElementById('dops-kpi-strip').innerHTML = `
    <div class="kpi">
      <div class="kpi-ey">Today's Snapshots</div>
      <div class="kpi-val ${statusClass}">${snappedToday} / ${totalMonths}</div>
      <div class="kpi-sub">${d.today || '—'}</div>
    </div>
    <div class="kpi">
      <div class="kpi-ey">Active Months</div>
      <div class="kpi-val">${months.join(' · ') || '—'}</div>
      <div class="kpi-sub">from live positions</div>
    </div>
    <div class="kpi">
      <div class="kpi-ey">Actions Today</div>
      <div class="kpi-val ${actionsToday > 0 ? 'ok' : ''}">${actionsToday}</div>
      <div class="kpi-sub">drag-drop events logged</div>
    </div>
    <div class="kpi">
      <div class="kpi-ey">Last Action</div>
      <div class="kpi-val" style="font-size:13px;">${lastActionTs}</div>
      <div class="kpi-sub">UTC</div>
    </div>`;

  // ── Per-month cards ──
  const cardsHtml = months.length ? months.map(m => {
    const s        = ss[m] || {};
    const snapped  = s.snapshotted_today;
    const hasSaved = s.groups_saved;
    const badge    = snapped
      ? '<span class="badge ok">✓ Snapped</span>'
      : '<span class="badge warn">⚠ Pending</span>';
    const groupsBadge = hasSaved
      ? '<span class="badge ok">Groups saved</span>'
      : '<span class="badge neutral">No groups</span>';
    return `
      <div class="card" style="margin-bottom:8px;">
        <div style="display:flex;align-items:center;justify-content:space-between;padding:10px 12px;border-bottom:1px solid var(--bdr);">
          <div style="font-size:13px;font-weight:600;">${m} 2026</div>
          <div style="display:flex;gap:5px;align-items:center;">${badge}${groupsBadge}</div>
        </div>
        <div style="padding:10px 12px;display:flex;gap:16px;flex-wrap:wrap;">
          <div class="sb"><div class="sb-l">Last snapshot</div><div class="sb-v">${s.last_date || '—'}</div></div>
          <div class="sb"><div class="sb-l">Lots today</div><div class="sb-v">${s.lot_count || 0}</div></div>
          <div style="margin-left:auto;">
            <button class="btn-sm" onclick="triggerSnapshot('${m}')" title="Run server-side snapshot now">
              ▶ Run Snapshot
            </button>
          </div>
        </div>
      </div>`;
  }).join('') : `<div style="font-size:12px;color:var(--t3);padding:8px 0;">${t('ops.no_active_months')}</div>`;

  document.getElementById('dops-month-cards').innerHTML = cardsHtml;

  // ── Notes ──
  const notes = d.recent_notes || [];
  document.getElementById('dops-notes').innerHTML = notes.length
    ? notes.slice().reverse().map(n => `
        <div style="padding:8px 10px;border-radius:5px;background:var(--bg2);margin-bottom:5px;">
          <div style="font-size:9px;font-family:var(--fm);color:var(--t3);margin-bottom:3px;">
            ${n.date} · ${n.month} · ${(n.ts||'').replace('T',' ').replace('Z','')} UTC
          </div>
          <div style="font-size:12px;color:var(--t1);">${n.notes || '<em style="color:var(--t4)">no note</em>'}</div>
        </div>`).join('')
    : `<div style="font-size:12px;color:var(--t3);padding:8px 0;">${t('ops.no_notes')}</div>`;

  // ── History table ──
  const rows = d.recent_snapshots || [];
  document.getElementById('dops-history-tbody').innerHTML = rows.length
    ? rows.slice().reverse().map(r => `
        <tr>
          <td>${r.date || '—'}</td>
          <td><span class="badge neutral">${r.month || '—'}</span></td>
          <td style="font-family:var(--fm);">${r.nifty_spot ? Number(r.nifty_spot).toLocaleString('en-IN',{minimumFractionDigits:2}) : '—'}</td>
          <td>${r.lot_count || '—'}</td>
        </tr>`).join('')
    : `<tr><td colspan="4" style="text-align:center;color:var(--t3);">${t('ops.no_history')}</td></tr>`;
}

export async function triggerSnapshot(month) {
  const btn = event.target;
  btn.disabled = true; btn.textContent = 'Running…';
  try {
    const res = await fetch(apiBase() + '/api/v1/portfolio/man-daily-snapshot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ month }),
    });
    const data = await res.json();
    if (data.status === 'ok') {
      btn.textContent = '✓ Done';
      setTimeout(() => loadDailyOps(), 600);
    } else {
      btn.textContent = data.reason || 'Skipped';
      btn.disabled = false;
    }
  } catch(e) {
    btn.textContent = 'Error';
    btn.disabled = false;
  }
}

// ── Instrument Onboard ────────────────────────────────────────────────────────

export async function searchInstrument() {
  const q = document.getElementById('dops-search-input').value.trim();
  if (q.length < 2) {
    document.getElementById('dops-search-results').innerHTML = '<p class="text-muted">Enter at least 2 characters.</p>';
    return;
  }
  document.getElementById('dops-search-results').innerHTML = '<p class="text-muted">Searching…</p>';
  try {
    const results = await api(`/api/v1/instrument/search?q=${encodeURIComponent(q)}`);
    if (!results || results.length === 0) {
      document.getElementById('dops-search-results').innerHTML = `<p class="text-muted">No results found for "${q}".</p>`;
      return;
    }
    const rows = results.map(r => {
      const displayName = r.name || r.ticker;
      const canOnboard = r.name && r.exchange;
      return `<div class="search-result-row d-flex justify-content-between align-items-center py-1 border-bottom">
        <span><strong>${r.ticker}</strong> — ${displayName} (${r.exchange || '—'}, ${r.currency || '—'})</span>
        <button class="btn btn-sm btn-outline-primary ms-2" ${canOnboard ? '' : 'disabled'}
          onclick="onboardInstrument('${r.ticker}','${(r.name||'').replace(/'/g,"\\'")}','${r.exchange||''}','${r.currency||''}','${r.country||''}')">
          Onboard
        </button>
      </div>`;
    }).join('');
    document.getElementById('dops-search-results').innerHTML = rows;
  } catch (e) {
    document.getElementById('dops-search-results').innerHTML = '<p class="text-danger">Search failed. Please try again.</p>';
  }
}

export async function onboardInstrument(ticker, name, exchange, currency, countryCode) {
  const statusEl = document.getElementById('dops-onboard-status');
  statusEl.innerHTML = `<p class="text-muted">Onboarding <strong>${ticker}</strong>…</p>`;
  try {
    const resp = await fetch(apiBase() + '/api/v1/instrument/onboard', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ticker, name, exchange, currency, country_code: countryCode, lot_size: null })
    });
    if (resp.status === 409) {
      statusEl.innerHTML = `<p class="text-warning"><strong>${ticker}</strong> is already onboarded.</p>`;
      return;
    }
    if (resp.status === 502) {
      statusEl.innerHTML = '<p class="text-danger">Yahoo Finance is unavailable — try again shortly.</p>';
      return;
    }
    if (!resp.ok) {
      let detail = 'Onboard failed.';
      try { const j = await resp.json(); detail = j.detail || detail; } catch (_) {}
      statusEl.innerHTML = `<p class="text-danger">${detail}</p>`;
      return;
    }
    const data = await resp.json();
    if (data.status === 'ok') {
      statusEl.innerHTML = `<p class="text-success"><strong>${data.ticker}</strong> onboarded — ${data.rows_fetched} rows fetched, ${data.rows_seeded} seeded.</p>`;
    } else {
      statusEl.innerHTML = `<p class="text-warning">Onboard returned unexpected status: ${data.status}</p>`;
    }
  } catch (e) {
    statusEl.innerHTML = '<p class="text-danger">Onboard request failed. Please try again.</p>';
  }
}
