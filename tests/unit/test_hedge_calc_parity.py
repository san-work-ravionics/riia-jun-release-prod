"""F39 Phase 3 — parity of dashboard/js/fno/hedge-calc.js with the pre-extraction maths.

hedge-calc.js holds the calculations extracted verbatim from portfolio-hedge.js
(_buildRows, _aggregates, _hedgedPL, _rowParams, ...) and equity_hedge.js
(_computeNShares, covered-call margin factors). The repo has no JS test runner, so this
test runs the module under node and compares against a Python port of the ORIGINAL
formulas (golden vectors). Skipped when node is not installed.
"""
from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_FNO_JS = _ROOT / "dashboard" / "js" / "fno"
_CALC = _FNO_JS / "hedge-calc.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def _node(tmp_path: Path, script: str) -> object:
    """Run `script` as an ES module with `calc` bound to hedge-calc.js; return JSON stdout."""
    mod = tmp_path / "hedge_calc.mjs"
    mod.write_text(_CALC.read_text(encoding="utf-8"), encoding="utf-8")
    runner = tmp_path / "run.mjs"
    runner.write_text(
        f"import * as calc from {json.dumps(mod.as_uri())};\n{script}\n", encoding="utf-8"
    )
    out = subprocess.run(
        ["node", str(runner)], capture_output=True, text=True, timeout=30, check=True
    )
    return json.loads(out.stdout)


# ── Python port of the original (pre-extraction) formulas ────────────────────
_ELIGIBLE = {
    "RELIANCE", "TATAMOTOR", "TCS", "INFY", "HDFCBANK", "WIPRO", "BAJFINANCE",
    "TATASTEEL", "SBIN", "ICICIBANK", "KOTAKBANK", "AXISBANK", "SUNPHARMA", "HCLTECH",
    "LT", "ONGC", "NTPC", "POWERGRID", "BPCL",
}


def _est_risk(r):
    a = abs(r or 0)
    return 1 if a < 0.3 else 2 if a < 0.7 else 3 if a < 1.2 else 4 if a < 2.0 else 5


def _hedge_type(i, region, alloc):
    if i in _ELIGIBLE:
        return "put_spread" if alloc >= 20 else "protective_put"
    return "ndx_proxy" if region in ("US", "EU") else "nifty_proxy"


def _row_params(t, risk, coverage):
    c = coverage / 100
    strike = -(12 - c * 10)
    proxy = t in ("ndx_proxy", "nifty_proxy")
    base = risk * 0.065
    cost = base * (0.28 if proxy else 0.40) * (0.4 + c * 0.6)
    return strike, cost, math.floor((30 + c * 50) * (0.85 if proxy else 1) + 0.5)  # JS Math.round


def _hedged_pl(m, tab, avg, cost):
    if tab == "pp":
        return max(m, avg) - cost
    if tab == "ps":
        lo, hi = avg, avg - 5
        if m > lo:
            return m - cost * 0.65
        if m > hi:
            return lo - cost * 0.65
        return m + (lo - hi) - cost * 0.65
    return max(min(m, 5), avg) - cost


_HOLDINGS = [
    {"instrument_id": "TCS", "allocation_pct": 30},
    {"instrument_id": "ASML", "allocation_pct": 45},
    {"instrument_id": "NIFTY", "allocation_pct": 25},
]
_INSTRUMENTS = {
    "TCS": {"region": "IN", "daily_return_pct": 0.5, "return_1y_pct": 12.0},
    "ASML": {"region": "EU", "daily_return_pct": 1.6, "return_1y_pct": -3.0},
    "NIFTY": {"region": "IN", "daily_return_pct": 0.1},
}
_API_HEDGE = {
    "holdings": [
        {
            "instrument_id": "ASML", "return_1y_pct": -3.0, "risk_score": 4,
            "hedge_type": "ndx_proxy", "strike_pct": -7.0, "strike_label": "-7% OTM",
            "cost_pct": 1.1, "protected_pct": 60,
        }
    ],
    "aggregate": {"max_dd_unhedged_pct": -31.5},
}


@pytest.mark.parametrize("tab", ["pp", "ps", "collar"])
@pytest.mark.parametrize("m", [-25, -20, -12.5, -7, -3, 0, 4, 5, 10, 15])
def test_hedged_pl_matches_original(tmp_path: Path, tab: str, m: float) -> None:
    avg, cost = -7.5, 0.95
    got = _node(tmp_path, f"console.log(JSON.stringify(calc.hedgedPL({m}, {json.dumps(tab)}, {avg}, {cost})));")
    assert math.isclose(got, _hedged_pl(m, tab, avg, cost), abs_tol=1e-12)


def test_moves_constants(tmp_path: Path) -> None:
    got = _node(tmp_path, "console.log(JSON.stringify([calc.PAYOFF_MOVES, calc.SCENARIO_MOVES]));")
    assert got[0] == list(range(-25, 16))
    assert got[1] == [-20, -10, 0, 10]


@pytest.mark.parametrize("coverage", [0, 25, 50, 80, 100])
def test_build_rows_and_aggregates_match_original(tmp_path: Path, coverage: int) -> None:
    script = f"""
const rows = calc.buildRows({json.dumps(_HOLDINGS)}, {json.dumps(_INSTRUMENTS)},
  {json.dumps(_API_HEDGE)}, new Set(['TCS','ASML','NIFTY']), {coverage});
const agg = calc.aggregates(rows, {json.dumps(_API_HEDGE)});
console.log(JSON.stringify({{rows, agg}}));
"""
    got = _node(tmp_path, script)
    rows = {r["id"]: r for r in got["rows"]}

    # ASML comes from the API row verbatim.
    assert rows["ASML"]["strikePct"] == -7.0 and rows["ASML"]["costPct"] == 1.1
    assert rows["ASML"]["type"] == "ndx_proxy" and rows["ASML"]["label"] == "NDX put proxy"

    # TCS / NIFTY fall back to the client-side estimate (original _rowParams path).
    for hid, alloc, inst in (("TCS", 30, _INSTRUMENTS["TCS"]), ("NIFTY", 25, _INSTRUMENTS["NIFTY"])):
        risk = _est_risk(inst["daily_return_pct"])
        t = _hedge_type(hid, inst["region"], alloc)
        strike, cost, prot = _row_params(t, risk, coverage)
        assert rows[hid]["type"] == t and rows[hid]["risk"] == risk
        assert math.isclose(rows[hid]["strikePct"], strike, abs_tol=1e-12)
        assert math.isclose(rows[hid]["costPct"], cost, abs_tol=1e-12)
        assert rows[hid]["protectedPct"] == prot

    tot_cost = sum(r["costPct"] * r["weight"] / 100 for r in got["rows"])
    avg_strike = sum(r["strikePct"] * r["weight"] / 100 for r in got["rows"])
    assert math.isclose(got["agg"]["totalCost"], tot_cost, abs_tol=1e-12)
    assert math.isclose(got["agg"]["avgStrike"], avg_strike, abs_tol=1e-12)
    assert math.isclose(got["agg"]["maxDdHedged"], max(avg_strike - tot_cost, -25), abs_tol=1e-12)
    assert got["agg"]["maxDdUnhedged"] == -31.5


def test_unchecked_and_empty_selection(tmp_path: Path) -> None:
    script = f"""
const rows = calc.buildRows({json.dumps(_HOLDINGS)}, {json.dumps(_INSTRUMENTS)}, null, new Set(['TCS']), 50);
console.log(JSON.stringify({{n: rows.length, empty: calc.aggregates([], null)}}));
"""
    got = _node(tmp_path, script)
    assert got["n"] == 1
    assert got["empty"] == {"totalCost": 0, "avgStrike": 0, "maxDdHedged": 0, "maxDdUnhedged": -22}


@pytest.mark.parametrize(
    "holding,inst,total,expected",
    [
        ({"shares": 7, "allocation_pct": 50}, {"close": 100}, 10000, 7),   # builder shares win
        ({"shares": None, "allocation_pct": 50}, {"close": 100}, 10000, 50),  # floor(5000/100)
        ({"shares": None, "allocation_pct": 50}, {"close": 3000}, 10000, 1),  # floor(1.66)=1
        ({"shares": None, "allocation_pct": 0.01}, {"close": 3000}, 10000, 1),  # floor 0 -> 1
        ({"shares": None, "allocation_pct": 50}, {"close": None}, 10000, 10),  # no price
        ({"shares": None, "allocation_pct": 50}, {"close": 100}, None, 10),  # no total
    ],
)
def test_compute_n_shares(tmp_path: Path, holding, inst, total, expected) -> None:
    got = _node(
        tmp_path,
        f"console.log(JSON.stringify(calc.computeNShares({json.dumps(holding)}, {json.dumps(inst)}, {json.dumps(total)})));",
    )
    assert got == expected


def test_margin_estimate_equals_inject_asml_formula(tmp_path: Path) -> None:
    """estimateEquityHedgeMargin == the injectAsmlToState formula in equity_hedge.js."""
    eq = {
        "hedge_scenarios": {
            "mild_bearish": {"max_value_eur": 12345.67, "total_premium_eur": 40.0},
            "strong_bearish": {"floor_value_eur": 900.0, "total_premium_eur": -55.25},
        }
    }
    got = _node(
        tmp_path,
        f"""const eq = {json.dumps(eq)};
console.log(JSON.stringify([calc.estimateEquityHedgeMargin(eq, 'call_sell'),
  calc.estimateEquityHedgeMargin(eq, 'put_buy'), calc.estimateEquityHedgeMargin(null, 'put_buy'),
  calc.coveredCallMargin(eq.hedge_scenarios.mild_bearish)]));""",
    )
    mv = 12345.67
    assert math.isclose(got[0], mv * 0.12 + mv * 0.08, rel_tol=1e-12)  # covered call
    assert math.isclose(got[1], 55.25, rel_tol=1e-12)  # long put = premium paid
    assert got[2] is None
    assert math.isclose(got[3]["span"], mv * 0.12) and math.isclose(got[3]["exposure"], mv * 0.08)


def test_old_pages_import_shared_calc_and_do_not_redefine_it() -> None:
    ph = (_FNO_JS / "portfolio-hedge.js").read_text(encoding="utf-8")
    assert "from './hedge-calc.js'" in ph
    for removed in ("function _hedgedPL", "function _rowParams", "function _hedgeType", "_FNO_ELIGIBLE"):
        assert removed not in ph
    # equity_hedge.js is deleted in F39 Phase 4 Tier B: tolerate either state (exists-guarded).
    eh_path = _FNO_JS / "equity_hedge.js"
    if eh_path.exists():
        eh = eh_path.read_text(encoding="utf-8")
        assert "from './hedge-calc.js'" in eh
        assert "* 0.12" not in eh and "* 0.08" not in eh  # factors live only in hedge-calc.js
