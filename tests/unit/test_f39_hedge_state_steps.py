"""F39 Phase 4 (Tier A) — state / step-navigation unit tests, driven through node.

Covers (Architect edge cases 1, 5, 9): hwGoToStep order/reached/persist, stale-token on
rapid step navigation, hwSelectInstrument per step (no /instrument/select, no
setUnderlying), hwToggleHedged / hwSelectStrategy / hwSetCoverage / hwSetScenarioTab
dirty+autosave behaviour, ensureExposure on restore, the autosave condition
``dirty || savedPlan`` (pinned as CURRENT behaviour), loadHedgeWorkflow with no portfolio,
redirect aliases, and the Overview autosave omitting ``last_step`` (finding 7, pinned).

Uses the real dashboard/js tree with stubbed browser globals and a routed fetch.
Skipped when node is absent.
"""
from __future__ import annotations

import json
import re
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
    out = subprocess.run(
        ["node", str(script)], capture_output=True, text=True, timeout=60, cwd=workdir
    )
    assert out.returncode == 0, out.stderr[-3000:]
    return json.loads(out.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def jsroot(tmp_path_factory) -> Path:
    dst = tmp_path_factory.mktemp("js")
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
const WATCH = new Set(['hw-exp-hqs-banner','hw-exp-latest-view','hw-exp-sigma-kpis','hw-stepper']);
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


# ── hwGoToStep: order / reached / persist ───────────────────────────────────────────

def test_gotostep_unknown_step_falls_back_to_exposure_and_reached_accumulates(jsroot):
    r = _flow(jsroot, r"""
await wf.hwGoToStep('bogus', false);
const a = hw.step;
await wf.hwGoToStep('whatif', false);
await wf.hwGoToStep('recommendation', false);
console.log(JSON.stringify({ a, step: hw.step, reached: [...hw.reached], puts: puts.length,
  stepper: els['hw-stepper'].innerHTML.includes('hw-step--active') }));""")
    assert r["a"] == "exposure" and r["step"] == "recommendation"
    assert set(r["reached"]) == {"exposure", "whatif", "recommendation"}
    assert r["puts"] == 0              # persist=false never writes
    assert r["stepper"] is True


def test_autosave_condition_is_dirty_or_savedplan_pinned_current_behaviour(jsroot):
    """Pins CURRENT behaviour: persist=true writes only if (dirty || savedPlan)."""
    r = _flow(jsroot, r"""
await wf.hwGoToStep('recommendation', true); await sleep(520);
const clean = puts.length;                               // neither dirty nor savedPlan
hw.dirty = true;
await wf.hwGoToStep('whatif', true); await sleep(520);
const dirtyWrites = puts.map(p => p.last_step);
hw.dirty = false; hw.savedPlan = { last_step: 'exposure' };
await wf.hwGoToStep('recommendation', true); await sleep(520);
const withPlan = puts.map(p => p.last_step);
await wf.hwGoToStep('exposure', false); await sleep(520);
console.log(JSON.stringify({ clean, dirtyWrites, withPlan, final: puts.length }));""")
    assert r["clean"] == 0
    assert r["dirtyWrites"] == ["whatif"]
    assert r["withPlan"] == ["whatif", "recommendation"]
    assert r["final"] == 2             # persist=false (restore/refresh) never writes


def test_gotostep_stale_token_on_rapid_navigation_only_latest_step_loads(jsroot):
    """Edge 9: the superseded navigation returns before loading its step or persisting."""
    r = _flow(jsroot, r"""
hw.dirty = true;
const p1 = wf.hwGoToStep('recommendation', true);   // starts first, superseded
const p2 = wf.hwGoToStep('whatif', true);
await Promise.all([p1, p2]); await sleep(520);
console.log(JSON.stringify({ step: hw.step, writes: puts.map(p => p.last_step),
  reasoning: log.filter(l => l.includes('/hedge-reasoning')).length,
  kite: log.filter(l => l.includes('/kite-live')).length > 0,
  whatifHedge: log.filter(l => l.includes('/portfolio-hedge')).length > 0 }));""")
    assert r["step"] == "whatif"
    assert r["writes"] == ["whatif"]
    assert r["reasoning"] == 0, "superseded recommendation step must not load the advisor"
    assert r["whatifHedge"] is True


def test_control_direct_recommendation_visit_does_call_advisor(jsroot):
    """Control for the stale-token test: the advisor fetch is observable when not superseded."""
    r = _flow(jsroot, r"""
await wf.hwGoToStep('recommendation', false); await sleep(50);
console.log(JSON.stringify(log.filter(l => l.includes('/hedge-reasoning')).length));""")
    assert r >= 1


# ── hwSelectInstrument ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("step", ["exposure", "recommendation", "whatif", "save"])
def test_select_instrument_never_posts_instrument_select_or_calls_set_underlying(jsroot, step):
    r = _flow(jsroot, f"""
await wf.hwGoToStep({json.dumps(step)}, false);
log.length = 0;
wf.hwSelectInstrument('INFY'); await sleep(80);
console.log(JSON.stringify({{ id: hw.instrumentId, log: [...log], su: setUnderlyingCalls }}));""")
    assert r["id"] == "INFY"
    assert r["su"] == 0
    assert not any("/instrument/select" in line for line in r["log"]), r["log"]
    kite = [line for line in r["log"] if "/kite-live" in line]
    # What-if skips the direct _fetchLiveData (loadWhatIfStep fetches kite-live itself, once)
    if step == "whatif":
        assert len(kite) == 1 and any("/portfolio-hedge" in line for line in r["log"])
    else:
        assert len(kite) >= 1


# ── dirty flag + autosave from controls ─────────────────────────────────────────────

def test_toggle_hedged_marks_dirty_and_autosaves_with_current_step(jsroot):
    r = _flow(jsroot, r"""
await wf.hwGoToStep('recommendation', false);
const before = [...hw.hedgedIds];
rec.hwToggleHedged('RELIANCE');
const dirty = hw.dirty;
await sleep(520);
console.log(JSON.stringify({ before, after: hw.hedgedIds, dirty, dirtyAfter: hw.dirty, put: puts[0] }));""")
    assert r["dirty"] is True and r["dirtyAfter"] is False
    assert "RELIANCE" not in r["after"] and "RELIANCE" in r["before"]
    assert r["put"]["last_step"] == "recommendation"
    assert r["put"]["hedged_ids"] == r["after"]


def test_select_strategy_does_not_mark_dirty_pinned_current_behaviour(jsroot):
    """Pins CURRENT behaviour: strategy selection is session-only (not part of the plan body)."""
    r = _flow(jsroot, r"""
await wf.hwGoToStep('recommendation', false);
rec.hwSelectStrategy('RELIANCE', 'call_sell');
rec.hwSelectStrategy('RELIANCE', 'not_a_strategy');   // ignored
await sleep(520);
console.log(JSON.stringify({ sel: hw.selections.RELIANCE, dirty: hw.dirty, puts: puts.length }));""")
    assert r == {"sel": "call_sell", "dirty": False, "puts": 0}


def test_set_scenario_tab_dirty_autosave_and_unknown_tab_ignored(jsroot):
    r = _flow(jsroot, r"""
await wf.hwGoToStep('whatif', false); await sleep(50);
wi.hwSetScenarioTab('bogus');
const ignored = { tab: hw.scenarioTab, dirty: hw.dirty };
wi.hwSetScenarioTab('collar');
await sleep(520);
console.log(JSON.stringify({ ignored, tab: hw.scenarioTab, put: puts.map(p => [p.scenario_tab, p.last_step]) }));""")
    assert r["ignored"] == {"tab": "pp", "dirty": False}
    assert r["tab"] == "collar" and r["put"] == [["collar", "whatif"]]


def test_set_coverage_debounce_discards_superseded_refetch_and_clamps(jsroot):
    r = _flow(jsroot, r"""
await wf.hwGoToStep('whatif', false); await sleep(50);
log.length = 0;
wi.hwSetCoverage(60); wi.hwSetCoverage(70);            // 60 is superseded within the debounce
await sleep(520);
const cov = log.filter(l => l.includes('/portfolio-hedge?coverage=')).map(l => l.match(/coverage=(\d+)/)[1]);
wi.hwSetCoverage('abc');                                 // NaN ignored
wi.hwSetCoverage(250);                                   // clamped
console.log(JSON.stringify({ cov, coverage: hw.coverage, puts: puts.map(p => p.coverage) }));""")
    assert r["cov"] == ["70"], r
    assert r["coverage"] == 100
    assert r["puts"][0] == 70


# ── restore / ensureExposure / empty state ──────────────────────────────────────────

def test_restore_to_later_step_loads_exposure_first_and_only_once(jsroot):
    r = _flow(jsroot, r"""
opts.plan = { key_id:'k', hedged_ids:['INFY'], coverage:65, scenario_tab:'ps', duration:'1y', last_step:'save', updated_at:'2026-10-03T00:00:00Z' };
await wf.loadHedgeWorkflow();
const loads1 = log.filter(l => l.includes('/user-portfolio')).length;
await wf.ensureExposure(); await wf.ensureExposure();
const loads2 = log.filter(l => l.includes('/user-portfolio')).length;
console.log(JSON.stringify({ step: hw.step, loaded: hw.exposureLoadedAt != null, hedged: hw.hedgedIds,
  holdings: hw.portfolioHoldings.length, loads1, loads2, puts: puts.length }));""")
    assert r["step"] == "save" and r["loaded"] is True
    assert r["holdings"] == 2 and r["hedged"] == ["INFY"]
    assert r["loads1"] == 1 and r["loads2"] == 1
    assert r["puts"] == 0              # restore never rewrites the plan


def test_load_with_no_portfolio_renders_empty_state_without_throwing(jsroot):
    r = _flow(jsroot, r"""
opts.portfolio = 'none';
await wf.loadHedgeWorkflow();
await wf.hwGoToStep('whatif', false); await sleep(50);
console.log(JSON.stringify({ step: hw.step, holdings: hw.portfolioHoldings.length, known: hw.knownInstruments,
  inst: hw.instrumentId, banner: els['hw-exp-hqs-banner'].innerHTML, latest: els['hw-exp-latest-view'].innerHTML,
  hedged: hw.hedgedIds, puts: puts.length }));""")
    assert r["step"] == "whatif" and r["holdings"] == 0 and r["known"] == [] and r["inst"] is None
    assert "No exposure yet" in r["banner"]
    assert "no exposure yet" in r["latest"]
    assert r["hedged"] == [] and r["puts"] == 0


# ── redirect aliases (edge 1) ────────────────────────────────────────────────────────

_EXPECTED_ALIASES = {
    "hedge": "exposure",
    "hedge-advisor": "recommendation",
    "equity-hedge": "recommendation",
    "portfolio-hedge": "exposure",
}


def test_alias_registrations_match_expected_steps_in_main_and_nav():
    main = (_FNO / "main.js").read_text(encoding="utf-8")
    nav = (_FNO / "nav.js").read_text(encoding="utf-8")
    in_main = dict(re.findall(r"_sectionLoaders\['([\w-]+)'\]\s*=\s*_hwAlias\('(\w+)'\)", main))
    assert in_main == _EXPECTED_ALIASES
    block = re.search(r"HEDGE_WORKFLOW_ALIASES\s*=\s*\{(.*?)\};", nav, re.S).group(1)
    in_nav = dict(re.findall(r"'?([\w-]+)'?\s*:\s*'(\w+)'", block))
    assert in_nav == _EXPECTED_ALIASES
    # _hwAlias must delegate to loadHedgeWorkflow(step) (single call, no separate hwGoToStep)
    assert re.search(r"function _hwAlias\(step\)\s*\{.*?loadHedgeWorkflow\(step\)", main, re.S)


@pytest.mark.parametrize("alias,step", sorted(_EXPECTED_ALIASES.items()))
def test_each_alias_lands_on_correct_step_even_with_saved_last_step(jsroot, alias, step):
    """Mirrors main.js _hwAlias(step) -> loadHedgeWorkflow(step); override beats last_step."""
    r = _flow(jsroot, f"""
opts.plan = {{ key_id:'k', hedged_ids:['INFY'], coverage:65, scenario_tab:'ps', duration:'1y', last_step:'save', updated_at:'2026-10-03T00:00:00Z' }};
await wf.loadHedgeWorkflow({json.dumps(step)});
console.log(JSON.stringify({{ step: hw.step, puts: puts.length }}));""")
    assert r == {"step": step, "puts": 0}, alias


# ── Overview autosave resets last_step (finding 7) ──────────────────────────────────

def test_overview_autosave_put_omits_last_step(jsroot):
    """Pins CURRENT behaviour (finding 7 / D4): portfolio-hedge.js saveHedgePlan sends no last_step."""
    r = _flow(jsroot, r"""
const ph = await import(base + 'fno/portfolio-hedge.js');
try { ph.phSetScenarioTab('collar'); } catch (e) { /* DOM render is stubbed out */ }
await sleep(520);
console.log(JSON.stringify({ n: puts.length, keys: puts[0] ? Object.keys(puts[0]).sort() : null, body: puts[0] }));""")
    assert r["n"] == 1, r
    assert "last_step" not in r["keys"]
    assert r["body"]["scenario_tab"] == "collar"


def test_backend_coerces_missing_last_step_to_exposure():
    """Pins CURRENT behaviour: PUT without last_step is stored as 'exposure' (finding 7)."""
    src = (_ROOT / "src" / "rita" / "api" / "experience" / "fno_hedge_plan.py").read_text(encoding="utf-8")
    assert 'last_step=body.last_step or "exposure"' in src
