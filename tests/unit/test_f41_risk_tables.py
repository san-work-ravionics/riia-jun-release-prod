"""Risk page: Net Greeks and Stress scenarios render as tables (not card tiles)."""
from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_HTML = (_ROOT / "dashboard" / "fno.html").read_text()
_GREEKS = (_ROOT / "dashboard" / "js" / "fno" / "greeks.js").read_text()
_STRESS = (_ROOT / "dashboard" / "js" / "fno" / "stress.js").read_text()


def test_net_greeks_is_a_table_with_four_greek_columns():
    assert 'class="rk-tbl rk-net-tbl"' in _GREEKS
    for sym in ("Δ", "Γ", "Θ", "V"):
        assert f"th('{sym}'" in _GREEKS
    assert "rk-ug-row" in _GREEKS and "rk-gk" not in _GREEKS


def test_stress_is_a_table_move_level_pnl():
    assert 'class="rk-tbl rk-stress-tbl"' in _STRESS
    assert "Market move" in _STRESS and "Reference level" in _STRESS and "P&amp;L" in _STRESS
    assert "scenario-card" not in _STRESS


def test_stress_row_container_keeps_id_once_and_is_not_a_grid():
    assert _HTML.count('id="stress-row"') == 1
    assert 'class="rk-tbl-wrap" id="stress-row"' in _HTML
    assert 'class="scenario-row" id="stress-row"' not in _HTML
    assert _HTML.count('id="greeks-all-grid"') == 1


def test_table_css_scoped_to_page_risk_and_no_nowrap():
    block = _HTML[_HTML.index("/* ═══ F41 Risk page"): _HTML.index("/* ═══ end F41 Risk page ═══ */")]
    sels = [l.split("{")[0] for l in block.splitlines() if l.startswith("#page-risk .rk-tbl")]
    assert sels and all(x.startswith("#page-risk") for x in sels)
    tbl_rules = "\n".join(l for l in block.splitlines() if ".rk-tbl" in l)
    assert "nowrap" not in tbl_rules
    assert re.search(r"#page-risk \.rk-tbl\{width:100%", block)
