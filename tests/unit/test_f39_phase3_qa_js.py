"""QA gap-fill — F39 Phase 3 frontend, driven through node (repo has no JS runner).

* hedge-calc.js edge cases (zero hedged instruments, empty holdings, null risk_score,
  all-zero weights).
* A flow harness (stubbed browser globals + routed fetch) that loads the REAL
  dashboard/js tree to verify: autosave-vs-explicit-save ordering (Code Review
  advisory #1) and the "Kite margin only when INR and non-null" rule.
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
    """Copy dashboard/js so it loads as ES modules without touching the repo."""
    dst = tmp_path_factory.mktemp("js")
    shutil.copytree(_JS, dst / "js")
    (dst / "js" / "package.json").write_text('{"type":"module"}', encoding="utf-8")
    return dst / "js"


# ── hedge-calc edge cases ──────────────────────────────────────────────────────────

def _calc(jsroot: Path, body: str) -> object:
    uri = (jsroot / "fno" / "hedge-calc.js").as_uri()
    return _node(jsroot, f"import * as calc from {json.dumps(uri)};\n{body}")


def test_zero_hedged_instruments_gives_empty_rows_and_default_aggregates(jsroot):
    r = _calc(jsroot, """
const h=[{instrument_id:'TCS',allocation_pct:50},{instrument_id:'INFY',allocation_pct:50}];
const rows=calc.buildRows(h,{},null,new Set(),50);
console.log(JSON.stringify({rows, agg:calc.aggregates(rows,null)}));""")
    assert r["rows"] == []
    assert r["agg"] == {"totalCost": 0, "avgStrike": 0, "maxDdHedged": 0, "maxDdUnhedged": -22}


def test_empty_and_null_holdings(jsroot):
    r = _calc(jsroot, """
console.log(JSON.stringify({a:calc.buildRows([],{},null,new Set(['X']),50),
  b:calc.buildRows(null,null,null,new Set(['X']),50),
  c:calc.buildRows(undefined,undefined,{holdings:null},new Set(),0)}));""")
    assert r == {"a": [], "b": [], "c": []}


def test_hedged_set_with_ids_not_in_portfolio_is_ignored(jsroot):
    r = _calc(jsroot, """
const h=[{instrument_id:'TCS',allocation_pct:100}];
console.log(JSON.stringify(calc.buildRows(h,{},null,new Set(['GHOST']),50)));""")
    assert r == []


def test_null_risk_score_from_api_falls_back_to_est_risk(jsroot):
    r = _calc(jsroot, """
const h=[{instrument_id:'TCS',allocation_pct:30}];
const inst={TCS:{daily_return_pct:-1.5,region:'India'}};
const api={holdings:[{instrument_id:'TCS',return_1y_pct:null,risk_score:null,hedge_type:'protective_put',
  strike_pct:-7,strike_label:'-7% OTM',cost_pct:1.2,protected_pct:60}]};
const rows=calc.buildRows(h,inst,api,new Set(['TCS']),50);
console.log(JSON.stringify(rows[0]));""")
    assert r["risk"] == 4          # estRisk(1.5) -> 4
    assert r["ret"] == -1.5        # return_1y_pct null -> daily_return_pct
    assert r["label"] == "Protective put" and r["costPct"] == 1.2


def test_no_api_no_instrument_data_uses_client_params(jsroot):
    r = _calc(jsroot, """
const h=[{instrument_id:'UNKNOWN',allocation_pct:10}];
const rows=calc.buildRows(h,{},null,new Set(['UNKNOWN']),50);
console.log(JSON.stringify(rows[0]));""")
    assert r["region"] == "Other" and r["risk"] == 1 and r["type"] == "nifty_proxy"


def test_est_risk_null_undefined_and_boundaries(jsroot):
    r = _calc(jsroot, """
console.log(JSON.stringify([null,undefined,0,0.3,0.7,1.2,2.0,-2.0,-0.29].map(calc.estRisk)));""")
    assert r == [1, 1, 1, 2, 3, 4, 5, 5, 1]


def test_all_zero_weights_aggregates_and_flat_payoff(jsroot):
    r = _calc(jsroot, """
const rows=[{costPct:2,strikePct:-8,weight:0}];
const a=calc.aggregates(rows,null);
const hedged=calc.PAYOFF_MOVES.map(m=>calc.hedgedPL(m,'pp',a.avgStrike,a.totalCost));
console.log(JSON.stringify({a,hedged:hedged.slice(0,3),unhedged:calc.PAYOFF_MOVES.slice(0,3)}));""")
    assert r["a"]["totalCost"] == 0 and r["a"]["avgStrike"] == 0
    assert r["hedged"] == [0, 0, 0]          # floor at avgStrike=0 -> no loss shown
    assert r["a"]["maxDdUnhedged"] == -22


def test_aggregates_uses_api_unhedged_dd_and_clamps_hedged_dd(jsroot):
    r = _calc(jsroot, """
const rows=[{costPct:50,strikePct:-30,weight:100}];
console.log(JSON.stringify(calc.aggregates(rows,{aggregate:{max_dd_unhedged_pct:-31}})));""")
    assert r["maxDdUnhedged"] == -31 and r["maxDdHedged"] == -25


@pytest.mark.parametrize("tab", ["pp", "ps", "collar", "unknown"])
def test_hedged_pl_zero_cost_zero_strike_is_finite(jsroot, tab):
    r = _calc(jsroot, f"""
console.log(JSON.stringify(calc.PAYOFF_MOVES.map(m=>calc.hedgedPL(m,'{tab}',0,0))));""")
    assert all(isinstance(v, (int, float)) for v in r) and len(r) == 41


def test_compute_n_shares_null_and_zero_inputs(jsroot):
    r = _calc(jsroot, """
console.log(JSON.stringify([
 calc.computeNShares(null,null,null),
 calc.computeNShares({shares:0,allocation_pct:10},{close:100},1000),
 calc.computeNShares({shares:null,allocation_pct:10},{close:0},1000),
 calc.computeNShares({shares:null,allocation_pct:0.01},{close:1e9},1000),
 calc.computeNShares({shares:7},{},null)]));""")
    assert r == [10, 1, 10, 1, 7]


def test_estimate_margin_null_and_missing_legs(jsroot):
    r = _calc(jsroot, """
console.log(JSON.stringify([
 calc.estimateEquityHedgeMargin(null,'put_buy'),
 calc.estimateEquityHedgeMargin({},'call_sell'),
 calc.estimateEquityHedgeMargin({hedge_scenarios:{}},'call_sell'),
 calc.estimateEquityHedgeMargin({hedge_scenarios:{}},'put_buy'),
 calc.estimateEquityHedgeMargin({hedge_scenarios:{strong_bearish:{total_premium_eur:-120}}},'put_buy'),
 calc.estimateEquityHedgeMargin({hedge_scenarios:{mild_bearish:{max_value_eur:1000}}},'call_sell')]));""")
    assert r == [None, None, None, None, 120, 200]


# ── Flow harness ──────────────────────────────────────────────────────────────────

_PRELUDE = r"""
import { pathToFileURL } from 'node:url';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const store = {};
globalThis.window = globalThis;
globalThis.sessionStorage = { getItem:k=>store[k]??null, setItem:(k,v)=>{store[k]=String(v)}, removeItem:k=>{delete store[k]} };
globalThis.location = { hostname:'localhost', href:'http://localhost/' };
globalThis.document = { getElementById:()=>null, querySelector:()=>null, querySelectorAll:()=>[], addEventListener(){} };
globalThis.Chart = class { constructor(){} destroy(){} update(){} static register(){} };
globalThis.Chart.defaults = { font: {} };
const puts = [];            // {body, resolve, sent}
const server = { last_step: null, writes: [] };
let HOLD_PUTS = false;
const opts = { currency: 'INR', kiteMargin: { required: 5000, span: 3000, exposure: 2000 }, kiteAvailable: true };
const log = [];
function jr(body, status = 200) {
  return { ok: status < 400, status, statusText: 'x', json: async () => body };
}
globalThis.fetch = async (url, o = {}) => {
  const method = (o.method || 'GET').toUpperCase();
  log.push(method + ' ' + url);
  if (url.includes('/user-portfolio')) return jr({ total_value_eur: 100000, name: 'p',
    holdings: [{ instrument_id: 'RELIANCE', allocation_pct: 60, shares: 10, cash_eur: 0 }] });
  if (url.includes('/geography-overview')) return jr({ regions: [{ region: 'India',
    instruments: [{ id: 'RELIANCE', close: 2500, daily_return_pct: 1.5, return_1y_pct: 12, risk_score: 4 }] }] });
  if (url.includes('/portfolio-analytics')) return jr({ positions: [], greeks: [], net_greeks: {}, hedge_quality: { positions: [] } });
  if (url.includes('/portfolio-hedge')) return jr(null, 404);
  if (url.includes('/equity-hedge-scenarios')) return jr({
    portfolio: { currency: opts.currency, n_shares: 10, lot_size: 250, n_contracts: 0, start_price: 1, end_price: 2, return_pct: 1, vol_30d_pct: 20 },
    hedge_scenarios: { data_source: 'x',
      mild_bearish: { strike_label: '2600', total_premium_eur: 10, max_value_eur: 1000, breakeven_price: 1 },
      strong_bearish: { strike_label: '2400', total_premium_eur: -321, floor_value_eur: 1, breakeven_price: 1 },
      payoff_curves: { price_range: [1,2], unhedged: [1,2], covered_call: [1,2], protective_put: [1,2] } } });
  if (url.includes('/kite-live')) return jr({ instrument_id: 'RELIANCE', available: opts.kiteAvailable,
    source: opts.kiteAvailable ? 'kite' : 'fallback', lot_size: 250, quote: null, margin: opts.kiteMargin, fetched_at: null });
  if (url.includes('/hedge-history')) return jr([]);
  if (url.includes('/hedge-reasoning')) return jr(null, 404);
  if (url.includes('/hedge-plan')) {
    if (method === 'PUT') {
      const body = JSON.parse(o.body);
      return await new Promise((resolve) => {
        const rec = { body, sent: log.length, resolve: () => {
          server.last_step = body.last_step; server.writes.push(body.last_step);
          resolve(jr({ key_id: 'k', hedged_ids: body.hedged_ids, coverage: body.coverage,
            scenario_tab: body.scenario_tab, duration: '1y', last_step: body.last_step,
            updated_at: new Date().toISOString() }));
        } };
        puts.push(rec);
        if (!HOLD_PUTS) rec.resolve();
      });
    }
    return jr(null);
  }
  return jr(null, 404);
};
const base = pathToFileURL(process.cwd() + '/').href;
const wf = await import(base + 'fno/hedge-workflow.js');
const save = await import(base + 'fno/hedge-workflow-save.js');
const { state } = await import(base + 'fno/state.js');
const hw = state.hedgeWorkflow;
"""


def _flow(jsroot: Path, body: str) -> object:
    return _node(jsroot, _PRELUDE + "\n" + body)


@pytest.mark.xfail(
    strict=True,
    reason="Code Review advisory #1 CONFIRMED: hwSave() sends its PUT while an autosave PUT is in "
    "flight (no await/cancel), so the autosave (last_step='whatif') can land last; UI shows Saved, "
    "hw.savedPlan.last_step=='whatif', DB 'whatif'. Source intentionally not fixed by QA. "
    "Remove xfail once hwSave awaits/cancels the in-flight autosave.",
)
def test_autosave_in_flight_then_explicit_save_ends_with_last_step_save(jsroot):
    """Code Review advisory #1. An autosave PUT (last_step 'whatif') still in flight when
    the user clicks Save must not be able to land AFTER the explicit 'save' write."""
    r = _flow(jsroot, r"""
await wf.hwGoToStep('save', false);
HOLD_PUTS = true;
save.hwMarkDirty();                 // queue autosave (400ms debounce)
await sleep(480);                   // autosave PUT is now in flight, unresolved
const inflightAtSaveClick = puts.length;
const p = save.hwSave();            // explicit Save while autosave in flight
await sleep(50);
const sentWhileInflight = puts.length;
// Worst-case network ordering: newest request is processed first, oldest last.
let guard = 0;
while (guard++ < 10) {
  const pending = puts.filter((x) => !x.done);
  if (!pending.length) { await sleep(30); if (!puts.filter((x) => !x.done).length) break; continue; }
  const rec = pending[pending.length - 1];
  rec.done = true; rec.resolve();
  await sleep(30);
}
await p;
console.log(JSON.stringify({ inflightAtSaveClick, sentWhileInflight, writes: server.writes,
  final: server.last_step, uiSavedPlan: hw.savedPlan && hw.savedPlan.last_step,
  historyPlan: hw.history.plan && hw.history.plan.last_step, status: hw.saveStatus }));
process.exit(0);""")
    assert r["inflightAtSaveClick"] == 1, r
    assert r["final"] == "save", (
        "Autosave PUT (last_step='whatif') landed after the explicit save PUT -> DB holds "
        f"'whatif' while UI says Saved. Detail: {r}"
    )
    assert r["uiSavedPlan"] == "save"


def test_explicit_save_without_inflight_autosave_writes_save_once(jsroot):
    r = _flow(jsroot, r"""
await wf.hwGoToStep('save', false);
await save.hwSave();
console.log(JSON.stringify({ writes: server.writes, status: hw.saveStatus, hist: hw.history.plan.last_step }));""")
    assert r == {"writes": ["save"], "status": "saved", "hist": "save"}


def test_hwsave_cancels_pending_debounce_and_double_click_sends_one_put(jsroot):
    r = _flow(jsroot, r"""
await wf.hwGoToStep('save', false);
HOLD_PUTS = true;
save.hwMarkDirty();                  // debounce pending, not yet fired
const a = save.hwSave(); const b = save.hwSave();   // double click
await sleep(500);                    // debounce window passes
const count = puts.length;
puts.forEach((x) => x.resolve());
await Promise.all([a, b]); await sleep(50);
console.log(JSON.stringify({ count, writes: server.writes }));
process.exit(0);""")
    assert r["count"] == 1 and r["writes"] == ["save"]


def test_autosave_on_save_step_never_writes_save(jsroot):
    r = _flow(jsroot, r"""
await wf.hwGoToStep('save', false);
save.hwMarkDirty(); await sleep(500);
console.log(JSON.stringify(server.writes));""")
    assert r == ["whatif"]


def test_save_failure_sets_error_and_keeps_saved_plan_unchanged(jsroot):
    r = _flow(jsroot, r"""
await wf.hwGoToStep('save', false);
const before = hw.savedPlan;
const orig = globalThis.fetch;
globalThis.fetch = async (u, o = {}) => (o.method === 'PUT' ? jr({ detail: 'No portfolio key found' }, 404) : orig(u, o));
await save.hwSave();
console.log(JSON.stringify({ status: hw.saveStatus, err: hw.saveError, same: hw.savedPlan === before }));""")
    assert r == {"status": "error", "err": "No portfolio key found", "same": True}


@pytest.mark.parametrize(
    "currency,margin,available,expected_source",
    [
        ("INR", {"required": 5000, "span": 1, "exposure": 1}, True, "kite"),
        ("INR", {"required": None, "span": 1, "exposure": 1}, True, "estimated"),   # null required
        ("INR", None, True, "estimated"),                                           # margin null
        ("EUR", {"required": 5000, "span": 1, "exposure": 1}, True, "estimated"),   # currency mismatch
        ("INR", {"required": 5000, "span": 1, "exposure": 1}, False, "estimated"),  # kite unavailable
    ],
)
def test_margin_impact_uses_kite_only_when_inr_and_non_null(jsroot, currency, margin, available, expected_source):
    r = _flow(jsroot, f"""
opts.currency = {json.dumps(currency)}; opts.kiteMargin = {json.dumps(margin)}; opts.kiteAvailable = {json.dumps(available)};
await wf.hwGoToStep('whatif', false);
await sleep(50);
console.log(JSON.stringify(hw.marginImpact));""")
    assert r is not None and r["source"] == expected_source and r["currency"] == currency
    assert r["amount"] == (5000 if expected_source == "kite" else 321)   # BSM put_buy = |premium|


def test_whatif_with_no_holdings_does_not_throw_and_no_margin(jsroot):
    r = _flow(jsroot, r"""
const orig = globalThis.fetch;
globalThis.fetch = async (u, o = {}) => u.includes('/user-portfolio') ? jr({ total_value_eur: null, holdings: [] }) : orig(u, o);
await wf.hwGoToStep('whatif', false);
console.log(JSON.stringify({ margin: hw.marginImpact, n: hw.portfolioHoldings.length }));""")
    assert r == {"margin": None, "n": 0}


def test_alias_deep_link_wins_over_saved_last_step(jsroot):
    r = _flow(jsroot, r"""
const orig = globalThis.fetch;
globalThis.fetch = async (u, o = {}) => (u.includes('/hedge-plan') && (o.method||'GET')==='GET')
  ? jr({ key_id:'k', hedged_ids:['RELIANCE'], coverage:70, scenario_tab:'ps', duration:'1y', last_step:'save', updated_at:'2026-10-03T00:00:00Z' })
  : orig(u, o);
await wf.loadHedgeWorkflow('recommendation');
console.log(JSON.stringify({ step: hw.step, cov: hw.coverage, tab: hw.scenarioTab, writes: server.writes }));""")
    assert r["step"] == "recommendation" and r["cov"] == 70 and r["tab"] == "ps"
    assert r["writes"] == []                      # restore never rewrites last_step


def test_null_plan_get_defaults_to_exposure_and_unknown_last_step_is_exposure(jsroot):
    r = _flow(jsroot, r"""
await wf.loadHedgeWorkflow();
const a = hw.step;
const orig = globalThis.fetch;
globalThis.fetch = async (u, o = {}) => (u.includes('/hedge-plan') && (o.method||'GET')==='GET')
  ? jr({ key_id:'k', hedged_ids:[], coverage:10, scenario_tab:null, duration:'1y', last_step:'bogus', updated_at:'2026-10-03T00:00:00Z' })
  : orig(u, o);
await wf.loadHedgeWorkflow();
console.log(JSON.stringify({ a, b: hw.step, tab: hw.scenarioTab, hedged: hw.hedgedIds }));""")
    assert r == {"a": "exposure", "b": "exposure", "tab": "pp", "hedged": []}
