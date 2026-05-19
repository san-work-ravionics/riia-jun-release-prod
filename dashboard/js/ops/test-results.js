// ── Test Results ───────────────────────────────────────────────────────────
import { apiFetch } from './api.js';
import { badge }    from './utils.js';

// Each suite writes to its own dedicated folder — results from one suite
// can never overwrite results from another suite.
const _RUN_CMDS = `# Run from riia-jun-release/

# E2E — each suite has its own isolated folder
pytest tests/e2e/test_rita_scenarios.py --junitxml=test-results/e2e/rita/latest.xml -v
pytest tests/e2e/test_fno_scenarios.py  --junitxml=test-results/e2e/fno/latest.xml  -v
pytest tests/e2e/test_ops_scenarios.py  --junitxml=test-results/e2e/ops/latest.xml  -v

# Unit
pytest tests/unit/        --junitxml=test-results/unit/latest.xml        -v

# Integration
pytest tests/integration/ --junitxml=test-results/integration/latest.xml -v`;

// Visual config per suite type
const _ST = {
  e2e:         { label: 'E2E',         color: 'var(--sense)',      bg: 'var(--sense-bg)',      bd: 'var(--sense-bd)'      },
  integration: { label: 'Integration', color: 'var(--accelerate)', bg: 'var(--accelerate-bg)', bd: 'var(--accelerate-bd)' },
  unit:        { label: 'Unit',        color: 'var(--optimize)',   bg: 'var(--optimize-bg)',   bd: 'var(--optimize-bd)'   },
  'chrome-extension': { label: 'Chrome UI', color: 'var(--accent)', bg: 'var(--accent-bg)', bd: 'var(--accent-bd)' },
};

export async function loadTestResults() {
  const data = await apiFetch('/api/v1/test-results');
  if (!data) { _showNoData('API error — could not load test results'); return; }
  if (!data.data_available) { _showNoData(); return; }

  _renderSuiteSummary(data.suite_summary || {});
  _renderModuleGrid(data.modules || []);
  _renderOverallKpis(data);
  _renderFailures(data.modules || []);
  _renderRunHistory(data);
}

// ── Suite summary cards ────────────────────────────────────────────────────

function _renderSuiteSummary(summary) {
  for (const [type, cfg] of Object.entries(_ST)) {
    const el = document.getElementById(`ts-${type}`);
    if (!el) continue;

    const s    = summary[type] || { total: 0, passed: 0, failed: 0, run_at: null, module_count: 0, file_exists: false };
    const pct  = s.total > 0 ? Math.round(s.passed / s.total * 100) : 0;
    const ts   = s.run_at ? s.run_at.slice(0, 16).replace('T', ' ') : 'not run yet';
    const modC = s.module_count || '—';

    el.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
        <span class="badge" style="background:${cfg.bg};color:${cfg.color};border:1px solid ${cfg.bd};font-size:10px">${cfg.label}</span>
        ${s.failed > 0
          ? `<span class="badge danger" style="font-size:10px">${s.failed} failed</span>`
          : (s.file_exists ? `<span class="badge ok" style="font-size:10px">passing</span>` : '')}
      </div>
      <div style="font-size:22px;font-weight:700;color:${s.failed > 0 ? 'var(--danger)' : (s.file_exists ? cfg.color : 'var(--t4)')};line-height:1.1">
        ${s.file_exists ? `${s.passed}<span style="font-size:13px;font-weight:400;color:var(--t3)"> / ${s.total}</span>` : '—'}
      </div>
      <div style="font-size:11px;color:var(--t3);margin-top:2px">${modC} module${modC !== 1 ? 's' : ''}</div>
      <div style="margin:10px 0 4px;height:5px;background:var(--border);border-radius:3px;overflow:hidden">
        <div style="height:100%;width:${pct}%;background:${s.failed > 0 ? 'var(--danger)' : cfg.color};border-radius:3px;transition:width .4s"></div>
      </div>`;
      
    // Mini history sparkline
    if (s.runs && s.runs.length > 0) {
      const histBars = s.runs.slice(0, 15).reverse().map(r => {
        const runPct = r.total > 0 ? Math.round(r.passed / r.total * 100) : 0;
        const bg = r.failed > 0 ? 'var(--danger)' : cfg.color;
        // height mapped to pass rate, minimum 2px
        const h = Math.max(2, runPct / 10);
        return `<div style="flex:1;height:${h}px;background:${bg};border-radius:1px;opacity:0.75" title="${runPct}% pass rate"></div>`;
      }).join('');
      el.innerHTML += `<div style="display:flex;gap:2px;height:10px;align-items:flex-end;margin-bottom:6px">${histBars}</div>`;
    }

    el.innerHTML += `<div style="display:flex;justify-content:space-between;font-size:10px;color:var(--t4)">
        <span>${pct}% pass rate</span>
        <span>${ts}</span>
      </div>`;
  }
}

// ── Module grid ────────────────────────────────────────────────────────────

function _renderModuleGrid(modules) {
  const el = document.getElementById('test-module-grid');
  if (!el) return;

  if (modules.length === 0) {
    el.innerHTML = '<div style="font-size:12px;color:var(--t4);padding:8px 0">No modules found</div>';
    return;
  }

  const rows = modules.map(m => {
    const cfg  = _ST[m.suite_type] || _ST.unit;
    const pct  = m.total > 0 ? Math.round(m.passed / m.total * 100) : 0;
    const ts   = m.run_at ? m.run_at.slice(0, 16).replace('T', ' ') : '—';
    const fBdg = m.failed > 0
      ? `<span style="color:var(--danger);font-weight:600">${m.failed}</span>`
      : `<span style="color:var(--t4)">0</span>`;

    return `<tr style="border-bottom:1px solid var(--border)">
      <td style="padding:6px 8px">
        <span style="font-size:10px;font-weight:500;background:${cfg.bg};color:${cfg.color};border:1px solid ${cfg.bd};border-radius:3px;padding:1px 5px">${cfg.label}</span>
      </td>
      <td style="padding:6px 8px;font-family:var(--fm);font-size:11px;color:var(--t2);max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${m.module}</td>
      <td style="padding:6px 8px;text-align:right;font-size:12px;color:var(--t2)">${m.total}</td>
      <td style="padding:6px 8px;text-align:right;font-size:12px;color:var(--ok)">${m.passed}</td>
      <td style="padding:6px 8px;text-align:right;font-size:12px">${fBdg}</td>
      <td style="padding:6px 8px;min-width:80px">
        <div style="display:flex;align-items:center;gap:5px">
          <div style="flex:1;height:4px;background:var(--border);border-radius:2px;overflow:hidden">
            <div style="height:100%;width:${pct}%;background:${m.failed > 0 ? 'var(--danger)' : cfg.color};border-radius:2px"></div>
          </div>
          <span style="font-size:10px;color:var(--t3);min-width:28px;text-align:right">${pct}%</span>
        </div>
      </td>
      <td style="padding:6px 8px;font-size:10px;color:var(--t4);white-space:nowrap">${ts}</td>
    </tr>`;
  }).join('');

  el.innerHTML = `
    <div style="overflow-y:auto;max-height:200px;position:relative">
      <table style="width:100%;border-collapse:collapse">
        <thead>
          <tr style="position:sticky;top:0;background:var(--surface);z-index:1;border-bottom:1.5px solid var(--border)">
            <th style="padding:5px 8px;text-align:left;font-size:10px;color:var(--t3);font-weight:500;text-transform:uppercase;letter-spacing:.04em">Suite</th>
            <th style="padding:5px 8px;text-align:left;font-size:10px;color:var(--t3);font-weight:500;text-transform:uppercase;letter-spacing:.04em">Module</th>
            <th style="padding:5px 8px;text-align:right;font-size:10px;color:var(--t3);font-weight:500;text-transform:uppercase;letter-spacing:.04em">Tests</th>
            <th style="padding:5px 8px;text-align:right;font-size:10px;color:var(--t3);font-weight:500;text-transform:uppercase;letter-spacing:.04em">Passed</th>
            <th style="padding:5px 8px;text-align:right;font-size:10px;color:var(--t3);font-weight:500;text-transform:uppercase;letter-spacing:.04em">Failed</th>
            <th style="padding:5px 8px;font-size:10px;color:var(--t3);font-weight:500;text-transform:uppercase;letter-spacing:.04em">Rate</th>
            <th style="padding:5px 8px;text-align:left;font-size:10px;color:var(--t3);font-weight:500;text-transform:uppercase;letter-spacing:.04em">Last Run</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

// ── Overall KPI strip ──────────────────────────────────────────────────────

function _renderOverallKpis(data) {
  const ids = { 'test-total': data.total, 'test-passed': data.passed, 'test-failed': data.failed };
  for (const [id, val] of Object.entries(ids)) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  }
  const rateEl = document.getElementById('test-rate');
  if (rateEl) rateEl.textContent = data.total > 0 ? data.pass_rate + '%' : '—';
}

// ── Failures table ─────────────────────────────────────────────────────────

function _renderFailures(modules) {
  const el = document.getElementById('test-failures');
  if (!el) return;

  const failures = modules.flatMap(m =>
    (m.cases || []).filter(c => c.status !== 'passed').map(c => ({ ...c, module: m.module, suite_type: m.suite_type }))
  );

  if (failures.length === 0) {
    el.innerHTML = '<div class="al ok" style="margin-top:4px"><svg class="al-ic" width="13" height="13" viewBox="0 0 13 13" fill="none"><path d="M2.5 7l3 3 5-5.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>All tests passing</div>';
    return;
  }

  const rows = failures.map(f => {
    const cfg = _ST[f.suite_type] || _ST.unit;
    return `<tr style="border-bottom:1px solid var(--border)">
      <td style="padding:6px 8px">
        <span style="font-size:10px;font-weight:500;background:${cfg.bg};color:${cfg.color};border:1px solid ${cfg.bd};border-radius:3px;padding:1px 5px">${cfg.label}</span>
      </td>
      <td style="padding:6px 8px;font-family:var(--fm);font-size:11px;color:var(--t2)">${f.module}</td>
      <td style="padding:6px 8px;font-family:var(--fm);font-size:11px;color:var(--t2);max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${f.name}">${f.name}</td>
      <td style="padding:6px 8px;font-size:11px;color:var(--danger);max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${f.message || ''}">${f.message || '—'}</td>
      <td style="padding:6px 8px">${badge('FAIL', 'danger')}</td>
    </tr>`;
  }).join('');

  el.innerHTML = `
    <div style="overflow-y:auto;max-height:252px;position:relative">
      <table style="width:100%;border-collapse:collapse">
        <thead>
          <tr style="position:sticky;top:0;background:var(--surface);z-index:1;border-bottom:1.5px solid var(--border)">
            <th style="padding:5px 8px;text-align:left;font-size:10px;color:var(--t3);font-weight:500;text-transform:uppercase;letter-spacing:.04em">Suite</th>
            <th style="padding:5px 8px;text-align:left;font-size:10px;color:var(--t3);font-weight:500;text-transform:uppercase;letter-spacing:.04em">Module</th>
            <th style="padding:5px 8px;text-align:left;font-size:10px;color:var(--t3);font-weight:500;text-transform:uppercase;letter-spacing:.04em">Test</th>
            <th style="padding:5px 8px;text-align:left;font-size:10px;color:var(--t3);font-weight:500;text-transform:uppercase;letter-spacing:.04em">Error</th>
            <th style="padding:5px 8px;font-size:10px;color:var(--t3);font-weight:500"></th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

// ── Run history grid ───────────────────────────────────────────────────────

function _renderRunHistory(data) {
  const el = document.getElementById('test-run-history');
  if (!el) return;

  const history = [];

  // Unit, integration, and chrome-extension
  for (const type of ['unit', 'integration', 'chrome-extension']) {
    const cfg  = _ST[type];
    const runs = data.suite_summary?.[type]?.runs || [];
    for (const r of runs) {
      history.push({ ...r, cfg, label: cfg.label });
    }
  }

  // E2E suites
  for (const suite of data.suites || []) {
    const cfg = _ST.e2e;
    for (const r of suite.runs || []) {
      history.push({ ...r, cfg, label: `E2E — ${suite.name.toUpperCase()}` });
    }
  }

  if (history.length === 0) {
    el.innerHTML = '<div style="font-size:12px;color:var(--t4);padding:8px 0">No run history yet</div>';
    return;
  }

  // Newest first — use run_at from XML, fall back to run_id timestamp prefix
  history.sort((a, b) => (b.run_at || b.run_id || '').localeCompare(a.run_at || a.run_id || ''));

  const rows = history.map(r => {
    const { cfg } = r;
    const pct  = r.total > 0 ? Math.round(r.passed / r.total * 100) : 0;
    const ts   = r.run_at
      ? r.run_at.slice(0, 16).replace('T', ' ')
      : r.run_id.slice(0, 10) + ' ' + r.run_id.slice(11, 19).replace(/-/g, ':');
    const fBdg = r.failed > 0
      ? `<span style="color:var(--danger);font-weight:600">${r.failed}</span>`
      : `<span style="color:var(--t4)">0</span>`;

    return `<tr style="border-bottom:1px solid var(--border)">
      <td style="padding:6px 8px;white-space:nowrap;font-size:11px;color:var(--t3)">${ts}</td>
      <td style="padding:6px 8px">
        <span style="font-size:10px;font-weight:500;background:${cfg.bg};color:${cfg.color};border:1px solid ${cfg.bd};border-radius:3px;padding:1px 5px">${r.label}</span>
      </td>
      <td style="padding:6px 8px;text-align:right;font-size:12px;color:var(--t2)">${r.total}</td>
      <td style="padding:6px 8px;text-align:right;font-size:12px;color:var(--ok)">${r.passed}</td>
      <td style="padding:6px 8px;text-align:right;font-size:12px">${fBdg}</td>
      <td style="padding:6px 8px;min-width:90px">
        <div style="display:flex;align-items:center;gap:5px">
          <div style="flex:1;height:4px;background:var(--border);border-radius:2px;overflow:hidden">
            <div style="height:100%;width:${pct}%;background:${r.failed > 0 ? 'var(--danger)' : cfg.color};border-radius:2px"></div>
          </div>
          <span style="font-size:10px;color:var(--t3);min-width:28px;text-align:right">${pct}%</span>
        </div>
      </td>
    </tr>`;
  }).join('');

  el.innerHTML = `
    <div style="overflow-y:auto;max-height:200px;position:relative">
      <table style="width:100%;border-collapse:collapse">
        <thead>
          <tr style="position:sticky;top:0;background:var(--surface);z-index:1;border-bottom:1.5px solid var(--border)">
            <th style="padding:5px 8px;text-align:left;font-size:10px;color:var(--t3);font-weight:500;text-transform:uppercase;letter-spacing:.04em">Run Time</th>
            <th style="padding:5px 8px;text-align:left;font-size:10px;color:var(--t3);font-weight:500;text-transform:uppercase;letter-spacing:.04em">Suite</th>
            <th style="padding:5px 8px;text-align:right;font-size:10px;color:var(--t3);font-weight:500;text-transform:uppercase;letter-spacing:.04em">Tests</th>
            <th style="padding:5px 8px;text-align:right;font-size:10px;color:var(--t3);font-weight:500;text-transform:uppercase;letter-spacing:.04em">Passed</th>
            <th style="padding:5px 8px;text-align:right;font-size:10px;color:var(--t3);font-weight:500;text-transform:uppercase;letter-spacing:.04em">Failed</th>
            <th style="padding:5px 8px;font-size:10px;color:var(--t3);font-weight:500;text-transform:uppercase;letter-spacing:.04em">Rate</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

// ── No-data state ──────────────────────────────────────────────────────────

function _showNoData(msg) {
  ['test-total', 'test-passed', 'test-failed', 'test-rate'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.textContent = '—';
  });

  for (const type of Object.keys(_ST)) {
    const el = document.getElementById(`ts-${type}`);
    if (el) el.innerHTML = `<div style="font-size:12px;color:var(--t4);padding:8px 0">Not run yet</div>`;
  }

  const gridEl = document.getElementById('test-module-grid');
  if (gridEl) gridEl.innerHTML = `<div style="font-size:12px;color:var(--t4);padding:8px 0">${msg || 'No test results found'}</div>`;

  const histEl = document.getElementById('test-run-history');
  if (histEl) histEl.innerHTML = '<div style="font-size:12px;color:var(--t4);padding:8px 0">No run history yet</div>';

  const failEl = document.getElementById('test-failures');
  if (failEl) failEl.innerHTML = `
    <div style="padding:8px 0">
      <div style="font-size:12px;color:var(--t3);margin-bottom:8px">${msg || 'Run the tests from the project root to generate results:'}</div>
      <pre style="font-size:11px;font-family:var(--fm);background:var(--surface);border:1px solid var(--border);border-radius:4px;padding:10px 14px;color:var(--text);white-space:pre-wrap">${_RUN_CMDS}</pre>
    </div>`;
}
