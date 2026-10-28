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
- jarvis.html: the login gate is the stub's, verbatim; every §5 DOM id exists; main.js?v=2

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
                             "portfolio.js", "instrument.js", "concepts.js"}


# ── stale token (A2, A3, A4, A5, A6) ───────────────────────────────────────────

_CALLS = {
    "A2": ("chat.js", "openSession('europe')", "POST /api/v1/workflow/jarvis/session"),
    "A3": ("chat.js", "sendMessage('s-1', 'use my goal', 'europe')", "POST /api/v1/workflow/jarvis/message"),
    "A4": ("chat.js", "loadState('india')", "GET /api/v1/experience/jarvis/state?location=india"),
    "A5": ("portfolio.js", "loadPortfolio('us')", "GET /api/v1/experience/jarvis/portfolio?location=us"),
    "A6": ("instrument.js", "loadInstrument('india', 'NIFTY')",
           "GET /api/v1/experience/jarvis/instrument?location=india&instrument=NIFTY"),
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
const m = await import(base + 'jarvis/{mod}?v=2');
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
const m = await import(base + 'jarvis/chat.js?v=2');
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
const m = await import(base + 'jarvis/chat.js?v=2');
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
const chat = await import(base + 'jarvis/chat.js?v=2');
const plan = await import(base + 'jarvis/plan.js?v=2');
const pf = await import(base + 'jarvis/portfolio.js?v=2');
const inst = await import(base + 'jarvis/instrument.js?v=2');
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
                "engines", "levels_rita", "rationale_rita", "toggle_rita"):
        _assert_escaped(r[key])
    # the id is an attribute value: quotes escaped, so it can't break out of data-inst
    assert 'data-inst="&lt;img src=x onerror=&quot;alert(1)&quot;&gt;&#39;&quot;"' in r["grid"]
    assert "onclick" not in "".join(r.values())


@_needs_node
def test_unknown_card_kind_renders_nothing():
    r = _node(_PRELUDE + """
const chat = await import(base + 'jarvis/chat.js?v=2');
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
const pf = await import(base + 'jarvis/portfolio.js?v=2');
const inst = await import(base + 'jarvis/instrument.js?v=2');
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
const { esc } = await import(base + 'jarvis/esc.js?v=2');
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
    assert qs == {"v=2"}


@_needs_node
def test_main_module_graph_loads():
    r = _node(_PRELUDE + """
await import(base + 'jarvis/main.js?v=2');
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
const chat = await import(base + 'jarvis/chat.js?v=2');
const plan = await import(base + 'jarvis/plan.js?v=2');
const pf = await import(base + 'jarvis/portfolio.js?v=2');
const inst = await import(base + 'jarvis/instrument.js?v=2');
const cx = await import(base + 'jarvis/concepts.js?v=2');
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


@pytest.mark.parametrize("group,fixture_key", [("A4", "A4_state"), ("A5", "A5_portfolio"), ("A6", "A6_instrument")])
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
chart-modal-img""".split()


def test_html_has_every_design_id_once():
    html = _HTML.read_text()
    ids = re.findall(r'\bid="([^"]+)"', html)
    for i in _DESIGN_IDS:
        assert ids.count(i) == 1, i
    assert len(ids) == len(set(ids))


def test_html_loads_main_v2_and_chartjs():
    html = _HTML.read_text()
    assert '<script type="module" src="./js/jarvis/main.js?v=2"></script>' in html
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
    for cid in ("jv-pnl-chart", "jv-target-chart", "jv-engine-chart", "jv-inst-chart", "jv-sleeve-chart"):
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
const cx = await import(base + 'jarvis/concepts.js?v=2');
const {{ COPY }} = await import(base + 'jarvis/copy.js?v=2');
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
