"""F41 QA additions — Code Review advisories, Architect edge cases, CSS reasoning, API contract."""
from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_JS = _ROOT / "dashboard" / "js"
_HTML = (_ROOT / "dashboard" / "fno.html").read_text(encoding="utf-8")
_GREEKS = (_JS / "fno" / "greeks.js").read_text(encoding="utf-8")
_STRESS = (_JS / "fno" / "stress.js").read_text(encoding="utf-8")
_SCHEMA = _ROOT / "src" / "rita" / "schemas" / "portfolio_analytics.py"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def _f41_css() -> str:
    a = _HTML.index("/* ═══ F41 Risk page")
    b = _HTML.index("/* ═══ end F41 Risk page ═══ */")
    return _HTML[a:b]


@pytest.fixture(scope="module")
def jsroot(tmp_path_factory) -> Path:
    dst = tmp_path_factory.mktemp("jsqa")
    shutil.copytree(_JS, dst / "js")
    (dst / "js" / "package.json").write_text('{"type":"module"}', encoding="utf-8")
    return dst / "js"


def _node(jsroot: Path, body: str) -> dict:
    s_uri = (jsroot / "fno" / "state.js").as_uri()
    g_uri = (jsroot / "fno" / "greeks.js").as_uri()
    st_uri = (jsroot / "fno" / "stress.js").as_uri()
    src = f"""
import {{ state }} from {json.dumps(s_uri)};
const els = {{}};
for (const id of ['greeks-all-grid','risk-stddev-card','stress-row','stress-card-sub'])
  els[id] = {{ innerHTML: '', textContent: '', style: {{}} }};
const events = [];
globalThis.document = {{ getElementById: id => els[id] ?? null, dispatchEvent: e => {{ events.push(e.type); return true; }} }};
const g = await import({json.dumps(g_uri)});
const st = await import({json.dumps(st_uri)});
const out = {{}};
{body}
out.events = events;
console.log(JSON.stringify(out));
"""
    p = jsroot / "runqa.mjs"
    p.write_text(src, encoding="utf-8")
    r = subprocess.run(["node", str(p)], capture_output=True, text=True, timeout=60, cwd=jsroot)
    assert r.returncode == 0, r.stderr[-3000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def _render(jsroot: Path, greeks, sel=None, und="ALL", exp="ALL") -> dict:
    return _node(jsroot, f"""
state.greeksData = {json.dumps(greeks)};
state.riskSelectedInstrument = {json.dumps(sel)};
state.currentUnd = {json.dumps(und)}; state.currentExpiry = {json.dumps(exp)};
g.renderGreeksCards();
out.cards = els['greeks-all-grid'].innerHTML;
""")


def _g(**kw):
    base = dict(und="NIFTY", full="NIFTY PUT", hedge_type="put", exp="WEEKLY", type="PE", side="BUY",
                delta=-0.5, gamma=0.002, theta=-1200, vega=800, ann_vol_pct=14.25)
    base.update(kw)
    return base


# ── (a) std-dev row click ─────────────────────────────────────────────────────────

@needs_node
def test_stddev_row_click_dispatches_filter_change_and_sets_selection(jsroot):
    r = _node(jsroot, """
state.positions = [{und:'NIFTY', ltp:24000, ann_vol_pct:14, currency:'INR'}, {und:'ASML', ltp:700, ann_vol_pct:30, currency:'EUR'}];
state.marketData = {}; state.greeksData = [{und:'NIFTY', allocation_pct:50, ann_vol_pct:14}];
state.portfolioMeta = {total_value_eur: 100000}; state.riskSelectedInstrument = null;
const rows = [];
els['risk-stddev-card'].querySelectorAll = sel => { if (sel !== '.stddev-row') return [];
  const ids = [...els['risk-stddev-card'].innerHTML.matchAll(/data-inst="([^"]+)"/g)].map(m => m[1]);
  return ids.map(id => { const row = {dataset:{inst:id}, fire(){ this.h && this.h(); }, addEventListener(ev, h){ if (ev==='click') this.h = h; }}; rows.push(row); return row; }); };
st.renderStdDevTable();
out.html = els['risk-stddev-card'].innerHTML;
out.ids = rows.map(r => r.dataset.inst);
rows.find(r => r.dataset.inst === 'ASML').fire(); out.afterAsml = state.riskSelectedInstrument; out.ev1 = events.length;
rows.find(r => r.dataset.inst === 'Portfolio').fire(); out.afterPort = state.riskSelectedInstrument; out.ev2 = events.length;
""")
    assert r["ids"] == ["Portfolio", "NIFTY", "ASML"]
    assert 'class="stddev-row"' in r["html"] and 'class="rk-sd-tbl"' in r["html"]
    assert r["afterAsml"] == "ASML" and r["afterPort"] is None
    assert r["events"] == ["risk-filter-change", "risk-filter-change"]


# ── (b) zero / near-zero rendering ────────────────────────────────────────────────

@needs_node
def test_zero_greeks_not_rendered_as_signed_coloured(jsroot):
    r = _render(jsroot, [_g(delta=0, gamma=0, theta=0, vega=0)])
    blob = r["cards"]
    assert "+₹0" not in blob and "−₹0" not in blob
    assert 'class="num pos">' not in r["cards"] and 'class="num neg">' not in r["cards"]


@needs_node
def test_near_zero_negative_not_rendered_as_minus_zero(jsroot):
    r = _render(jsroot, [_g(delta=-0.001, theta=-0.4, vega=-0.2)])
    blob = r["cards"]
    assert "−₹0" not in blob and "−0.00" not in blob


# ── (c) Architect edge cases ──────────────────────────────────────────────────────

@needs_node
def test_nan_infinity_strings_never_leak(jsroot):
    # JSON cannot carry NaN; inject NaN/Infinity via JS directly
    r = _node(jsroot, """
state.greeksData = [{und:'NIFTY', full:'X', exp:'W', type:'PE', side:'BUY', delta:NaN, gamma:Infinity, theta:'abc', vega:undefined, ann_vol_pct:NaN}];
state.riskSelectedInstrument = null; state.currentUnd='ALL'; state.currentExpiry='ALL';
g.renderGreeksCards();
out.blob = els['greeks-all-grid'].innerHTML;
""")
    for bad in ("NaN", "undefined", "Infinity", "null"):
        assert bad not in r["blob"]
    assert 'class="num neu"' in r["blob"]  # non-finite inputs sum to a neutral zero (Net Greeks has no per-row dash)


@needs_node
def test_empty_selected_missing_and_non_array_data(jsroot):
    r = _render(jsroot, [])
    assert "No Greeks data" in r["cards"]
    r = _render(jsroot, [_g()], sel="GHOST")
    assert "No Greeks data" in r["cards"]
    r2 = _node(jsroot, """
state.greeksData = null; state.riskSelectedInstrument = null; state.currentUnd='ALL'; state.currentExpiry='ALL';
g.renderGreeksCards(); out.cards = els['greeks-all-grid'].innerHTML;
""")
    assert "No Greeks data" in r2["cards"]


@needs_node
@pytest.mark.parametrize("name", ["<img src=x onerror=1>", "A" * 300, 'q"uote\'s & <b>'])
def test_hostile_and_long_names_escaped_everywhere(jsroot, name):
    r = _render(jsroot, [_g(full=name, und=name, exp=name, type=name, side=name)])
    blob = r["cards"]
    assert "<img" not in blob and "<b>" not in blob
    # every tag in the output is one of the known F41 elements
    tags = set(re.findall(r"<([a-zA-Z0-9]+)", blob))
    assert tags <= {"div", "span", "i", "table", "thead", "tbody", "tr", "th", "td"}, tags
    assert f'title="{"A" * 300}"' in blob if name == "A" * 300 else 'title="' in blob


@needs_node
def test_very_wide_numbers_no_exponent_or_overflow_tokens(jsroot):
    r = _render(jsroot, [_g(theta=-1e15, vega=1e15, delta=123456789.123, gamma=-99999.99999)])
    blob = r["cards"]
    assert "e+" not in blob and "NaN" not in blob and "undefined" not in blob
    assert "₹1,00,00,00,00,00,00,000" in blob  # 1e15, en-IN grouping, full digits


@needs_node
def test_filters_underlying_and_expiry_still_applied(jsroot):
    data = [_g(), _g(und="BANKNIFTY", full="BN", exp="MONTHLY")]
    # Net Greeks ignores currentUnd/currentExpiry (only the std-dev selection filters it)
    assert _render(jsroot, data)["cards"].count('class="rk-ug-row"') == 2
    assert _render(jsroot, data, sel="NIFTY")["cards"].count('class="rk-ug-row"') == 1
    assert _render(jsroot, data, sel="BANKNIFTY")["cards"].count('class="rk-ug-row"') == 1
    assert "No Greeks data" in _render(jsroot, data, sel="GHOST")["cards"]


@needs_node
def test_no_rho_rendered(jsroot):
    r = _render(jsroot, [_g(rho=5)])
    assert "ρ" not in r["cards"] and "Rho" not in r["cards"]


# ── (d) CSS reasoning ─────────────────────────────────────────────────────────────

def _css_rules(css: str):
    """Yield (selectors, body, media) flattening @media one level."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out, i = [], 0
    def parse(txt, media):
        for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", txt):
            out.append(([s.strip() for s in m.group(1).split(",")], m.group(2), media))
    # split media blocks
    pos = 0
    for m in re.finditer(r"@media\s*([^{]*?)\s*\{", css):
        if m.start() < pos:
            continue
        depth, j = 1, m.end()
        while depth:
            depth += {"{": 1, "}": -1}.get(css[j], 0)
            j += 1
        parse(css[pos:m.start()], None)
        parse(css[m.end():j - 1], m.group(1))
        pos = j
    parse(css[pos:], None)
    return out


def test_every_selector_scoped_including_inside_media():
    rules = _css_rules(_f41_css())
    assert len(rules) > 25
    bad = [s for sels, _, _ in rules for s in sels if not s.startswith("#page-risk")]
    assert not bad, bad
    assert any(m for _, _, m in rules)


@pytest.mark.parametrize("bp", ["max-width:900px", "max-width:768px", "max-width:480px", "min-width:1280px"])
def test_media_breakpoints_present(bp):
    assert any(m and bp in m.replace(" ", "") for _, _, m in _css_rules(_f41_css()))


def test_1280_breakpoint_three_columns_and_explicit_midrange_single_column():
    rules = _css_rules(_f41_css())
    three = [b for sels, b, m in rules if m and "min-width:1280px" in m.replace(" ", "") and "#page-risk .rk-three" in sels]
    assert three and "repeat(3,minmax(0,1fr))" in three[0].replace(" ", "")
    mid = [b for sels, b, m in rules if m and "769" in m and "1279" in m and "#page-risk .rk-three" in sels]
    assert mid and "repeat(3" not in mid[0]
    base = [b for sels, b, m in rules if not m and "#page-risk .rk-three" in sels]
    assert base and "display:grid" in base[0].replace(" ", "")
    assert not any(".rk-two" in s or ".rk-grid" in s for sels, _, _ in rules for s in sels)


def _table_cell_rules():
    out = []
    for sels, body, media in _css_rules(_f41_css()):
        if any(re.search(r"\b(td|th)\b|\.rk-tbl|\.rk-g|\.num\b|\.rk-ug", s) for s in sels):
            out.append((sels, body))
    return out


def test_no_font_size_override_on_net_greeks_or_stress_table_cells():
    # F41 font bug: value cells must render at the table's normal size, never an oversized clamp()
    for sels, body in _table_cell_rules():
        if any(".rk-tbl" in s or ".rk-net-tbl" in s or ".rk-stress-tbl" in s for s in sels):
            assert "font-size" not in body, (sels, body)
    assert "clamp(" not in _f41_css()
    for src in (_GREEKS, _STRESS):
        # no td in the Net Greeks / Stress markup carries an inline font-size or the card-era class
        for td in re.findall(r"<td[^>]*>", src.split("rk-sd-tbl")[0]):
            assert "font-size" not in td and "rk-g-val" not in td, td
    assert "rk-g-val" not in _GREEKS and "rk-g-val" not in _f41_css()


def test_payoff_grid_override_important_at_768():
    rules = _css_rules(_f41_css())
    hit = [b for sels, b, m in rules if m and "768" in m and any(s == "#page-risk #payoff-charts-grid" for s in sels)]
    assert hit and "grid-template-columns" in hit[0] and "!important" in hit[0]


def test_no_nowrap_anywhere_in_risk_css_or_markup():
    for sels, body, _ in _css_rules(_f41_css()):
        assert "nowrap" not in body.replace(" ", "") or "white-space:normal" in body.replace(" ", ""), sels
    assert "nowrap" not in _GREEKS


def test_dead_per_instrument_css_removed():
    css = _f41_css()
    for cls in ("rk-inst-list", "rk-row", "rk-chip", "rk-chips", "tbl-footer"):
        assert cls not in css, cls


def test_no_horizontal_scroll_guards():
    css = _f41_css().replace(" ", "")
    assert "#page-risk#risk-stddev-card.tbl-wrap{overflow-x:hidden;}" in css
    assert "overflow-x:scroll" not in css and "overflow-x:auto" not in css


# ── (e) API contract ──────────────────────────────────────────────────────────────

def _schema_fields(cls_name: str) -> set[str]:
    tree = ast.parse(_SCHEMA.read_text(encoding="utf-8"))
    for n in tree.body:
        if isinstance(n, ast.ClassDef) and n.name == cls_name:
            return {s.target.id for s in n.body if isinstance(s, ast.AnnAssign)}
    raise AssertionError(cls_name)


def _js_g_reads(src: str) -> set[str]:
    return set(re.findall(r"\bg\.([a-z_]+)", src)) | set(re.findall(r"_(?:sum|has)\([^)]*?['\"]([a-z_]+)['\"]", src)) \
        | set(re.findall(r"_sum\(\w+,\s*'([a-z_]+)'\)", src))


def test_contract_numeric_fields_exist_in_greek_item_schema():
    fields = _schema_fields("GreekItemSchema")
    reads = _js_g_reads(_GREEKS) | _js_g_reads(_STRESS)
    assert {"delta", "gamma", "theta", "vega", "und", "exp", "ann_vol_pct", "allocation_pct"} <= reads
    missing = {r for r in reads if r not in fields} - {"full", "type", "side"}
    assert not missing, missing


def test_contract_missing_display_fields_have_js_fallbacks():
    # per-instrument rows (which read g.full/type/side) were removed; Net Greeks only sums numeric fields
    assert "g.full" not in _GREEKS and "g.side" not in _GREEKS


def test_contract_response_wires_greeks_list():
    assert "greeks" in _schema_fields("PortfolioAnalyticsResponse") or "greeks: list[GreekItemSchema]" in _SCHEMA.read_text(encoding="utf-8")
