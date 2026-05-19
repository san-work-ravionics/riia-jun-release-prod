import { api } from './api.js';
import { state } from './state.js';

// ── Module-scoped state ──────────────────────────────────────────────────────
let lastResults = null;
let running = false;
let _instrumentList = [];

const STEP_NAMES = [
  'Set Goal','Analyze Market','Design Strategy','Train Model',
  'Set Period','Run Backtest','Get Results','Update Goal'
];

// ── Inline step bar helpers ───────────────────────────────────────────────────
function markIStep(prefix, n, stepState) {
  const el = document.getElementById(`${prefix}-s${n}`);
  if (!el) return;
  el.classList.remove('done','running');
  if (stepState==='done') el.classList.add('done');
  if (stepState==='running') el.classList.add('running');
}

function resetISteps(prefix) { for(let i=1;i<=8;i++) markIStep(prefix,i,'pending'); }

function buildAccordion(accId, stepData) {
  const acc = document.getElementById(accId);
  if (!acc) return;
  acc.style.display='';
  acc.innerHTML = stepData.map((s,i)=>{
    const ok = s.status==='ok'||s.status==='success';
    const dur = s.duration_s ? parseFloat(s.duration_s).toFixed(2)+'s' : '';
    const detail = s.details||{};
    const kvHtml = Object.entries(detail).map(([k,v])=>
      `<div class="step-kv-item"><div class="step-kv-label">${k}</div><div class="step-kv-val">${v}</div></div>`
    ).join('');
    return `
    <div class="step-acc-item">
      <div class="step-acc-hdr" onclick="this.nextElementSibling.classList.toggle('open')">
        <span class="sn">${i+1}</span>
        <span class="st">${s.name||s.step_name||STEP_NAMES[i]}</span>
        <span style="font-family:var(--fm);font-size:10px;color:var(--t3);margin-right:6px">${dur}</span>
        <span class="badge ${ok?'ok':'err'}">${ok?'✓':'✗'}</span>
      </div>
      <div class="step-acc-body">
        ${kvHtml?`<div class="step-kv">${kvHtml}</div>`:'<div style="color:var(--t4);font-size:11px">No detail data.</div>'}
      </div>
    </div>`;
  }).join('');
}

// ── Pipeline runner ───────────────────────────────────────────────────────────
async function runPipeline(forceRetrain) {
  if (running) return;
  const prefix  = forceRetrain ? 'b' : 'r';
  const btnId   = forceRetrain ? 'btn-build' : 'btn-reuse';
  const stepsEl = document.getElementById(forceRetrain ? 'build-steps' : 'reuse-steps');
  const statusEl= document.getElementById(forceRetrain ? 'build-status' : 'reuse-status');
  const accId   = forceRetrain ? 'build-accordion' : 'reuse-accordion';

  const get = id => document.getElementById(id);
  const iid = forceRetrain ? 'b' : 'r';
  const selectedInstrumentId = get(`${iid}-instrument`)?.value || state.activeInst?.id || '';
  const seeds = parseInt(get('b-seeds')?.value || 3);

  const body = {
    instrument: selectedInstrumentId,
    target_return_pct:15, time_horizon_days:252, risk_tolerance:'moderate',
    force_retrain: forceRetrain,
    n_seeds: seeds,
    sim_start: get(`${iid}-start`).value||null,
    sim_end:   get(`${iid}-end`).value||null
  };
  if (forceRetrain) {
    body.timesteps = parseInt(get('b-timesteps').value);
  }

  const totalTimesteps = forceRetrain
    ? (parseInt(get('b-timesteps')?.value||100000) * seeds)
    : 0;

  running = true;
  get(btnId).disabled = true;
  stepsEl.classList.add('visible');
  resetISteps(prefix);
  statusEl.innerHTML = '<span class="spinner"></span>Switching instrument…';

  if (selectedInstrumentId) {
    try {
      await api('/api/v1/instrument/select', 'POST', { instrument_id: selectedInstrumentId });
      await loadActiveInstrument();
    } catch(e) {
      statusEl.innerHTML = `<span class="badge err" style="font-size:11px">✗ Could not select instrument: ${e.message}</span>`;
      running = false;
      get(btnId).disabled = false;
      return;
    }
  }

  statusEl.innerHTML = '<span class="spinner"></span>Starting pipeline…';

  const STEP_KEYS = [
    'step1_goal_set','step2_market_analyzed','step3_strategy_designed',
    'step4_model_trained','step5_period_set','step6_backtest_run',
    'step7_results_ready','step8_goal_updated'
  ];

  let pollTimer = null;
  let lastRunningStep = 1;
  let seenInProgress = false;

  async function pollProgress() {
    try {
      const prog = await api('/progress');
      const stepsArr = Array.isArray(prog.steps) ? prog.steps : [];
      const steps = {};
      STEP_KEYS.forEach((k, i) => {
        const s = stepsArr[i];
        steps[k] = s ? (s.status === 'completed') : false;
      });

      let runningStep = null;
      for (let i = 0; i < STEP_KEYS.length; i++) {
        if (!steps[STEP_KEYS[i]]) { runningStep = i + 1; break; }
      }

      if (runningStep === null && !seenInProgress) {
        pollTimer = setTimeout(pollProgress, 2000);
        return;
      }
      if (!seenInProgress) seenInProgress = true;

      if (runningStep === null) {
        for (let i = 1; i <= 8; i++) markIStep(prefix, i, 'done');
        statusEl.innerHTML = '<span class="badge ok" style="font-size:11px">✓ Complete</span>';
        try {
          const log = await api('/api/experience/ops/step-log');
          if (log && log.length) buildAccordion(accId, log);
        } catch(e) {}
        await loadActiveInstrument();
        running = false;
        get(btnId).disabled = false;
        // Use window.show to avoid circular dependency with nav.js
        setTimeout(() => { const n = document.querySelector('[data-s="dashboard"]'); window.show('dashboard', n); }, 800);
        return;
      }

      lastRunningStep = runningStep;

      for (let i = 1; i <= 8; i++) {
        if (steps[STEP_KEYS[i-1]]) markIStep(prefix, i, 'done');
        else if (i === runningStep)  markIStep(prefix, i, 'running');
      }

      if (runningStep === 4 && forceRetrain) {
        api('/api/v1/training-progress').then(rows => {
          if (rows && rows.length) {
            const maxTs = Math.max(...rows.map(r => parseInt(r.timestep)||0));
            const pct   = totalTimesteps > 0 ? Math.min(Math.round(maxTs / totalTimesteps * 100), 99) : '?';
            statusEl.innerHTML = `<span class="spinner"></span>Step 4 — Training… ${maxTs.toLocaleString()} / ${totalTimesteps.toLocaleString()} steps (${pct}%)`;
          } else {
            statusEl.innerHTML = '<span class="spinner"></span>Step 4 — Model Training…';
          }
        }).catch(() => {
          statusEl.innerHTML = '<span class="spinner"></span>Step 4 — Model Training…';
        });
      } else {
        statusEl.innerHTML = `<span class="spinner"></span>Step ${runningStep} — ${STEP_NAMES[runningStep-1]}…`;
      }
    } catch(e) { /* keep polling silently */ }

    pollTimer = setTimeout(pollProgress, 2000);
  }

  pollProgress();

  try {
    await api('/api/v1/pipeline', 'POST', body);
  } catch(e) {
    clearTimeout(pollTimer);
    markIStep(prefix, lastRunningStep, 'pending');
    statusEl.innerHTML = `<span class="badge err" style="font-size:11px">✗ ${e.message}</span>`;
    running = false;
    get(btnId).disabled = false;
  }
}

export function runBuild()  { runPipeline(true);  }
export function runReuse()  { runPipeline(false); }

export async function resetSession() {
  if(!confirm('Reset pipeline session? In-memory results will be cleared.')) return;
  try {
    await api('/reset', 'POST');
    lastResults=null;
    ['build-steps','reuse-steps'].forEach(id=>document.getElementById(id).classList.remove('visible'));
    ['build-status','reuse-status'].forEach(id=>document.getElementById(id).innerHTML='');
    ['build-accordion','reuse-accordion'].forEach(id=>{ document.getElementById(id).style.display='none'; document.getElementById(id).innerHTML=''; });
    resetISteps('b'); resetISteps('r');
  } catch(e) { alert('Reset failed: '+e.message); }
}

// ── Instruments ───────────────────────────────────────────────────────────────
export async function loadInstruments() {
  try {
    const d = await api('/api/v1/instruments');
    const raw = Array.isArray(d) ? d : (d.instruments||[]);
    _instrumentList = raw.map(i => typeof i === 'string'
      ? { id: i, name: i }
      : { id: i.id||i.name||'nifty', name: i.name||i.symbol||i.id||'NIFTY' });
    if (!_instrumentList.length) _instrumentList = [{ id:'nifty', name:'NIFTY' }];
  } catch(e){ _instrumentList = [{ id:'nifty', name:'NIFTY' }]; }

  ['b-instrument','r-instrument'].forEach(selId => {
    const sel = document.getElementById(selId);
    if (sel) sel.innerHTML = _instrumentList.map(i => `<option value="${i.id}">${i.name}</option>`).join('');
  });
}

// ── Status check ──────────────────────────────────────────────────────────────
export async function checkStatus() {
  const dot=document.getElementById('status-dot');
  const txt=document.getElementById('status-text');
  const sbD=document.getElementById('sb-data-info');
  const sbM=document.getElementById('sb-model-info');
  try {
    const h=await api('/health');
    dot.className='status-dot ok'; txt.textContent='API Online';
    if(h.latest_date) sbD.textContent=`Data: through ${h.latest_date}`;
    else if(h.data_rows) sbD.textContent=`Data: ${h.data_rows} rows`;
    if(h.model_file) sbM.textContent=`Model: ${h.model_file}`;
  } catch(e) {
    dot.className='status-dot err'; txt.textContent='API Offline';
    sbD.textContent='Data: unavailable'; sbM.textContent='Model: unavailable';
  }
}

// ── Active instrument pill ────────────────────────────────────────────────────
export async function loadActiveInstrument() {
  try {
    const inst = await api('/api/v1/instrument/active');
    if (!inst || !inst.id) return;
    state.activeInst = inst;

    const pill = document.getElementById('inst-pill');
    document.getElementById('inst-pill-flag').textContent = inst.flag || '';
    document.getElementById('inst-pill-name').textContent = inst.name || inst.id;
    document.getElementById('inst-pill-exch').textContent = inst.exchange ? `· ${inst.exchange}` : '';
    pill.style.display = 'flex';

    const sbInfo = document.getElementById('sb-data-info');
    if (sbInfo) sbInfo.textContent = `${inst.flag||''} ${inst.name||inst.id} · ${inst.exchange||''}`.trim();

    ['b-instrument', 'r-instrument'].forEach(selId => {
      const sel = document.getElementById(selId);
      if (sel) sel.value = inst.id;
    });

    const n = inst.name || inst.id;
    const _upd = (id, txt) => { const el = document.getElementById(id); if (el) el.textContent = txt; };
    _upd('perf-page-sub',    `Backtest results — DDQN strategy vs ${n} Buy & Hold`);
    _upd('trades-page-sub',  `Model entry/exit signals overlaid on ${n} price — phase-by-phase analysis`);
    _upd('trades-chart-title', `${n} Close — ▲ Entry · ▼ Profit Exit · ✕ Loss Exit (All Phases)`);
  } catch { /* silently skip */ }
}
