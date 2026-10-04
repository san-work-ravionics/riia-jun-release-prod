"""F40 Phase 2 — Save-flow fixes, driven through node against the real dashboard/js tree.

Covers: no PUT on navigation alone; entering Save does not PUT a whatif remap; hwSelectStrategy
-> one debounced PUT with selections; Overview autosave omits last_step (+ source/selections);
explicit save sends last_step 'save' + trigger 'explicit'; loadHedgeWorkflow restores selections
(and the advisor does not overwrite a restored choice); Save step renders latest save with
per-instrument strategy (legacy null selections -> dash) + note, and makes no
/api/v1/portfolio/hedge-history call; hw-save-actions-table is gone from HTML and JS.
Skipped when node is absent.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_JS = _ROOT / "dashboard" / "js"
_FNO = _JS / "fno"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def _node(workdir: Path, source: str) -> object:
    script = workdir / "run.mjs"
    script.write_text(source, encoding="utf-8")
    out = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60, cwd=workdir)
    assert out.returncode == 0, out.stderr[-3000:]
    return json.loads(out.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def jsroot(tmp_path_factory) -> Path:
    dst = tmp_path_factory.mktemp("js40")
    shutil.copytree(_JS, dst / "js")
    (dst / "js" / "package.json").write_text('{"type":"module"}', encoding="utf-8")
    return dst / "js"


_PRELUDE = r"""
import { pathToFileURL } from 'node:url';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const store = {};
globalThis.window = globalThis;
globalThis.sessionStorage = { getItem:k=>store[k]??null, setItem:(k,v)=>{store[k]=String(v)}, removeItem:k=>{delete store[k]} };
globalThis.location = { hostname:'localhost', href:'http://localhost/' };
const els = {};
const WATCH = new Set(['hw-exp-hqs-banner','hw-exp-latest-view','hw-exp-sigma-kpis','hw-stepper','hw-save-history-table','hw-save-history-note','hw-save-summary','hw-save-status']);
globalThis.document = {
  getElementById: (id) => WATCH.has(id) ? (els[id] ??= { innerHTML: '', style: {} }) : null,
  querySelector:()=>null, querySelectorAll:()=>[], addEventListener(){} };
globalThis.Chart = class { constructor(){} destroy(){} update(){} static register(){} };
globalThis.Chart.defaults = { font: {} };
const opts = { portfolio: 'ok', plan: null };
const log = [];
const puts = [];
let setUnderlyingCalls = 0;
globalThis.setUnderlying = () => { setUnderlyingCalls++; };
function jr(body, status = 200) { return { ok: status < 400, status, statusText: 'x', json: async () => body }; }
globalThis.fetch = async (url, o = {}) => {
  const method = (o.method || 'GET').toUpperCase();
  log.push(method + ' ' + url);
  if (url.includes('/user-portfolio')) {
    if (opts.portfolio === 'none') return jr(null, 404);
    return jr({ total_value_eur: 100000, name: 'p', holdings: [
      { instrument_id: 'RELIANCE', allocation_pct: 60, shares: 10, cash_eur: 0 },
      { instrument_id: 'INFY', allocation_pct: 40, shares: 5, cash_eur: 0 }] });
  }
  if (url.includes('/geography-overview')) return jr({ regions: [{ region: 'India', instruments: [
    { id: 'RELIANCE', close: 2500, daily_return_pct: 1.5, return_1y_pct: 12, risk_score: 4 },
    { id: 'INFY', close: 1500, daily_return_pct: 1, return_1y_pct: 8, risk_score: 3 }] }] });
  if (url.includes('/portfolio-analytics')) return jr({ positions: [], greeks: [], net_greeks: {}, hedge_quality: { positions: [] } });
  if (url.includes('/portfolio-hedge')) return jr(null, 404);
  if (url.includes('/equity-hedge-scenarios')) return jr(null, 404);
  if (url.includes('/kite-live')) return jr({ instrument_id: 'RELIANCE', available: false, source: 'fallback', lot_size: 250, quote: null, margin: null, fetched_at: null });
  if (url.includes('/hedge-history')) return jr([]);
  if (url.includes('/hedge-reasoning')) return jr(null, 404);
  if (url.includes('/hedge-plan')) {
    if (method === 'PUT') {
      const body = JSON.parse(o.body);
      puts.push(body);
      return jr({ key_id: 'k', hedged_ids: body.hedged_ids, coverage: body.coverage,
        scenario_tab: body.scenario_tab, duration: '1y', last_step: body.last_step || 'exposure',
        updated_at: new Date().toISOString() });
    }
    return jr(opts.plan);
  }
  return jr(null, 404);
};
const base = pathToFileURL(process.cwd() + '/').href;
const wf = await import(base + 'fno/hedge-workflow.js');
const rec = await import(base + 'fno/hedge-workflow-recommendation.js');
const wi = await import(base + 'fno/hedge-workflow-whatif.js');
const save = await import(base + 'fno/hedge-workflow-save.js');
const { state } = await import(base + 'fno/state.js');
const hw = state.hedgeWorkflow;
"""


def _flow(jsroot: Path, body: str) -> object:
    return _node(jsroot, _PRELUDE + "\n" + body + "\nprocess.exit(0);")


def test_navigation_alone_never_puts_even_with_saved_plan(jsroot):
    r = _flow(jsroot, r"""
hw.savedPlan = { last_step: 'save' };
await wf.hwGoToStep('recommendation', true); await sleep(520);
await wf.hwGoToStep('save', true); await sleep(520);
console.log(JSON.stringify({ puts: puts.length, hist: log.filter(l => l.includes('/hedge-history')).length }));""")
    assert r == {"puts": 0, "hist": 0}   # also: Save step makes no Manoeuvre hedge-history call


def test_autosave_while_on_save_step_omits_last_step_no_whatif_remap(jsroot):
    r = _flow(jsroot, r"""
await wf.hwGoToStep('save', false);
save.hwMarkDirty(); await sleep(520);
console.log(JSON.stringify({ n: puts.length, hasKey: 'last_step' in puts[0], trigger: puts[0].trigger }));""")
    assert r == {"n": 1, "hasKey": False, "trigger": "autosave"}


def test_select_strategy_one_debounced_put_with_selections_and_context(jsroot):
    r = _flow(jsroot, r"""
await wf.hwGoToStep('recommendation', false);
rec.hwSelectStrategy('RELIANCE', 'call_sell');
rec.hwSelectStrategy('INFY', 'put_buy');
await sleep(520);
const b = puts[0];
console.log(JSON.stringify({ n: puts.length, sel: b.selections, step: b.last_step, trigger: b.trigger,
  source: b.source, ctxIds: b.context.instruments.map(i => i.instrument_id).sort(),
  locked: [...hw.selectionLocked].sort() }));""")
    assert r["n"] == 1
    assert r["sel"]["RELIANCE"] == "call_sell" and r["sel"]["INFY"] == "put_buy"
    assert (r["step"], r["trigger"], r["source"]) == ("recommendation", "autosave", "workflow")
    assert r["ctxIds"] == ["INFY", "RELIANCE"] and r["locked"] == ["INFY", "RELIANCE"]


def test_explicit_save_sends_save_and_explicit_trigger(jsroot):
    r = _flow(jsroot, r"""
await wf.hwGoToStep('save', false);
await save.hwSave();
console.log(JSON.stringify({ n: puts.length, step: puts[0].last_step, trigger: puts[0].trigger,
  hasSel: 'selections' in puts[0], status: hw.saveStatus }));""")
    assert r == {"n": 1, "step": "save", "trigger": "explicit", "hasSel": True, "status": "saved"}


def test_overview_autosave_omits_last_step_and_marks_source(jsroot):
    r = _flow(jsroot, r"""
const ph = await import(base + 'fno/portfolio-hedge.js');
try { ph.phSetScenarioTab('collar'); } catch (e) {}
await sleep(520);
console.log(JSON.stringify({ n: puts.length, hasStep: 'last_step' in puts[0], source: puts[0].source,
  trigger: puts[0].trigger, hasSel: 'selections' in puts[0] }));""")
    assert r == {"n": 1, "hasStep": False, "source": "overview", "trigger": "autosave", "hasSel": True}


def test_phpickstrategy_schedules_autosave(jsroot):
    r = _flow(jsroot, r"""
const ph = await import(base + 'fno/portfolio-hedge.js');
try { ph.phPickStrategy('RELIANCE', 'call_sell'); } catch (e) {}
await sleep(520);
console.log(JSON.stringify({ n: puts.length, sel: puts[0] && puts[0].selections }));""")
    assert r["n"] == 1 and r["sel"]["RELIANCE"] == "call_sell"


def test_load_restores_selections_from_saved_plan(jsroot):
    r = _flow(jsroot, r"""
opts.plan = { key_id:'k', hedged_ids:['RELIANCE'], coverage:65, scenario_tab:'ps', duration:'1y', last_step:'save',
  selections: { RELIANCE: 'call_sell', INFY: 'put_buy' }, updated_at:'2026-10-03T00:00:00Z' };
await wf.loadHedgeWorkflow();
const restored = { ...hw.selections };
await wf.hwGoToStep('recommendation', false); await sleep(100);   // seeds defaults for missing ids only
console.log(JSON.stringify({ restored, after: { ...hw.selections }, puts: puts.length }));""")
    assert r["restored"] == {"RELIANCE": "call_sell", "INFY": "put_buy"}
    assert r["after"]["RELIANCE"] == "call_sell" and r["after"]["INFY"] == "put_buy"
    assert r["puts"] == 0


def test_save_step_shows_latest_save_with_strategy_per_instrument(jsroot):
    r = _flow(jsroot, r"""
opts.plan = { key_id:'k', hedged_ids:['RELIANCE','INFY'], coverage:65, scenario_tab:'ps', duration:'1y', last_step:'save',
  selections: { RELIANCE: 'call_sell' }, updated_at:'2026-10-03T00:00:00Z' };
await wf.loadHedgeWorkflow();
await sleep(50);
console.log(JSON.stringify({ table: els['hw-save-history-table'].innerHTML, note: els['hw-save-history-note'].innerHTML,
  hist: log.filter(l => l.includes('/portfolio/hedge-history')).length }));""")
    t = r["table"]
    assert "Saved" in t and "RELIANCE" in t and "INFY" in t
    assert "Covered call" in t                      # RELIANCE call_sell
    assert t.count("<td>—</td>") >= 1               # INFY: legacy/no selection -> dash
    assert "Latest save shown" in r["note"] and "archived" in r["note"]
    assert r["hist"] == 0


def test_save_step_no_saved_plan_message(jsroot):
    r = _flow(jsroot, r"""
await wf.hwGoToStep('save', false); await sleep(50);
console.log(JSON.stringify({ table: els['hw-save-history-table'].innerHTML, note: els['hw-save-history-note'].innerHTML }));""")
    assert "No saved hedge plan yet" in r["table"] and r["note"] == ""


def test_actions_table_removed_everywhere():
    html = (_ROOT / "dashboard" / "fno.html").read_text(encoding="utf-8")
    assert 'id="hw-save-actions-table"' not in html
    assert 'id="hw-save-history-table"' in html and 'id="hw-save-history-note"' in html
    save_js = (_FNO / "hedge-workflow-save.js").read_text(encoding="utf-8")
    for needle in ("hw-save-actions-table", "_renderActionsTable", "/api/v1/portfolio/hedge-history",
                   "not stored with the plan", "history.actions"):
        assert needle not in save_js, needle
