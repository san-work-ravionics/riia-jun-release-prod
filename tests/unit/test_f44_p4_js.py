"""F44 P4b — Jarvis page JS (``dashboard/js/jarvis/*.js``), node harness (P2 pattern,
``test_f44_p2_review_fixes.py``).

- stale token: A2, A3, A4, A5, A6 go through ``api()`` — a 401 → ``ensureDevToken(true)`` → exactly
  one retry (project.md §9; design rev 1 A13)
- escaping: hostile ``instrument_id`` / text (``<img onerror>``, quotes) renders escaped in every
  card kind, the grid (``data-inst``), chat bubbles, plan, levels and rationale; delegated grid
  click passes the raw id to ``api()`` URL-encoded
- grep gates: no ``fetch(`` / ``apiFetch(`` / ``onclick=`` in ``jarvis/*.js``; FC-API-SIG; FC-MERGE
- FC-IMP: every named import resolves to an export (static parse + a real node import of main.js)
- FC-004: every field the JS reads is a field of ``tests/unit/fixtures/f44_p4_contract.json`` —
  per card kind, A4 (plan), A5 (portfolio), A6 (instrument) and the A2/A3/A4 reads in main.js
- jarvis.html: the login gate is the stub's, verbatim; every §5 DOM id exists; main.js?v=3

JS runs under node (skipped when node is missing). No network, no browser.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1].parent
_JS = _ROOT / "dashboard" / "js"
_JV = _JS / "jarvis"
_HTML = _ROOT / "dashboard" / "jarvis.html"
_FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "f44_p4_contract.json").read_text())
_MODULES = sorted(p.name for p in _JV.glob("*.js"))
_needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

HOSTILE = "<img src=x onerror=\"alert(1)\">'\""


def _node(script: str):
    r = subprocess.run(["node", "--input-type=module", "-e", script], cwd=_JS,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-3000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


# Browser globals the modules touch at import time (shared/charts.js, rita/chart-modal.js).
_PRELUDE = """
import { pathToFileURL } from 'node:url';
const base = pathToFileURL(process.cwd() + '/').href;
const store = { auth_token: 'stale' };
globalThis.window = globalThis;
globalThis.sessionStorage = { getItem:k=>store[k]??null, setItem:(k,v)=>{store[k]=String(v)}, removeItem:k=>{delete store[k]} };
globalThis.location = { hostname:'localhost', href:'http://localhost/dashboard/jarvis.html', hash:'' };
const _listeners = {};
const _el = id => ({ id, listeners: {}, addEventListener(ev, fn) { (_listeners[id] ||= []).push(fn); },
                     querySelectorAll: () => [], classList: { toggle(){} }, dataset: {} });
globalThis.document = { addEventListener(){}, getElementById: _el, querySelectorAll: () => [] };
globalThis.Chart = function(){}; Chart.defaults = { font: {} }; Chart.register = () => {};
const jr = (body, status = 200) => ({ ok: status < 400, status, statusText: 'x', json: async () => body });
"""


def _src(name: str) -> str:
    return (_JV / name).read_text()


def test_all_design_modules_present():
    assert set(_MODULES) == {"main.js", "copy.js", "esc.js", "format.js", "chat.js", "plan.js",
                             "portfolio.js", "instrument.js", "concepts.js", "regions.js"}


# ── stale token (A2, A3, A4, A5, A6) ───────────────────────────────────────────

_CALLS = {
    "A2": ("chat.js", "openSession('europe')", "POST /api/v1/workflow/jarvis/session"),
    "A3": ("chat.js", "sendMessage('s-1', 'use my goal', 'europe')", "POST /api/v1/workflow/jarvis/message"),
    "A4": ("chat.js", "loadState('india')", "GET /api/v1/experience/jarvis/state?location=india"),
    "A5": ("portfolio.js", "loadPortfolio('us')", "GET /api/v1/experience/jarvis/portfolio?location=us"),
    "A6": ("instrument.js", "loadInstrument('india', 'NIFTY')",
           "GET /api/v1/experience/jarvis/instrument?location=india&instrument=NIFTY"),
    "G": ("regions.js", "loadGeography()", "GET /api/v1/experience/rita/geography-overview"),
}


@_needs_node
@pytest.mark.parametrize("ep", sorted(_CALLS))
def test_stale_token_reminted_once_then_retried(ep):
    mod, call, line = _CALLS[ep]
    r = _node(_PRELUDE + f"""
const log = [];
globalThis.fetch = async (url, o = {{}}) => {{
  const auth = (o.headers || {{}}).Authorization || '';
  log.push(`${{o.method || 'GET'}} ${{url}} ${{auth}}`.trim());
  if (url === '/auth/token') return jr({{ access_token: 'fresh' }});
  if (auth !== 'Bearer fresh') return jr({{ detail: 'expired' }}, 401);
  return jr({{ ok: true, body: o.body ? JSON.parse(o.body) : null }});
}};
const m = await import(base + 'jarvis/{mod}?v=3');
const res = await m.{call};
console.log(JSON.stringify({{ res, log, token: store.auth_token }}));""")
    assert r["log"] == [f"{line} Bearer stale", "POST /auth/token", f"{line} Bearer fresh"]
    assert r["token"] == "fresh" and r["res"]["ok"] is True


@_needs_node
def test_stale_token_retries_exactly_once_then_fails():
    r = _node(_PRELUDE + """
const log = [];
globalThis.fetch = async (url, o = {}) => {
  log.push(`${o.method || 'GET'} ${url}`);
  if (url === '/auth/token') return jr({ access_token: 'also-rejected' });
  return jr({ detail: 'expired' }, 401);
};
const m = await import(base + 'jarvis/chat.js?v=3');
let err = null;
try { await m.sendMessage('s-1', 'hi', 'europe'); } catch (e) { err = e.message; }
console.log(JSON.stringify({ log, err }));""")
    assert r["log"] == ["POST /api/v1/workflow/jarvis/message", "POST /auth/token",
                        "POST /api/v1/workflow/jarvis/message"]
    assert r["err"]


@_needs_node
def test_a3_posts_positional_body():
    r = _node(_PRELUDE + """
store.auth_token = 'fresh';
let seen = null;
globalThis.fetch = async (url, o = {}) => { seen = { url, method: o.method, body: JSON.parse(o.body) }; return jr({}); };
const m = await import(base + 'jarvis/chat.js?v=3');
await m.sendMessage('s-9', 'track it', 'us');
console.log(JSON.stringify(seen));""")
    assert r == {"url": "/api/v1/workflow/jarvis/message", "method": "POST",
                 "body": {"session_id": "s-9", "text": "track it", "location": "us"}}


# ── escaping ───────────────────────────────────────────────────────────────────

def _assert_escaped(html: str):
    assert "<img" not in html, html[:400]
    assert "onerror=\"" not in html
    assert "&lt;img" in html


@_needs_node
def test_hostile_strings_render_escaped_everywhere():
    fx = json.dumps(_FIXTURE)
    r = _node(_PRELUDE + f"""
const FX = {fx};
const H = {json.dumps(HOSTILE)};
const chat = await import(base + 'jarvis/chat.js?v=3');
const plan = await import(base + 'jarvis/plan.js?v=3');
const pf = await import(base + 'jarvis/portfolio.js?v=3');
const inst = await import(base + 'jarvis/instrument.js?v=3');
const hostile = o => JSON.parse(JSON.stringify(o), (k, v) =>
  (['instrument_id','text','label','basis','note','name','setup','reason','live_replay_note','currency'].includes(k)
   && typeof v === 'string') ? H : v);
const out = {{}};
for (const [kind, card] of Object.entries(FX.cards)) out['card_' + kind] = chat.cardHtml(hostile(card));
out.bubble_user = chat.bubbleHtml('user', H);
out.bubble_assistant = chat.bubbleHtml('assistant', H, [hostile(FX.cards.selection)]);
out.chips = chat.chipsHtml([{{ label: H, text: H }}]);
const st = hostile(FX.A4_state);
out.plan = plan.goalHtml(st.journey) + plan.selectionHtml(st.journey, st.live_holdings) + plan.excludedHtml(
  {{ selection: {{ excluded: [{{ instrument_id: H, reason: H }}] }} }}) + plan.proposalHtml({{ ...st.journey, state: 'reselect_proposed' }});
const a5 = hostile(FX.A5_portfolio);
out.grid = pf.gridRowsHtml(a5.instruments, a5.currency, H);
out.engines = pf.engineTableHtml(a5.engines, 'europe');
const rg = await import(base + 'jarvis/regions.js?v=3');
const geo = JSON.parse(JSON.stringify(FX.G_geography), (k, v) =>
  (['id', 'sector', 'signal', 'currency', 'name'].includes(k) && typeof v === 'string') ? H : v);
const a5h = hostile(FX.A5_portfolio);
a5h.instruments[0].instrument_id = H;
out.loc_inst = rg.locInstrumentsHtml(rg.groupByLocation(geo).europe, a5h, 'europe');
out.loc_pf = pf.locPortfolioHtml(hostile(FX.A5_portfolio), 'europe');
const pick = hostile(FX.A5_portfolio); pick.perf.money = null;
out.loc_pick = pf.locPortfolioHtml(pick, 'europe');
out.geo_table = rg.geoTableHtml(rg.allInstruments(geo), {{ col: 'ret', asc: false }}, {{ europe: a5h }});
const a6 = hostile(FX.A6_instrument);
for (const e of a6.engines) {{
  out['levels_' + e.engine] = inst.levelsHtml(e, {{}});
  out['rationale_' + e.engine] = inst.rationaleHtml(e);
  out['toggle_' + e.engine] = inst.enginesToggleHtml(a6, e.engine);
}}
console.log(JSON.stringify(out));""")
    for key, html in r.items():
        assert "<img" not in html, key
    for key in ("card_goal", "card_selection", "card_closest", "card_why", "card_tracking", "card_proposal",
                "card_what_if", "card_excluded", "bubble_user", "bubble_assistant", "chips", "plan", "grid",
                "engines", "levels_rita", "rationale_rita", "toggle_rita", "loc_inst", "loc_pf", "loc_pick",
                "geo_table"):
        _assert_escaped(r[key])
    # the id is an attribute value: quotes escaped, so it can't break out of data-inst
    assert 'data-inst="&lt;img src=x onerror=&quot;alert(1)&quot;&gt;&#39;&quot;"' in r["grid"]
    assert "onclick" not in "".join(r.values())


@_needs_node
def test_unknown_card_kind_renders_nothing():
    r = _node(_PRELUDE + """
const chat = await import(base + 'jarvis/chat.js?v=3');
console.log(JSON.stringify([chat.cardHtml({ kind: 'nope', data: { x: 1 } }), chat.cardHtml({ kind: '<img>', data: {} }),
                            chat.cardHtml(null), chat.CARD_KINDS]));""")
    assert r[:3] == ["", "", ""]
    assert sorted(r[3]) == sorted(_FIXTURE["cards"])


@_needs_node
def test_delegated_grid_click_passes_raw_id_and_url_encodes_it():
    r = _node(_PRELUDE + f"""
store.auth_token = 'fresh';
const urls = [];
globalThis.fetch = async (url) => {{ urls.push(url); return jr({{ instrument_id: 'x', engines: [] }}); }};
const pf = await import(base + 'jarvis/portfolio.js?v=3');
const inst = await import(base + 'jarvis/instrument.js?v=3');
let picked = null;
pf.initGrid(id => {{ picked = id; }});
const H = {json.dumps(HOSTILE)};
const tr = {{ dataset: {{ inst: H }} }};
_listeners['jv-grid-body'][0]({{ target: {{ closest: sel => (sel === 'tr[data-inst]' ? tr : null) }} }});
await inst.loadInstrument('europe', picked);
console.log(JSON.stringify({{ picked, urls, n: _listeners['jv-grid-body'].length }}));""")
    assert r["picked"] == HOSTILE and r["n"] == 1
    assert r["urls"] == ["/api/v1/experience/jarvis/instrument?location=europe&instrument="
                         "%3Cimg%20src%3Dx%20onerror%3D%22alert(1)%22%3E'%22"]


@_needs_node
def test_esc_covers_the_five_characters():
    r = _node(_PRELUDE + """
const { esc } = await import(base + 'jarvis/esc.js?v=3');
console.log(JSON.stringify([esc(`&<>"'`), esc(null), esc(undefined), esc(0)]));""")
    assert r == ["&amp;&lt;&gt;&quot;&#39;", "", "", "0"]


# ── grep gates ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", _MODULES)
def test_no_raw_fetch_apifetch_or_onclick(name):
    s = _src(name)
    assert not re.search(r"\bfetch\(", s), name
    assert "apiFetch" not in s, name
    assert "onclick=" not in s.lower(), name
    assert not re.search(r"\.onclick\s*=", s), name


@pytest.mark.parametrize("name", _MODULES)
def test_fc_api_sig_and_no_merge_markers(name):
    s = _src(name)
    # the object-options form api(path, {method, body}) silently breaks POSTs
    assert not re.search(r"\bapi\(\s*(['`])[^'`]*\1\s*,\s*\{", s), f"{name}: use api(path, 'POST', body)"
    for method in re.findall(r"\bapi\(\s*(['`])[^'`]*\1\s*,\s*'([A-Z]+)'", s):
        assert method[1] in ("POST", "PUT", "DELETE", "PATCH"), method
    assert not re.search(r"^(<<<<<<<|=======|>>>>>>>)", s, re.M), name


def test_only_window_binding_is_close_chart_modal():
    bindings = set()
    for name in _MODULES:
        bindings |= set(re.findall(r"window\.(\w+)\s*=", _src(name)))
    assert bindings == {"closeChartModal"}


# ── FC-IMP ─────────────────────────────────────────────────────────────────────

def _exports(path: Path) -> set[str]:
    s = path.read_text()
    names = set(re.findall(r"export\s+(?:async\s+)?(?:function|const|let|class)\s+(\w+)", s))
    for group in re.findall(r"export\s*\{([^}]*)\}", s):
        names |= {g.split(" as ")[-1].strip() for g in group.split(",") if g.strip()}
    return names


@pytest.mark.parametrize("name", _MODULES)
def test_fc_imp_named_imports_resolve(name):
    s = _src(name)
    for names, spec in re.findall(r"import\s*\{([^}]*)\}\s*from\s*'([^']+)'", s):
        target = (_JV / spec.split("?")[0]).resolve()
        assert target.exists(), f"{name}: {spec}"
        exported = _exports(target)
        for n in (x.strip() for x in names.split(",")):
            if n:
                assert n in exported, f"FC-IMP: {n} not exported by {spec} (imported in {name})"


def test_intra_jarvis_imports_share_one_cache_bust_query():
    """Every ./x.js import carries the same ?v= (a module imported under two URLs would load twice)."""
    qs = set()
    for name in _MODULES:
        for spec in re.findall(r"from\s*'(\./[^']+)'", _src(name)):
            assert "?v=" in spec, f"{name}: {spec}"
            qs.add(spec.split("?")[1])
    assert qs == {"v=3"}


@_needs_node
def test_main_module_graph_loads():
    r = _node(_PRELUDE + """
await import(base + 'jarvis/main.js?v=3');
console.log(JSON.stringify({ ok: typeof window.closeChartModal === 'function' }));""")
    assert r == {"ok": True}


# ── FC-004: fields read ⊆ contract fixture ─────────────────────────────────────

def _paths(o, p: str = "") -> set[str]:
    out: set[str] = set()
    if isinstance(o, dict):
        for k, v in o.items():
            q = f"{p}.{k}" if p else k
            out.add(q)
            out |= _paths(v, q)
    elif isinstance(o, list):
        for v in o:
            out |= _paths(v, p + "[]")
    return out


_RECORDER = """
const seen = {};
const SKIP = new Set([...Object.getOwnPropertyNames(Array.prototype), ...Object.getOwnPropertyNames(Object.prototype),
                      'toJSON', 'then']);
function rec(group, obj, path = '') {
  if (obj === null || typeof obj !== 'object') return obj;
  return new Proxy(obj, { get(t, k, r) {
    if (typeof k === 'symbol') return Reflect.get(t, k, r);
    if (Array.isArray(t)) {
      if (/^\\d+$/.test(k)) return rec(group, t[k], path + '[]');
      return Reflect.get(t, k, r);
    }
    if (SKIP.has(k) && !Object.prototype.hasOwnProperty.call(t, k)) return Reflect.get(t, k, r);
    const q = path ? `${path}.${k}` : k;
    (seen[group] ||= new Set()).add(q);
    return rec(group, t[k], q);
  } });
}
"""


@pytest.fixture(scope="module")
def js_reads():
    if shutil.which("node") is None:
        pytest.skip("node not installed")
    fx = json.dumps(_FIXTURE)
    return _node(_PRELUDE + _RECORDER + f"""
const FX = {fx};
const clone = o => JSON.parse(JSON.stringify(o));
const chat = await import(base + 'jarvis/chat.js?v=3');
const plan = await import(base + 'jarvis/plan.js?v=3');
const pf = await import(base + 'jarvis/portfolio.js?v=3');
const inst = await import(base + 'jarvis/instrument.js?v=3');
const cx = await import(base + 'jarvis/concepts.js?v=3');
for (const [kind, card] of Object.entries(FX.cards)) chat.cardHtml({{ kind, data: rec('card.' + kind, clone(card.data)) }});
for (const state of ['tracking', 'selected', 'cant_reach', 'reselect_proposed', 'back_to_plan']) {{
  const st = clone(FX.A4_state);
  st.journey.state = state;
  st.journey.back_to_plan_reason = state === 'back_to_plan' ? 'cap' : null;
  const s = rec('A4', st);
  const j = s.journey;
  plan.goalHtml(j); plan.selectionHtml(j, s.live_holdings); plan.methodHtml(j); plan.excludedHtml(j);
  plan.trackingHtml(j, s.live_holdings); plan.proposalHtml(j);
  if (s.plan_stale !== undefined && s.goal) void s.goal.plan_updated_at;
}}
for (const src of ['saved', 'mixed', 'model_sleeves', 'model_sleeves_preview', 'none']) {{
  const a5 = clone(FX.A5_portfolio); a5.pnl_source = src;
  const p = rec('A5', a5);
  pf.sourceText(p, 'europe'); pf.kpisHtml(p); pf.targetKpisHtml(p); pf.requiredText(p, 'europe');
  pf.gridRowsHtml(p.instruments, p.currency, 'E1'); pf.engineTableHtml(p.engines, 'europe');
  pf.locKpisHtml(p); pf.locPortfolioHtml(p, 'europe');
  for (const variant of ['legacy', 'no_money', 'no_perf']) {{
    const v = clone(FX.A5_portfolio); v.pnl_source = src;
    if (variant === 'legacy') v.perf.money.legacy_note = true;
    if (variant === 'no_money') v.perf.money = null;
    if (variant === 'no_perf') v.perf = null;
    const q = rec('A5', v);
    pf.locKpisHtml(q); pf.locPortfolioHtml(q, 'india');
  }}
}}
{{
  const rg = await import(base + 'jarvis/regions.js?v=3');
  const g = rec('G', clone(FX.G_geography));
  const pfs = {{ europe: rec('A5', clone(FX.A5_portfolio)) }};
  const cols = rg.groupByLocation(g);
  for (const l of rg.LOCS) {{ rg.regionAvg(cols[l]); rg.locHeaderMeta(cols[l]); rg.locAvgHtml(cols[l]); rg.locInstrumentsHtml(cols[l], pfs[l], l); }}
  const all = rg.allInstruments(g);
  for (const col of rg.GEO_COLS) rg.geoTableHtml(all, {{ col, asc: true }}, pfs);
  rg.geoMapData(g, pfs);
}}
for (const key of ['A6_instrument', 'A6_instrument_excluded']) {{
  for (const status of [null, 'ok', 'levels_only', 'excluded', 'no_recorded_window', 'warming']) {{
    const a6 = clone(FX[key]);
    if (status) a6.engines = a6.engines.map(e => ({{ ...e, status }}));
    const d = rec('A6', a6);
    inst.pickDefaultEngine(d);
    for (const eng of ['rita', 'fno', 'asta']) inst.enginesToggleHtml(d, eng);
    for (const e of d.engines) {{
      inst.levelsHtml(e, {{ slLimit: -0.1 }}); inst.rationaleHtml(e); inst.performanceHtml(e); inst.statusText(e, 'E1');
      inst.priceDatasets(e); inst.sleeveDatasets(e);
    }}
  }}
}}
for (const state of ['tracking', 'selected', 'reselect_proposed']) {{
  const st = clone(FX.A4_state); st.journey.state = state;
  const data = {{ state: rec('A4', st), pf: rec('A5', clone(FX.A5_portfolio)), inst: rec('A6', clone(FX.A6_instrument)) }};
  for (const step of cx.STEPS) cx.panelHtml(step, data);
  cx.statusText(data.state, data.pf, 'europe'); cx.stepBarHtml(data.state.journey.state);
}}
console.log(JSON.stringify(Object.fromEntries(Object.entries(seen).map(([k, v]) => [k, [...v].sort()]))));""")


@pytest.mark.parametrize("kind", sorted(_FIXTURE["cards"]))
def test_fc004_card_reads_are_fixture_fields(js_reads, kind):
    reads = set(js_reads.get(f"card.{kind}", []))
    assert reads, f"no reads recorded for card {kind}"
    allowed = _paths(_FIXTURE["cards"][kind]["data"])
    assert reads <= allowed, f"{kind}: {sorted(reads - allowed)}"


@pytest.mark.parametrize("group,fixture_key", [("A4", "A4_state"), ("A5", "A5_portfolio"), ("A6", "A6_instrument"),
                                               ("G", "G_geography")])
def test_fc004_page_reads_are_fixture_fields(js_reads, group, fixture_key):
    reads = set(js_reads[group])
    allowed = _paths(_FIXTURE[fixture_key])
    if group == "A6":                                    # method is Any: one example per emitted shape
        allowed |= _paths(_FIXTURE["A6_instrument_excluded"])
    assert reads <= allowed, f"{group}: {sorted(reads - allowed)}"


def test_fc004_plan_reads_live_holdings_for_model_today():
    """Rev 2 N2: "Model today" / "Invested now" / next_reset come from A4 live_holdings."""
    s = _src("plan.js")
    for f in ("lv.model_action", "lv.invested_fraction", "lv.sl_distance", "h.next_reset"):
        assert f in s, f
    assert "plan.selection.at_selection" in s


def test_fc004_main_reads_are_fixture_fields():
    s = _src("main.js")
    reads = set(re.findall(r"\b(?:res|sess|state|r)\.[a-z_]+(?:\.[a-z_]+)*", s))
    roots = {"res": "A3_message", "sess": "A2_session", "state": "A4_state", "r": "A1_warmup"}
    for read in reads:
        root, *rest = read.split(".")
        assert ".".join(rest) in _paths(_FIXTURE[roots[root]]), read
    assert {"res.reply.text", "res.reply.cards", "res.reply.chips", "res.journey", "sess.session_id"} <= reads


# ── jarvis.html ────────────────────────────────────────────────────────────────

_DESIGN_IDS = """jv-loc-tabs jv-tab-chat jv-tab-portfolio jv-status-model sec-jv-chat jv-chat-log jv-chat-form
jv-chat-input jv-chat-send jv-chat-chips jv-chat-error sec-jv-plan jv-plan-goal jv-plan-selection jv-plan-method
jv-plan-excluded jv-plan-tracking jv-plan-proposal jv-plan-empty sec-jv-portfolio jv-pf-source jv-pf-kpis
jv-pnl-chart jv-pnl-empty jv-target-kpis jv-target-chart jv-target-required jv-grid jv-grid-body jv-grid-empty
jv-engine-table jv-engine-chart jv-engine-note sec-jv-instrument jv-inst-title jv-inst-engines jv-inst-chart
jv-sleeve-chart jv-sleeve-wrap jv-inst-levels jv-rationale jv-inst-status chart-modal chart-modal-title
chart-modal-img jv-pf-status sec-jv-locations sec-jv-universe jv-geo-map jv-geo-map-empty jv-geo-map-note
jv-geo-table-wrap jv-geo-table jv-geo-table-empty jv-pf-detail-title""".split() + [
    f"jv-loc-{k}-{loc}" for loc in ("europe", "india", "us") for k in ("col", "ccy", "meta", "avg", "pf", "inst")]


def test_html_has_every_design_id_once():
    html = _HTML.read_text()
    ids = re.findall(r'\bid="([^"]+)"', html)
    for i in _DESIGN_IDS:
        assert ids.count(i) == 1, i
    assert len(ids) == len(set(ids))


def test_html_loads_main_v3_and_chartjs():
    html = _HTML.read_text()
    assert '<script type="module" src="./js/jarvis/main.js?v=3"></script>' in html
    assert "chart.js@4.4.0/dist/chart.umd.min.js" in html


def test_html_keeps_the_stub_login_gate_verbatim():
    html = _HTML.read_text()
    gate = html[html.index("<script>"):html.index("</script>") + len("</script>")]
    assert "// Login gate (F44: Jarvis requires login)." in gate
    assert "window.location.href = '/auth/google/login';" in gate
    assert "sessionStorage.setItem('post_login_redirect', window.location.href);" in gate
    stub = subprocess.run(["git", "-C", str(_ROOT), "show", "9ddb068:dashboard/jarvis.html"],
                          capture_output=True, text=True)
    if stub.returncode == 0:                                             # history available
        s = stub.stdout
        assert gate == s[s.index("<script>"):s.index("</script>") + len("</script>")]


def test_charts_sit_in_chart_wraps_with_titles():
    html = _HTML.read_text()
    for cid in ("jv-pnl-chart", "jv-target-chart", "jv-engine-chart", "jv-inst-chart", "jv-sleeve-chart", "jv-geo-map"):
        i = html.index(f'id="{cid}"')
        wrap = html.rfind('class="chart-wrap"', 0, i)
        assert wrap != -1 and 'class="chart-title"' in html[wrap:i], cid


# ── Concepts page ──────────────────────────────────────────────────────────────

def test_html_concepts_view_ids():
    html = _HTML.read_text()
    ids = re.findall(r'\bid="([^"]+)"', html)
    for i in ("jv-tab-concepts", "jv-view-concepts", "jv-cx-steps", "jv-cx-flow", "jv-cx-status", "jv-cx-tabs", "jv-cx-panel"):
        assert ids.count(i) == 1, i


@_needs_node
def test_concepts_every_step_renders_with_and_without_data():
    fx = json.dumps(_FIXTURE)
    r = _node(_PRELUDE + f"""
const FX = {fx};
const cx = await import(base + 'jarvis/concepts.js?v=3');
const {{ COPY }} = await import(base + 'jarvis/copy.js?v=3');
const full = {{ state: FX.A4_state, pf: FX.A5_portfolio, inst: FX.A6_instrument }};
const out = {{}};
for (const s of cx.STEPS) {{
  const a = cx.panelHtml(s, full), b = cx.panelHtml(s, {{}});
  out[s] = {{ full: a.includes('concept-desc') && (a.match(/chart-wrap/g) || []).length === 2,
              empty: b.includes('cx-empty') || s === 's2' || s === 's8',
              canvas: (a.match(/<canvas id="([^"]+)"/g) || []).length,
              copy: ['tab', 'who', 'kind', 'desc', 'c1', 'c2'].every(k => COPY[`cx.${{s}}.${{k}}`]) }};
}}
const hostile = JSON.parse(JSON.stringify(FX.A4_state));
hostile.journey.selection.ladder[0].tolerance = {json.dumps(HOSTILE)};
hostile.live_holdings[0].instrument_id = {json.dumps(HOSTILE)};
out.escaped = !cx.panelHtml('s1', {{ state: hostile }}).includes('<img') && !cx.flowTableHtml().includes('<img');
console.log(JSON.stringify(out));""")
    assert r.pop("escaped") is True
    for step, v in r.items():
        assert v["full"] and v["empty"] and v["copy"], (step, v)
    assert sum(v["canvas"] for v in r.values()) >= 9


# ── P4c: portfolio page on the RITA Portfolio Builder layout ───────────────────

def test_html_portfolio_view_children_parsed():
    """Parsed, not div-counted: #jv-view-portfolio's direct children are header, the three sections and
    the two dividers in order; the columns sit in the grid; drill-down + engines are in the detail."""
    from html.parser import HTMLParser

    void = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}

    class _N:
        def __init__(self, tag, attrs, parent):
            self.tag, self.attrs, self.parent, self.children = tag, dict(attrs), parent, []

    class _P(HTMLParser):
        def __init__(self):
            super().__init__()
            self.cur = _N("root", [], None)
            self.ids: dict[str, list] = {}
            self.mismatch: list = []

        def handle_starttag(self, tag, attrs):
            n = _N(tag, attrs, self.cur)
            self.cur.children.append(n)
            if n.attrs.get("id"):
                self.ids.setdefault(n.attrs["id"], []).append(n)
            if tag not in void:
                self.cur = n

        def handle_endtag(self, tag):
            if tag in void:
                return
            if self.cur.tag != tag:
                self.mismatch.append((tag, self.cur.tag, self.getpos()))
            c = self.cur
            while c is not None and c.tag != tag:
                c = c.parent
            if c is not None:
                self.cur = c.parent

    p = _P()
    p.feed(_HTML.read_text())
    assert p.mismatch == []
    view = p.ids["jv-view-portfolio"][0]
    kids = [(c.tag, c.attrs.get("id"), c.attrs.get("class")) for c in view.children]
    assert kids == [("div", None, "page-hdr"),
                    ("div", "jv-region-breadcrumb", "jv-region-breadcrumb"),
                    ("section", "sec-jv-locations", None), ("div", None, "jv-divider"),
                    ("section", "sec-jv-universe", None), ("div", None, "jv-divider"),
                    ("section", "sec-jv-portfolio", None)]

    def inside(i, sec):
        n = p.ids[i][0]
        while n is not None:
            if n.attrs.get("id") == sec:
                return True
            n = n.parent
        return False

    for loc in ("europe", "india", "us"):
        assert p.ids[f"jv-loc-col-{loc}"][0].parent.attrs.get("class") == "jv-loc-grid"
    for i in ("jv-pf-source", "jv-pf-kpis", "jv-grid", "sec-jv-instrument", "jv-engine-table", "jv-engine-chart"):
        assert inside(i, "sec-jv-portfolio"), i
    for i in ("jv-geo-map", "jv-geo-table"):
        assert inside(i, "sec-jv-universe"), i
    assert "jv-loc-tabs" in p.ids                                   # D3: still the current-location control


def test_regions_no_fx_and_no_cross_currency_sum():
    """D1/D5: the page never converts — no shared/fx.js import anywhere in jarvis/."""
    for name in _MODULES:
        s = _src(name)
        assert not re.search(r"from\s*'[^']*fx\.js", s) and "fxRate" not in s, name
    assert "Promise.allSettled" in _src("main.js") and "Promise.all(" not in _src("main.js")


@_needs_node
def test_regions_grouping_avg_rank_and_sort():
    fx = json.dumps(_FIXTURE["G_geography"])
    r = _node(_PRELUDE + f"""
const G = {fx};
const rg = await import(base + 'jarvis/regions.js?v=3');
const cols = rg.groupByLocation(G);
const ins = (id, r1, d, risk = 2, close = 1) => ({{ id, return_1y_pct: r1, daily_return_pct: d, risk_score: risk, close }});
const mixed = [ins('A', 10, 1), ins('B', null, 2), ins('C', 20, 3), ins('D', null, null)];
const dayOnly = [ins('X', null, 1), ins('Y', null, 3)];
console.log(JSON.stringify({{
  cols: Object.fromEntries(Object.entries(cols).map(([k, v]) => [k, v.map(i => [i.id, i.ccy, i.loc])])),
  all: rg.allInstruments(G).map(i => [i.id, i.loc, i.ccy]),
  loc: ['EU', 'India', 'US', 'Other', 'x'].map(rg.locationOfRegion),
  avg: [rg.regionAvg(mixed), rg.regionAvg(dayOnly), rg.regionAvg([])],
  rank: rg.rankInstruments(mixed).map(i => i.id),
  sortRetDesc: rg.sortGeo(mixed, 'ret', false).map(i => i.id),
  sortRetAsc: rg.sortGeo(mixed, 'ret', true).map(i => i.id),
  sortId: rg.sortGeo(mixed, 'id', false).map(i => i.id),
  label: [rg.retLabel(mixed[0]), rg.retLabel(mixed[1]), rg.retLabel(mixed[3])],
  empty: rg.locInstrumentsHtml([], null, 'india'),
  meta: rg.locHeaderMeta(cols.us),
}}));""")
    assert r["cols"] == {"europe": [["E1", "EUR", "europe"]], "india": [["NIFTY", "INR", "india"]],
                         "us": [["NVIDIA", "USD", "us"]]}                      # Other is not a column
    assert ["AEX", None, "EUR"] in r["all"]                               # ... but kept for map + table
    assert r["loc"] == ["europe", "india", "us", None, None]
    assert r["avg"][0] == {"value": 15, "est": False}                     # D7: 1Y average only
    assert r["avg"][1] == {"value": 2, "est": True}                       # daily fallback, (est.)
    assert r["avg"][2] == {"value": None, "est": False}
    assert r["rank"] == ["C", "A", "B", "D"]                              # 1Y, daily fallback, null last
    assert r["sortRetDesc"] == ["C", "A", "B", "D"] and r["sortRetAsc"] == ["B", "A", "C", "D"]
    assert r["sortId"] == ["D", "C", "B", "A"]
    assert r["label"] == ["+10.0%", "+2.0% (est.)", "—"]
    assert "No instruments for India yet." in r["empty"]
    assert r["meta"] == "1 instruments · ranked by 1Y return"


@_needs_node
def test_columns_each_in_own_currency_and_kpi_fields():
    """D1: each column formats with its own A5 currency; DR-A3 KPI fields; legacy cash in EUR."""
    fx = json.dumps(_FIXTURE)
    r = _node(_PRELUDE + f"""
const FX = {fx};
const pf = await import(base + 'jarvis/portfolio.js?v=3');
const rg = await import(base + 'jarvis/regions.js?v=3');
const clone = o => JSON.parse(JSON.stringify(o));
const inr = clone(FX.A5_portfolio); inr.location = 'india'; inr.currency = 'INR';
const usd = clone(FX.A5_portfolio); usd.location = 'us'; usd.currency = 'USD';
const legacy = clone(FX.A5_portfolio); legacy.currency = 'INR'; legacy.perf.money.legacy_note = true;
const none = clone(FX.A5_portfolio); none.perf.money = null; none.instruments = [];
const pick = clone(FX.A5_portfolio); pick.perf.money = null;
const fmt = (v, c) => new Intl.NumberFormat(undefined, {{ style: 'currency', currency: c, maximumFractionDigits: 0 }}).format(v);
console.log(JSON.stringify({{
  eur: pf.locPortfolioHtml(FX.A5_portfolio, 'europe'), inr: pf.locPortfolioHtml(inr, 'india'),
  usd: pf.locPortfolioHtml(usd, 'us'), legacy: pf.locPortfolioHtml(legacy, 'india'),
  none: pf.locPortfolioHtml(none, 'us'), pick: pf.locPortfolioHtml(pick, 'europe'),
  kpis: pf.locKpisHtml(FX.A5_portfolio),
  f: {{ eur: fmt(10310, 'EUR'), inr: fmt(10310, 'INR'), usd: fmt(10310, 'USD'), cash_eur: fmt(12.5, 'EUR'), cash_inr: fmt(12.5, 'INR') }},
  ccy: [rg.locCurrency('india', null), rg.locCurrency('us', null), rg.locCurrency('europe', inr)],
  title: [pf.detailTitle('india', 'INR'), pf.detailDivider('us')],
}}));""")
    f = r["f"]
    assert f["eur"] in r["eur"] and f["inr"] in r["inr"] and f["usd"] in r["usd"]
    assert f["inr"] not in r["eur"] and f["eur"] not in r["usd"]
    assert "My portfolio" in r["eur"] and "60% · 40 units" in r["eur"] and "Leftover cash" in r["eur"]
    assert "Leftover cash (EUR, older portfolio)" in r["legacy"] and f["cash_eur"] in r["legacy"]
    assert "No saved portfolio for US" in r["none"] and "—" in r["none"]
    assert "Jarvis pick — not saved yet" in r["pick"] and "E1" in r["pick"] and "60%" in r["pick"]
    # DR-A3: Value = money.value_now, P&L = money.pnl, This year = perf.ytd_return, Target = perf.goal_return
    for label, value in (("Value", f["eur"]), ("P&amp;L", "€310"), ("This year", "3.1%"), ("Target", "7.8%")):
        assert label in r["kpis"], label
    assert "3.1%" in r["kpis"] and "7.8%" in r["kpis"]
    assert r["ccy"] == ["INR", "USD", "INR"]
    assert r["title"] == ["India in detail · INR", "US IN DETAIL"]


@_needs_node
def test_geo_map_colours_held_and_skipped():
    fx = json.dumps(_FIXTURE)
    r = _node(_PRELUDE + f"""
const FX = {fx};
const rg = await import(base + 'jarvis/regions.js?v=3');
const {{ C }} = await import(base + 'shared/charts.js');
const g = JSON.parse(JSON.stringify(FX.G_geography));
g.regions[2].instruments.push({{ ...g.regions[2].instruments[0], id: 'NO1Y', return_1y_pct: null }});
const m = rg.geoMapData(g, {{ europe: FX.A5_portfolio }});
console.log(JSON.stringify({{ skipped: m.skipped, plotted: m.plotted,
  ds: m.datasets.map(d => [d.label, d.data.map(p => [p.id, p.held]), d.pointRadius]),
  col: m.datasets.map(d => d.backgroundColor[0].slice(0, 7)), C: [C.run, C.warn, C.mon, C.t4] }}));""")
    assert r["skipped"] == 1 and r["plotted"] == 4
    assert [d[0] for d in r["ds"]] == ["Europe", "India", "US", "Other"]
    assert r["ds"][0][1] == [["E1", True]] and r["ds"][0][2] == [8]       # held → larger dot
    assert r["ds"][1][2] == [5]
    assert r["col"] == r["C"]


@_needs_node
def test_portfolio_section_loads_g_and_a5_in_parallel_one_failing():
    """G + A5×3 are all requested before any answers; india's A5 failing blanks only its block —
    the other columns, the map and the table still render."""
    fx = json.dumps(_FIXTURE)
    r = _node(_PRELUDE + f"""
const FX = {fx};
store.auth_token = 'fresh';
const els = {{}};
const mk = id => ({{ id, innerHTML: '', textContent: '', hidden: false, dataset: {{}}, style: {{}},
  _cls: new Set(), get classList() {{ const s = this._cls; return {{ toggle: (c, on) => (on ? s.add(c) : s.delete(c)),
  add: c => s.add(c), remove: c => s.delete(c), contains: c => s.has(c) }}; }},
  addEventListener() {{}}, setAttribute() {{}}, querySelector: () => null, querySelectorAll: () => [],
  closest() {{ return els['wrap:' + id] ||= mk('wrap:' + id); }}, remove() {{}} }});
document.getElementById = id => (els[id] ||= mk(id));
document.querySelector = () => null;
const charts = [];
globalThis.Chart = function (ctx, cfg) {{ charts.push([ctx.id, cfg.type]); this.destroy = () => {{}}; }};
Chart.defaults = {{ font: {{}} }}; Chart.register = () => {{}};
const pending = [];
globalThis.fetch = (url) => new Promise((res) => pending.push({{ url, res }}));
const m = await import(base + 'jarvis/main.js?v=3');
const done = m.loadPortfolioSection();
await new Promise(r => setTimeout(r, 20));
const before = pending.map(p => p.url).sort();
const a5 = loc => {{ const p = JSON.parse(JSON.stringify(FX.A5_portfolio)); p.location = loc;
  p.currency = {{ europe: 'EUR', india: 'INR', us: 'USD' }}[loc]; return p; }};
for (const p of pending.splice(0)) {{
  if (p.url.includes('geography-overview')) p.res(jr(FX.G_geography));
  else if (p.url.includes('location=india')) p.res(jr({{ detail: 'india down' }}, 500));
  else if (p.url.includes('/jarvis/portfolio')) p.res(jr(a5(p.url.split('location=')[1])));
}}
for (let i = 0; i < 20 && !pending.length; i++) await new Promise(r => setTimeout(r, 5));
const a6 = pending.map(p => p.url);
for (const p of pending.splice(0)) p.res(jr({{ detail: 'no A6 here' }}, 500));
await done;
const g = id => els[id] || {{}};
console.log(JSON.stringify({{ before, a6, charts,
  pf: ['europe', 'india', 'us'].map(l => g('jv-loc-pf-' + l).innerHTML || g('jv-loc-pf-' + l).textContent),
  inst: ['europe', 'india', 'us'].map(l => g('jv-loc-inst-' + l).innerHTML),
  ccy: ['europe', 'india', 'us'].map(l => g('jv-loc-ccy-' + l).textContent),
  table: g('jv-geo-table').innerHTML, status: [g('jv-pf-status').textContent, g('jv-pf-status').hidden],
  title: g('jv-pf-detail-title').textContent, active: g('jv-loc-col-europe')._cls.has('is-active'),
  stale: m.S.pfStale, err: m.S.pfErr }}));""")
    assert r["before"] == ["/api/v1/experience/jarvis/portfolio?location=europe",
                           "/api/v1/experience/jarvis/portfolio?location=india",
                           "/api/v1/experience/jarvis/portfolio?location=us",
                           "/api/v1/experience/rita/geography-overview"]
    assert r["a6"] == ["/api/v1/experience/jarvis/instrument?location=europe&instrument=E1"]
    eur, ind, us = r["pf"]
    assert "My portfolio" in eur and "My portfolio" in us
    assert ind == "Couldn't load — india down"
    assert all("jv-loc-row" in h for h in r["inst"])                     # G still rendered for every column
    assert r["ccy"] == ["EUR", "INR", "USD"]
    assert ["jv-geo-map", "scatter"] in r["charts"]
    assert "E1" in r["table"] and "NVIDIA" in r["table"] and "AEX" in r["table"]
    assert r["status"] == ["", True]
    assert r["title"] == "Europe in detail · EUR" and r["active"] is True
    assert r["stale"] == {"europe": False, "india": True, "us": False}
    assert r["err"]["india"] == "india down"


@_needs_node
def test_geo_table_sort_header_is_delegated():
    r = _node(_PRELUDE + """
const rg = await import(base + 'jarvis/regions.js?v=3');
const got = [];
rg.initGeoTable(c => got.push(c));
const btn = sel => ({ closest: s => (s === 'thead button[data-sort]' ? { dataset: { sort: sel } } : null) });
_listeners['jv-geo-table'][0]({ target: btn('risk') });
_listeners['jv-geo-table'][0]({ target: btn('yours') });            // not sortable
_listeners['jv-geo-table'][0]({ target: { closest: () => null } });
const html = rg.geoTableHtml([], { col: 'risk', asc: true }, {});
console.log(JSON.stringify({ got, html }));""")
    assert r["got"] == ["risk"]
    assert 'data-sort="risk"' in r["html"] and "Risk ▲" in r["html"] and 'data-sort="yours"' not in r["html"]
