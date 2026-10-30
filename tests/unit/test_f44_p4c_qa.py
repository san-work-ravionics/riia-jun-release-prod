"""F44 P4c QA — Jarvis portfolio page (Europe / India / US columns, risk-vs-return map, sortable table).

Adds to the engineer's ``test_f44_p4_js.py`` (same node harness, no browser, no network):

- API-frontend contract against the *schemas* (not only the fixture): every G field the JS reads is a
  field of ``rita.schemas.geography.GeographyOverviewResponse``; every A5 field the P4c column renders
  read is a field of ``rita.schemas.jarvis.PortfolioPageOut``.
- Architect edge cases not covered by the engineer: geography-overview failing / empty (4), G retried
  on next open (4), current location's A5 failing hides drill-down (1), empty location column (3),
  Other with null currency (5), missing risk / 1Y → skipped + nulls last both ways (6), case-insensitive
  Held / Picked (8), cached re-open makes no G/A5 request (9), hostile strings in the table (10).
- CR-P4c-1: Concepts opened first draws the map into the hidden Portfolio view; opening Portfolio
  afterwards must redraw or resize it. Fixed in main.js (showTab redraws from cache); regression test.
- DR-A4: wall-clock first paint is not measurable without a browser; the parallel-load test in
  ``test_f44_p4_js.py`` asserts the 4 requests start before any resolves; here G + 3×A5 are also
  shown to be in flight concurrently (not sequential).
"""
from __future__ import annotations

import json
import shutil
import types
import typing

import pytest
from pydantic import BaseModel

from rita.schemas.geography import GeographyOverviewResponse
from rita.schemas.jarvis import PortfolioPageOut
from tests.unit.test_f44_p4_js import _FIXTURE, _PRELUDE, _RECORDER, HOSTILE, _node

_needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


# ── schema paths (Pydantic model → dotted field paths, lists as "[]") ─────────

def _models_in(tp) -> list[tuple[type[BaseModel] | None, bool]]:
    """(model or None, is_list) for each branch of an annotation."""
    origin = typing.get_origin(tp)
    if origin in (typing.Union, types.UnionType):
        out = []
        for a in typing.get_args(tp):
            out += _models_in(a)
        return out
    if origin is typing.Annotated:
        return _models_in(typing.get_args(tp)[0])
    if origin in (list, tuple, set):
        return [(m, True) for m, _ in _models_in(typing.get_args(tp)[0])]
    if isinstance(tp, type) and issubclass(tp, BaseModel):
        return [(tp, False)]
    return [(None, False)]


def _schema_paths(model: type[BaseModel], p: str = "", depth: int = 0) -> set[str]:
    out: set[str] = set()
    if depth > 6:
        return out
    for name, f in model.model_fields.items():
        q = f"{p}.{name}" if p else name
        for sub, is_list in _models_in(f.annotation):
            out.add(q)
            if sub is not None:
                out |= _schema_paths(sub, q + ("[]" if is_list else ""), depth + 1)
            elif is_list:
                out.add(q)
    return out


_G_SCHEMA = _schema_paths(GeographyOverviewResponse)
_A5_SCHEMA = _schema_paths(PortfolioPageOut)


@pytest.fixture(scope="module")
def p4c_reads():
    """Fields read by the P4c renders only (regions.js + locKpisHtml / locPortfolioHtml / detail title)."""
    if shutil.which("node") is None:
        pytest.skip("node not installed")
    fx = json.dumps(_FIXTURE)
    return _node(_PRELUDE + _RECORDER + f"""
const FX = {fx};
const clone = o => JSON.parse(JSON.stringify(o));
const pf = await import(base + 'jarvis/portfolio.js?v=3');
const rg = await import(base + 'jarvis/regions.js?v=3');
for (const src of ['saved', 'mixed', 'model_sleeves', 'model_sleeves_preview', 'none']) {{
  for (const variant of ['full', 'legacy', 'no_money', 'no_perf']) {{
    const v = clone(FX.A5_portfolio); v.pnl_source = src;
    if (variant === 'legacy') v.perf.money.legacy_note = true;
    if (variant === 'no_money') v.perf.money = null;
    if (variant === 'no_perf') v.perf = null;
    const q = rec('A5', v);
    pf.locKpisHtml(q); pf.locPortfolioHtml(q, 'india'); rg.locCurrency('india', q);
  }}
}}
const g = rec('G', clone(FX.G_geography));
const pfs = {{ europe: rec('A5', clone(FX.A5_portfolio)), india: rec('A5', clone(FX.A5_portfolio)),
               us: rec('A5', clone(FX.A5_portfolio)) }};
const cols = rg.groupByLocation(g);
for (const l of rg.LOCS) {{ rg.locAvgHtml(cols[l]); rg.locInstrumentsHtml(cols[l], pfs[l], l); rg.yoursText('E1', pfs, l); }}
const all = rg.allInstruments(g);
for (const col of rg.GEO_COLS) for (const asc of [true, false]) rg.geoTableHtml(all, {{ col, asc }}, pfs);
rg.geoMapData(g, pfs);
console.log(JSON.stringify(Object.fromEntries(Object.entries(seen).map(([k, v]) => [k, [...v].sort()]))));""")


# ── 1. API-frontend contract (schema, not just fixture) ───────────────────────

# The JS annotates every geography instrument with region / loc / ccy (regions.js _annotate) —
# those are client-side keys, not response fields.
_G_CLIENT_KEYS = {"regions[].instruments[].loc", "regions[].instruments[].ccy", "regions[].instruments[].region"}


def test_contract_g_reads_are_geography_schema_fields(p4c_reads):
    reads = set(p4c_reads["G"]) - _G_CLIENT_KEYS
    expected = {"regions", "regions[].region", "regions[].instruments", "regions[].instruments[].id",
                "regions[].instruments[].sector", "regions[].instruments[].close",
                "regions[].instruments[].daily_return_pct", "regions[].instruments[].return_1y_pct",
                "regions[].instruments[].risk_score", "regions[].instruments[].signal",
                "regions[].instruments[].currency"}
    assert expected <= reads, sorted(expected - reads)               # the design's field list is really read
    assert reads <= _G_SCHEMA, sorted(reads - _G_SCHEMA)               # ... and every read is a schema field


def test_contract_a5_column_reads_are_portfolio_schema_fields(p4c_reads):
    reads = set(p4c_reads["A5"])
    for f in ("currency", "perf.money.value_now", "perf.money.pnl", "perf.ytd_return", "perf.goal_return",
              "perf.money.name", "perf.money.cash", "perf.money.legacy_note",
              "perf.money.holdings[].instrument_id", "perf.money.holdings[].shares",
              "perf.holdings[].instrument_id", "perf.holdings[].allocation_pct",
              "instruments[].instrument_id", "instruments[].selected", "instruments[].held",
              "instruments[].allocation_pct"):
        assert f in reads, f
    assert reads <= _A5_SCHEMA, sorted(reads - _A5_SCHEMA)


def test_contract_fixture_validates_against_schemas():
    GeographyOverviewResponse.model_validate(_FIXTURE["G_geography"])
    PortfolioPageOut.model_validate(_FIXTURE["A5_portfolio"])
    # G fixture covers every region the JS maps to a column + Other
    assert [r["region"] for r in _FIXTURE["G_geography"]["regions"]] == ["EU", "India", "US", "Other"]


def test_endpoint_handler_returns_the_contract_model():
    from rita.api.experience import jarvis as ep
    routes = {r.path: r for r in ep.router.routes}
    a5 = next(r for p, r in routes.items() if p.endswith("/portfolio"))
    assert a5.response_model is PortfolioPageOut and a5.methods == {"GET"}


# ── 2. pure-render edge cases ─────────────────────────────────────────────────

@_needs_node
def test_edge_cases_pure_renders():
    fx = json.dumps(_FIXTURE)
    r = _node(_PRELUDE + f"""
const FX = {fx};
const clone = o => JSON.parse(JSON.stringify(o));
const rg = await import(base + 'jarvis/regions.js?v=3');
const ins = (id, r1, risk, close) => ({{ id, return_1y_pct: r1, daily_return_pct: null, risk_score: risk, close }});
const rows = [ins('A', 5, null, 10), ins('B', 1, 4, null), ins('C', 9, 1, 30)];
// 8: case-insensitive Held / Picked (A5 row 'e1' vs G id 'E1')
const pf = clone(FX.A5_portfolio);
pf.instruments = [{{ ...pf.instruments[0], instrument_id: 'e1', held: true, selected: false }}];
const g = clone(FX.G_geography);
// 5: Other instrument with null currency; 6: one with no risk score
g.regions[3].instruments[0].currency = null;
g.regions[2].instruments.push({{ ...g.regions[2].instruments[0], id: 'NORISK', risk_score: null }});
const all = rg.allInstruments(g);
const aex = all.find(i => i.id === 'AEX');
const table = rg.geoTableHtml(all, {{ col: 'ccy', asc: true }}, {{ europe: pf }});
const map = rg.geoMapData(g, {{ europe: pf }});
// 10: hostile sector / signal / id in an Other row
const h = clone(FX.G_geography);
Object.assign(h.regions[3].instruments[0], {{ id: {json.dumps(HOSTILE)}, sector: {json.dumps(HOSTILE)}, signal: {json.dumps(HOSTILE)} }});
console.log(JSON.stringify({{
  held: rg.locInstrumentsHtml(rg.groupByLocation(g).europe, pf, 'europe'),
  yours: rg.yoursText('E1', {{ europe: pf }}, 'europe'),
  aexCcy: aex.ccy, aexRow: table.split('<tr>').find(s => s.includes('>AEX<')),
  mapIds: map.datasets.flatMap(d => d.data.map(p => p.id)), skipped: map.skipped,
  riskAsc: rg.sortGeo(rows, 'risk', true).map(i => i.id), riskDesc: rg.sortGeo(rows, 'risk', false).map(i => i.id),
  closeAsc: rg.sortGeo(rows, 'close', true).map(i => i.id), closeDesc: rg.sortGeo(rows, 'close', false).map(i => i.id),
  hostileTable: rg.geoTableHtml(rg.allInstruments(h), {{ col: 'ret', asc: false }}, {{}}),
  hostileCol: rg.locInstrumentsHtml(rg.allInstruments(h).filter(i => !i.loc), null, 'europe'),
}}));""")
    assert "jv-badge-held" in r["held"] and r["yours"] == "Held"                       # edge 8
    assert r["aexCcy"] is None and '<td class="mono">—</td>' in r["aexRow"]           # edge 5: "—"
    assert "AEX" in r["mapIds"]                                                         # ... still plotted
    assert "NORISK" not in r["mapIds"] and r["skipped"] == 1                            # edge 6: skipped
    assert r["riskAsc"] == ["C", "B", "A"] and r["riskDesc"] == ["B", "C", "A"]         # nulls last both ways
    assert r["closeAsc"] == ["A", "C", "B"] and r["closeDesc"] == ["C", "A", "B"]
    for html in (r["hostileTable"], r["hostileCol"]):                                   # edge 10
        assert "<img" not in html and "&lt;img" in html


@_needs_node
def test_edge_empty_location_column_and_empty_geography():
    """Edge 3: a location with no instruments → 0 instruments, avg "—", empty text; portfolio block from A5.
    Edge 4: regions [] → map + table empty texts."""
    fx = json.dumps(_FIXTURE)
    r = _node(_PRELUDE + f"""
const FX = {fx};
const els = {{}};
const mk = id => ({{ id, innerHTML: '', textContent: '', hidden: false, dataset: {{}}, style: {{}},
  closest() {{ return els['wrap:' + id] ||= mk('wrap:' + id); }}, addEventListener() {{}} }});
document.getElementById = id => (els[id] ||= mk(id));
const rg = await import(base + 'jarvis/regions.js?v=3');
const g = JSON.parse(JSON.stringify(FX.G_geography)); g.regions[1].instruments = [];
rg.renderColumn('india', {{ geo: g, pf: FX.A5_portfolio }});
rg.renderUniverse({{ regions: [], version: 1 }}, {{}});
const e = id => els[id] || {{}};
console.log(JSON.stringify({{ meta: e('jv-loc-meta-india').textContent, avg: e('jv-loc-avg-india').innerHTML,
  inst: e('jv-loc-inst-india').innerHTML, pf: e('jv-loc-pf-india').innerHTML,
  mapEmpty: [e('jv-geo-map-empty').textContent, e('jv-geo-map-empty').hidden], mapWrapHidden: e('wrap:jv-geo-map').hidden,
  tableEmpty: e('jv-geo-table-empty').textContent, tableWrapHidden: e('jv-geo-table-wrap').hidden }}));""")
    assert r["meta"] == "0 instruments"
    assert ">—<" in r["avg"]
    assert "No instruments for India yet." in r["inst"]
    assert "jv-loc-kpis" in r["pf"]
    assert r["mapEmpty"] == ["No price data available.", False] and r["mapWrapHidden"] is True
    assert r["tableEmpty"] == "No instruments available." and r["tableWrapHidden"] is True


# ── 3. main.js orchestration edge cases (node DOM stub) ───────────────────────

_MAIN_HARNESS = """
const FX = __FX__;
store.auth_token = 'fresh';
const els = {};
const mk = id => ({ id, innerHTML: '', textContent: '', hidden: false, dataset: {}, style: {}, value: '',
  _cls: new Set(), get classList() { const s = this._cls; return { toggle: (c, on) => (on ? s.add(c) : s.delete(c)),
  add: c => s.add(c), remove: c => s.delete(c), contains: c => s.has(c) }; },
  addEventListener(ev, fn) { ((this.listeners ||= {})[ev] ||= []).push(fn); }, setAttribute() {}, removeAttribute() {},
  querySelector(sel) { return els[id + ' ' + sel] ||= mk(id + ' ' + sel); }, querySelectorAll: () => [],
  insertAdjacentHTML() {}, appendChild(c) { return c; }, scrollIntoView() {}, focus() {},
  closest() { return els['wrap:' + id] ||= mk('wrap:' + id); }, remove() {} });
// Concepts chart canvases exist only once concepts.js renders them into the panel (not in a stub).
document.getElementById = id => (/^jv-cx-s\d/.test(id) ? null : (els[id] ||= mk(id)));
document.querySelector = () => null;
document.createElement = tag => mk('new:' + tag);
globalThis.history = { replaceState() {} };
const charts = [];
globalThis.Chart = function (ctx, cfg) {
  const rec = { id: ctx.id, type: cfg.type, viewHidden: !!(els['jv-view-portfolio'] || {}).hidden, resized: [] };
  charts.push(rec);
  this.destroy = () => {}; this.update = () => {};
  this.resize = () => rec.resized.push(!!(els['jv-view-portfolio'] || {}).hidden);
};
Chart.defaults = { font: {} }; Chart.register = () => {};
const a5 = loc => { const p = JSON.parse(JSON.stringify(FX.A5_portfolio)); p.location = loc;
  p.currency = { europe: 'EUR', india: 'INR', us: 'USD' }[loc]; return p; };
const log = [];
let route = (url) => {
  if (url.includes('/auth/token')) return jr({ access_token: 'fresh' });
  if (url.includes('/warmup')) return jr(FX.A1_warmup);
  if (url.includes('/jarvis/state')) return jr(FX.A4_state);
  if (url.includes('/jarvis/session')) return jr(FX.A2_session);
  if (url.includes('geography-overview')) return jr(FX.G_geography);
  if (url.includes('/jarvis/portfolio')) return jr(a5(url.split('location=')[1]));
  if (url.includes('/jarvis/instrument')) return jr(FX.A6_instrument);
  return jr({ detail: 'nope' }, 404);
};
globalThis.fetch = async (url) => { log.push(url); return route(url); };
const settle = async () => { for (let i = 0; i < 40; i++) await new Promise(r => setTimeout(r, 2)); };
const m = await import(base + 'jarvis/main.js?v=3');
const e = id => els[id] || {};
"""


def _main(script: str):
    return _node(_PRELUDE + _MAIN_HARNESS.replace("__FX__", json.dumps(_FIXTURE)) + script)


@_needs_node
def test_edge_geography_fails_columns_err_a5_still_render_and_g_retried():
    """Edge 4: G 500 → each column's instrument list shows err.load, map + table empty texts, A5 blocks
    and the detail still render; G is not cached, so the next open requests it again."""
    r = _main("""
const base_route = route;
route = url => (url.includes('geography-overview') ? jr({ detail: 'geo down' }, 500) : base_route(url));
await m.loadPortfolioSection(); await settle();
const first = { inst: ['europe', 'india', 'us'].map(l => e('jv-loc-inst-' + l).textContent),
  pf: ['europe', 'india', 'us'].map(l => e('jv-loc-pf-' + l).innerHTML),
  map: e('jv-geo-map-empty').textContent, table: e('jv-geo-table-empty').textContent,
  title: e('jv-pf-detail-title').textContent, geoErr: m.S.geoErr, geo: m.S.geo };
route = base_route; log.length = 0;
await m.loadPortfolioSection(); await settle();
console.log(JSON.stringify({ first, retry: log.filter(u => !u.includes('/instrument')),
  inst2: e('jv-loc-inst-europe').innerHTML, table2: e('jv-geo-table').innerHTML }));""")
    f = r["first"]
    assert f["inst"] == ["Couldn't load — geo down"] * 3
    assert all("jv-loc-kpis" in h for h in f["pf"])                     # A5 blocks still render
    assert f["map"] == "No price data available." and f["table"] == "No instruments available."
    assert f["title"] == "Europe in detail · EUR"
    assert f["geoErr"] == "geo down" and f["geo"] is None
    assert r["retry"] == ["/api/v1/experience/rita/geography-overview"]  # G retried; A5 cached, not re-fetched
    assert "jv-loc-row" in r["inst2"] and "NVIDIA" in r["table2"]


@_needs_node
def test_edge_current_location_a5_fails_detail_shows_error_and_hides_drilldown():
    """Edge 1: the current location's A5 fails → jv-pf-source shows err.load, drill-down hidden, no A6."""
    r = _main("""
const base_route = route;
route = url => (url.includes('portfolio?location=europe') ? jr({ detail: 'eu down' }, 500) : base_route(url));
await m.loadPortfolioSection(); await settle();
console.log(JSON.stringify({ src: e('jv-pf-source').textContent, sec: e('sec-jv-instrument').hidden,
  a6: log.filter(u => u.includes('/instrument')), col: e('jv-loc-pf-europe').textContent,
  us: e('jv-loc-pf-us').innerHTML, title: e('jv-pf-detail-title').textContent }));""")
    assert r["src"] == "Couldn't load — eu down"
    assert r["sec"] is True and r["a6"] == []
    assert r["col"] == "Couldn't load — eu down" and "jv-loc-kpis" in r["us"]
    assert r["title"] == "Europe in detail · EUR"                        # region currency, no A5 needed


@_needs_node
def test_edge_cached_reopen_makes_no_g_or_a5_request():
    """Edge 9: a second open with everything cached re-renders without requesting G or A5."""
    r = _main("""
await m.loadPortfolioSection(); await settle();
const firstCount = log.filter(u => !u.includes('/instrument')).length;
log.length = 0;
await m.loadPortfolioSection(); await settle();
console.log(JSON.stringify({ firstCount, second: log.filter(u => !u.includes('/instrument')),
  title: e('jv-pf-detail-title').textContent }));""")
    assert r["firstCount"] == 4
    assert r["second"] == []
    assert r["title"] == "Europe in detail · EUR"


@_needs_node
def test_dr_a4_g_and_three_a5_in_flight_together():
    """DR-A4 proxy: with every response delayed 50 ms, G + 3×A5 finish in ~one delay (parallel), not four."""
    r = _main("""
let open = 0, peak = 0;
const base_route = route;
globalThis.fetch = async (url) => { log.push(url);
  if (url.includes('/instrument')) return base_route(url);
  open++; peak = Math.max(peak, open); await new Promise(r => setTimeout(r, 50)); open--; return base_route(url); };
const t0 = Date.now();
await m.loadPortfolioSection();
console.log(JSON.stringify({ peak, ms: Date.now() - t0 }));""")
    assert r["peak"] == 4
    assert r["ms"] < 4 * 50


# ── 4. CR-P4c-1: Concepts → Portfolio map render ─────────────────────────────

def _boot_then(script: str):
    # Capture main.js's DOMContentLoaded handler so the real boot (tabs, listeners) runs.
    pre = _PRELUDE.replace("globalThis.document = { addEventListener(){},",
                           "globalThis.document = { addEventListener(ev, fn){ if (ev === 'DOMContentLoaded') globalThis._boot = fn; },")
    assert pre != _PRELUDE
    return _node(pre + _MAIN_HARNESS.replace("__FX__", json.dumps(_FIXTURE)) + """
await globalThis._boot(); await settle();
const click = id => (e(id).listeners.click || []).forEach(fn => fn({ target: { closest: () => null } }));
""" + script)


@_needs_node
def test_portfolio_first_draws_map_while_visible():
    """Control: Chat → Portfolio draws the map with the Portfolio view visible."""
    r = _boot_then("""
click('jv-tab-portfolio'); await settle();
console.log(JSON.stringify({ map: charts.filter(c => c.id === 'jv-geo-map') }));""")
    assert r["map"] and r["map"][-1]["viewHidden"] is False


@_needs_node
def test_cr_p4c_1_concepts_then_portfolio_redraws_map():
    r = _boot_then("""
click('jv-tab-concepts'); await settle();
const hiddenDraws = charts.filter(c => c.id === 'jv-geo-map').map(c => c.viewHidden);
click('jv-tab-portfolio'); await settle();
const maps = charts.filter(c => c.id === 'jv-geo-map');
const visibleDraw = maps.some(c => !c.viewHidden) || maps.some(c => c.resized.some(h => !h));
console.log(JSON.stringify({ hiddenDraws, visibleDraw, viewHidden: e('jv-view-portfolio').hidden }));""")
    assert r["hiddenDraws"] == [True]                 # precondition: Concepts drew the map into the hidden view
    assert r["viewHidden"] is False
    assert r["visibleDraw"] is True, "map never redrawn / resized after the Portfolio view became visible"
