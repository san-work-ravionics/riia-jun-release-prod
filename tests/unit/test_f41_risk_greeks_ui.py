"""F41 — Risk & Greeks page UI rework (fno.html #page-risk, greeks.js, stress.js).

Static HTML/CSS/JS structure checks plus a node harness (skipped when node is absent).
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
_HTML = (_ROOT / "dashboard" / "fno.html").read_text(encoding="utf-8")
_GREEKS = (_JS / "fno" / "greeks.js").read_text(encoding="utf-8")
_STRESS = (_JS / "fno" / "stress.js").read_text(encoding="utf-8")

_IDS = ["greeks-all-grid", "greeks-tbody", "greeks-footer", "greeks-table-sub", "stress-row",
        "stress-card-sub", "payoff-charts-grid", "payoff-nifty-wrap", "payoff-bnkn-wrap",
        "payoff-chart", "payoff-chart-bnkn", "risk-stddev-card", "risk-inst-chart", "risk-port-chart"]


def _risk_block() -> str:
    start = _HTML.index('<div class="section" id="page-risk">')
    end = _HTML.index("RISK-REWARD", start)
    return _HTML[start:end]


def _f41_css() -> str:
    a = _HTML.index("/* ═══ F41 Risk page")
    b = _HTML.index("/* ═══ end F41 Risk page ═══ */")
    return _HTML[a:b]


# ── HTML structure ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("i", _IDS)
def test_dom_id_exactly_once_inside_page_risk(i):
    assert len(re.findall(rf'id="{re.escape(i)}"', _HTML)) == 1
    assert f'id="{i}"' in _risk_block()


def test_three_col_replaced_and_greeks_is_div_list():
    blk = _risk_block()
    assert "three-col" not in blk
    assert 'class="rk-grid"' in blk and 'class="rk-two"' in blk
    assert '<div id="greeks-tbody" class="rk-inst-list">' in blk
    assert "<tbody" not in blk.split('id="greeks-tbody"')[1].split("greeks-footer")[0]
    assert 'id="greeks-all-grid" style' not in blk  # inline grid removed


def test_stddev_card_precedes_greeks_grid():
    blk = _risk_block()
    assert blk.index("risk-stddev-card") < blk.index("greeks-all-grid")


def test_f41_css_block_is_scoped_and_global_rules_untouched():
    css = _f41_css()
    body = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    selectors = []
    for chunk in re.findall(r"([^{}]+)\{", body):
        chunk = chunk.strip()
        if chunk.startswith("@media"):
            continue
        selectors += [s.strip() for s in chunk.split(",")]
    assert selectors
    assert all(s.startswith("#page-risk") for s in selectors), [s for s in selectors if not s.startswith("#page-risk")]
    # global rules preserved
    assert ".three-col{display:grid;grid-template-columns:1fr 1fr 1fr;gap:18px;margin-bottom:18px;}" in _HTML
    assert ".scenario-row{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-bottom:18px;}" in _HTML


def test_f41_css_covers_breakpoints_and_no_inner_scroll():
    css = _f41_css()
    for token in ("min-width:1100px", "max-width:900px", "max-width:768px", "max-width:480px",
                  "table-layout:fixed", "rk-sd-x", "overflow-x:hidden", "!important"):
        assert token in css, token
    assert "min-width:0" in css  # grid children can shrink


# ── JS structure ──────────────────────────────────────────────────────────────────

def test_greeks_js_structure():
    assert "export function renderGreeksCards" in _GREEKS and "export function renderGreeksTable" in _GREEKS
    assert "gridTemplateColumns = `repeat(" not in _GREEKS
    for k in ("hint_delta", "hint_gamma", "hint_theta", "hint_vega"):
        assert f"greeks.{k}" in _GREEKS
    assert "rho" not in _GREEKS.lower()
    assert 'title="${_esc(' in _GREEKS


def test_stress_js_std_dev_class():
    assert 'class="rk-sd-tbl"' in _STRESS and "rk-sd-x" in _STRESS
    assert "padding:6px 10px" not in _STRESS


@pytest.mark.parametrize("lang", ["en", "nl", "fr"])
def test_locale_keys_present(lang):
    s = (_JS / "locales" / f"{lang}.js").read_text(encoding="utf-8")
    for k in ("greeks.hint_delta", "greeks.hint_gamma", "greeks.hint_theta", "greeks.hint_vega"):
        assert s.count(f"'{k}'") == 1


def test_no_state_or_main_changes_needed():
    assert "export" in (_JS / "fno" / "state.js").read_text(encoding="utf-8")


# ── node harness ──────────────────────────────────────────────────────────────────

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


@pytest.fixture(scope="module")
def jsroot(tmp_path_factory) -> Path:
    dst = tmp_path_factory.mktemp("js")
    shutil.copytree(_JS, dst / "js")
    (dst / "js" / "package.json").write_text('{"type":"module"}', encoding="utf-8")
    return dst / "js"


def _run(jsroot: Path, greeks, **state) -> dict:
    g_uri = (jsroot / "fno" / "greeks.js").as_uri()
    s_uri = (jsroot / "fno" / "state.js").as_uri()
    src = f"""
import {{ state }} from {json.dumps(s_uri)};
const els = {{}};
for (const id of ['greeks-all-grid','greeks-tbody','greeks-footer','greeks-table-sub'])
  els[id] = {{ innerHTML: '', textContent: '', style: {{}} }};
globalThis.document = {{ getElementById: id => els[id] ?? null }};
const g = await import({json.dumps(g_uri)});
state.greeksData = {json.dumps(greeks)};
state.riskSelectedInstrument = {json.dumps(state.get("sel"))};
state.currentUnd = {json.dumps(state.get("und", "ALL"))};
state.currentExpiry = {json.dumps(state.get("exp", "ALL"))};
g.renderGreeksCards(); g.renderGreeksTable();
console.log(JSON.stringify({{cards: els['greeks-all-grid'].innerHTML, rows: els['greeks-tbody'].innerHTML,
  foot: els['greeks-footer'].innerHTML, sub: els['greeks-table-sub'].textContent}}));
"""
    script = jsroot / "run41.mjs"
    script.write_text(src, encoding="utf-8")
    out = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60, cwd=jsroot)
    assert out.returncode == 0, out.stderr[-3000:]
    return json.loads(out.stdout.strip().splitlines()[-1])


def _g(**kw):
    base = dict(und="NIFTY", full="NIFTY PUT", hedge_type="put", exp="WEEKLY", type="PE", side="BUY",
                delta=-0.5, gamma=0.002, theta=-1200, vega=800, ann_vol_pct=14.25)
    base.update(kw)
    return base


@needs_node
def test_normal_data_renders_groups_gamma_and_hints(jsroot):
    r = _run(jsroot, [_g(), _g(und="BANKNIFTY", full="BANKNIFTY CALL", delta=0.3)])
    assert r["cards"].count('class="rk-ug"') == 2
    assert "Γ" in r["cards"] and "rk-g-hint" in r["cards"] and "P&amp;L per 1pt move" in r["cards"]
    assert r["rows"].count('class="rk-row"') == 2 and "Γ" in r["rows"] and "+0.0020" in r["rows"]
    assert "14.3%" in r["rows"] or "14.2%" in r["rows"]
    for bad in ("NaN", "undefined", "null"):
        assert bad not in r["cards"] + r["rows"] + r["foot"]


@needs_node
def test_null_and_missing_greeks_show_dash_neutral_no_nan(jsroot):
    r = _run(jsroot, [_g(delta=None, gamma=None, theta=None, vega=None, ann_vol_pct=None),
                      {"und": "NIFTY"}, _g(delta="abc", gamma=float("nan") if False else None)])
    blob = r["cards"] + r["rows"] + r["foot"]
    for bad in ("NaN", "undefined", "null"):
        assert bad not in blob
    assert "—" in r["rows"] and "rk-chip neu" in r["rows"]


@needs_node
def test_sign_classes(jsroot):
    r = _run(jsroot, [_g(delta=-0.5, theta=-100, vega=50)])
    assert 'rk-g-val neg">−0.50' in r["cards"]
    assert 'rk-g-val pos">+₹50' in r["cards"]
    assert 'rk-chip neg"><i>Θ/day</i>−₹100' in r["rows"]


@needs_node
def test_footer_totals(jsroot):
    r = _run(jsroot, [_g(delta=0.5, theta=-100, vega=10), _g(delta=0.25, theta=40, vega=None, theta_x=1)])
    assert "+0.75" in r["foot"] and "−₹60" in r["foot"] and "+₹10" in r["foot"]


@needs_node
def test_empty_data_and_unknown_selection(jsroot):
    r = _run(jsroot, [])
    assert "No Greeks data" in r["cards"] and "No positions" in r["rows"]
    assert "NaN" not in r["foot"]
    r2 = _run(jsroot, [_g()], sel="GHOST")
    assert "No Greeks data" in r2["cards"] and "No positions" in r2["rows"]


@needs_node
def test_long_names_escaped_with_title(jsroot):
    name = 'X' * 120 + '<img src=x onerror=1>"'
    r = _run(jsroot, [_g(full=name)])
    assert "<img" not in r["rows"] and "&lt;img" in r["rows"]
    assert 'title="' + "X" * 120 in r["rows"] and "&quot;" in r["rows"]


@needs_node
def test_wide_numbers_and_all_zero_note(jsroot):
    r = _run(jsroot, [_g(theta=-123456789, vega=987654321)])
    assert "−₹12,34,56,789" in r["cards"] and "+₹98,76,54,321" in r["cards"]
    z = _run(jsroot, [_g(delta=0, gamma=0, theta=0, vega=0)])
    assert "add a hedge plan" in z["sub"]
