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
for (const id of ['greeks-all-grid','greeks-tbody','greeks-footer','greeks-table-sub','risk-stddev-card','stress-row','stress-card-sub'])
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
g.renderGreeksCards(); g.renderGreeksTable();
out.cards = els['greeks-all-grid'].innerHTML; out.rows = els['greeks-tbody'].innerHTML;
out.foot = els['greeks-footer'].innerHTML; out.sub = els['greeks-table-sub'].textContent;
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
    blob = r["cards"] + r["rows"]
    assert "+₹0" not in blob and "−₹0" not in blob
    assert 'rk-g-val pos">' not in r["cards"] and 'rk-g-val neg">' not in r["cards"]


@needs_node
def test_near_zero_negative_not_rendered_as_minus_zero(jsroot):
    r = _render(jsroot, [_g(delta=-0.001, theta=-0.4, vega=-0.2)])
    blob = r["cards"] + r["rows"]
    assert "−₹0" not in blob and "−0.00" not in blob


# ── (c) Architect edge cases ──────────────────────────────────────────────────────

@needs_node
def test_nan_infinity_strings_never_leak(jsroot):
    # JSON cannot carry NaN; inject NaN/Infinity via JS directly
    r = _node(jsroot, """
state.greeksData = [{und:'NIFTY', full:'X', exp:'W', type:'PE', side:'BUY', delta:NaN, gamma:Infinity, theta:'abc', vega:undefined, ann_vol_pct:NaN}];
state.riskSelectedInstrument = null; state.currentUnd='ALL'; state.currentExpiry='ALL';
g.renderGreeksCards(); g.renderGreeksTable();
out.blob = els['greeks-all-grid'].innerHTML + els['greeks-tbody'].innerHTML + els['greeks-footer'].innerHTML;
""")
    for bad in ("NaN", "undefined", "Infinity", "null"):
        assert bad not in r["blob"]
    assert "—" in r["blob"]


@needs_node
def test_empty_selected_missing_and_non_array_data(jsroot):
    r = _render(jsroot, [])
    assert "No Greeks data" in r["cards"] and "No positions" in r["rows"] and "NaN" not in r["foot"]
    r = _render(jsroot, [_g()], sel="GHOST")
    assert "No Greeks data" in r["cards"] and "No positions" in r["rows"]
    r2 = _node(jsroot, """
state.greeksData = null; state.riskSelectedInstrument = null; state.currentUnd='ALL'; state.currentExpiry='ALL';
g.renderGreeksCards(); g.renderGreeksTable(); out.rows = els['greeks-tbody'].innerHTML;
""")
    assert "No positions" in r2["rows"]


@needs_node
def test_all_zero_greeks_keeps_hedge_plan_note(jsroot):
    r = _render(jsroot, [_g(delta=0, gamma=0, theta=0, vega=0), _g(und="BANKNIFTY", delta=0, gamma=0, theta=0, vega=0)])
    assert "add a hedge plan" in r["sub"]
    r = _render(jsroot, [_g(delta=0, gamma=0, theta=0, vega=5)])
    assert "add a hedge plan" not in r["sub"]


@needs_node
@pytest.mark.parametrize("name", ["<img src=x onerror=1>", "A" * 300, 'q"uote\'s & <b>'])
def test_hostile_and_long_names_escaped_everywhere(jsroot, name):
    r = _render(jsroot, [_g(full=name, und=name, exp=name, type=name, side=name)])
    blob = r["cards"] + r["rows"]
    assert "<img" not in blob and "<b>" not in blob
    # every tag in the output is one of the known F41 elements
    tags = set(re.findall(r"<([a-zA-Z0-9]+)", blob))
    assert tags <= {"div", "span", "i"}, tags
    assert f'title="{"A" * 300}"' in blob if name == "A" * 300 else 'title="' in blob


@needs_node
def test_very_wide_numbers_no_exponent_or_overflow_tokens(jsroot):
    r = _render(jsroot, [_g(theta=-1e15, vega=1e15, delta=123456789.123, gamma=-99999.99999)])
    blob = r["cards"] + r["rows"] + r["foot"]
    assert "e+" not in blob and "NaN" not in blob and "undefined" not in blob
    assert "₹1,00,00,00,00,00,00,000" in blob  # 1e15, en-IN grouping, full digits


@needs_node
def test_filters_underlying_and_expiry_still_applied(jsroot):
    data = [_g(), _g(und="BANKNIFTY", full="BN", exp="MONTHLY")]
    assert _render(jsroot, data, und="BANKNIFTY")["rows"].count('class="rk-row"') == 1
    assert _render(jsroot, data, exp="WEEKLY")["rows"].count('class="rk-row"') == 1
    assert _render(jsroot, data, sel="NIFTY")["cards"].count('class="rk-ug"') == 1


@needs_node
def test_no_rho_rendered(jsroot):
    r = _render(jsroot, [_g(rho=5)])
    assert "ρ" not in r["cards"] + r["rows"] and "Rho" not in r["cards"] + r["rows"]


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
    for m in re.finditer(r"@media\s*(\([^)]*\))\s*\{", css):
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


@pytest.mark.parametrize("bp", ["max-width:900px", "max-width:768px", "max-width:480px", "min-width:1100px"])
def test_media_breakpoints_present(bp):
    assert any(m and bp in m.replace(" ", "") for _, _, m in _css_rules(_f41_css()))


def test_1100_breakpoint_exists_for_two_column_row():
    rules = _css_rules(_f41_css())
    assert any(m and "1100" in m and any(".rk-two" in s for s in sels) for sels, _, m in rules)


def test_payoff_grid_override_important_at_768():
    rules = _css_rules(_f41_css())
    hit = [b for sels, b, m in rules if m and "768" in m and any(s == "#page-risk #payoff-charts-grid" for s in sels)]
    assert hit and "grid-template-columns" in hit[0] and "!important" in hit[0]


def test_no_nowrap_on_instrument_rows_only_short_chips():
    rules = _css_rules(_f41_css())
    for sels, body, _ in rules:
        if "nowrap" in body.replace(" ", ""):
            assert sels == ["#page-risk .rk-chip"], sels
    row_rules = [b for sels, b, _ in rules if any(s.startswith(("#page-risk .rk-row", "#page-risk .rk-inst-list")) for s in sels)]
    assert row_rules and not any("nowrap" in b for b in row_rules)
    # JS markup has no inline nowrap either
    assert "nowrap" not in _GREEKS


def test_no_horizontal_scroll_guards():
    css = _f41_css().replace(" ", "")
    assert "#page-risk.rk-inst-list{max-height:360px;overflow-y:auto;overflow-x:hidden;}" in css
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
    assert {"delta", "gamma", "theta", "vega", "und", "exp", "hedge_type", "ann_vol_pct", "allocation_pct"} <= reads
    missing = {r for r in reads if r not in fields} - {"full", "type", "side"}
    assert not missing, missing


@pytest.mark.xfail(strict=True, reason="F41-QA-2 pre-existing contract gap: greeks.js reads g.full/g.type/g.side but GreekItemSchema has no such fields (JS falls back to und+hedge_type / '—')")
def test_contract_display_fields_exist_in_greek_item_schema():
    fields = _schema_fields("GreekItemSchema")
    reads = _js_g_reads(_GREEKS) | _js_g_reads(_STRESS)
    assert {"full", "type", "side"} <= reads
    assert {"full", "type", "side"} <= fields


def test_contract_missing_display_fields_have_js_fallbacks():
    assert "g.full ?? (g.und && g.hedge_type" in _GREEKS
    assert "g.type ?? '—'" in _GREEKS and "g.side ?? '—'" in _GREEKS


def test_contract_response_wires_greeks_list():
    assert "greeks" in _schema_fields("PortfolioAnalyticsResponse") or "greeks: list[GreekItemSchema]" in _SCHEMA.read_text(encoding="utf-8")
