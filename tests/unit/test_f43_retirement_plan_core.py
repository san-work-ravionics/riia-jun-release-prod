"""F43 Phase 1 — core.retirement_plan parity with the approved mock rev 39.

The golden fixture (tests/fixtures/what_i_need_golden.json) is the output of the mock's
own calc() (dashboard/js/investgame-app/what-i-need.js @ b1a9b4c), produced by
tests/fixtures/what_i_need_src/gen.js under node.  Every field of every scenario is
compared: ints / nulls / bools exactly, floats with rel 1e-9 / abs 1e-6 and a hard
ceiling of EUR 0.01.
"""
from __future__ import annotations

import ast
import copy
import json
import math
from pathlib import Path

import pytest

from rita.core import retirement_plan as core
from rita.core.retirement_plan import MAX_AGE, calc, fv_factor, simulate, to_params, validate_plan
from rita.schemas.retirement_plan import RetirementPlanInputs, RetirementPlanResult

_FIXTURE = Path(__file__).parent.parent / "fixtures" / "what_i_need_golden.json"
GOLDEN = json.loads(_FIXTURE.read_text(encoding="utf-8"))
SCENARIOS = sorted(GOLDEN["scenarios"])
DEFAULTS = GOLDEN["scenarios"]["defaults"]["input"]


def _result(inp: dict, start_year: int | None = None) -> dict:
    raw = RetirementPlanInputs.model_validate(inp).model_dump()
    assert validate_plan(raw) is None
    r = calc(to_params(raw), start_year if start_year is not None else GOLDEN["start_year"])
    return RetirementPlanResult.model_validate(r, from_attributes=True).model_dump(by_alias=True)


def _walk(golden, actual, path: str, stats: dict) -> None:
    if isinstance(golden, dict):
        for k, v in golden.items():
            assert k in actual, f"{path}.{k} missing"
            _walk(v, actual[k], f"{path}.{k}", stats)
        if "off" not in golden and "off" in actual and "age" in golden and "share" in golden:
            assert actual["off"] is False, f"{path}.off"
    elif isinstance(golden, list):
        assert isinstance(actual, list) and len(actual) == len(golden), f"{path} length"
        for i, (g, a) in enumerate(zip(golden, actual)):
            _walk(g, a, f"{path}[{i}]", stats)
    elif golden is None or isinstance(golden, (bool, str)):
        assert actual == golden, f"{path}: {actual!r} != {golden!r}"
    elif isinstance(golden, int) and isinstance(actual, int):
        assert actual == golden, f"{path}: {actual} != {golden}"
    else:
        diff = abs(float(actual) - float(golden))
        stats["max"] = max(stats["max"], diff)
        stats["n"] += 1
        assert diff <= 0.01, f"{path}: hard ceiling {diff}"
        assert math.isclose(actual, golden, rel_tol=1e-9, abs_tol=1e-6), f"{path}: {actual} != {golden}"


@pytest.mark.parametrize("name", SCENARIOS)
def test_golden_parity_all_fields(name):
    sc = GOLDEN["scenarios"][name]
    stats = {"max": 0.0, "n": 0}
    _walk(sc["output"], _result(sc["input"]), name, stats)
    assert stats["n"] > 100


def test_fixture_has_twelve_scenarios_and_constants():
    assert len(SCENARIOS) == 12
    assert GOLDEN["max_age"] == MAX_AGE == 120
    assert core.AGE_PANELS == (55, 60, 65, 70, 75, 80, 85)


def test_headline_numbers_defaults():
    r = _result(DEFAULTS)
    assert r["byAge"][0]["age"] == 55 and abs(r["byAge"][0]["monthly"] - 2556.959) < 0.01
    assert r["byAge"][3]["age"] == 70 and abs(r["byAge"][3]["monthly"] - 7703.30) < 0.01
    assert abs(r["byAge"][3]["portfolio"] - 1733258.3) < 0.1
    assert r["withInvesting"]["savingsOut"] == 55
    assert r["withoutInvesting"]["savingsOut"] == 59
    assert r["withInvesting"]["portfolioOut"] == 119
    assert r["withoutInvesting"]["portfolioOut"] is None


def test_events_order_and_kinds():
    r = _result(DEFAULTS)
    by_age = {x["age"]: x["events"] for x in r["withInvesting"]["points"]}
    assert [e["kind"] for e in by_age[50]] == ["saving"]
    assert [e["kind"] for e in by_age[55]] == ["saving", "expense"]
    assert [e["kind"] for e in by_age[60]] == ["house", "saving", "expense"]
    assert by_age[65] == []  # amount 0 → no event
    assert by_age[60][0]["amount"] == pytest.approx(r["houseRelease"])


def test_same_house_has_no_house_event():
    inp = {**DEFAULTS, "h2Mode": "same"}
    r = _result(inp)
    assert r["houseRelease"] == 0.0
    assert all(e["kind"] != "house" for x in r["withInvesting"]["points"] for e in x["events"])


def test_no_invest_portfolio_never_runs_out():
    r = _result(GOLDEN["scenarios"]["no_invest"]["input"])
    assert r["withInvesting"]["portfolioOut"] is None


def test_end_70_panels_off():
    r = _result(GOLDEN["scenarios"]["end_70"]["input"])
    off = {c["age"]: c["off"] for c in r["byAge"]}
    assert off == {55: False, 60: False, 65: False, 70: False, 75: True, 80: True, 85: True}
    cell = r["byAge"][4]
    assert cell["monthly"] is None and cell["share"] is None
    assert r["withInvesting"]["portfolioOut"] is not None


def test_start_year_only_labels_years():
    a = _result(DEFAULTS, start_year=2026)
    b = _result(DEFAULTS, start_year=2031)
    assert [y["year"] - 5 for y in b["years"]] == [y["year"] for y in a["years"]]
    assert a["years"][0]["year"] == 2026 + 55 - 35
    assert [y["monthly"] for y in a["years"]] == [y["monthly"] for y in b["years"]]


def test_fv_factor_zero_rate_is_k():
    assert fv_factor(0.0, 240) == 240.0
    assert fv_factor(0.07, 12) == pytest.approx(12.0 * (1 + 0.07 / 2), rel=0.01)


def test_simulate_invest_false_has_no_portfolio():
    p = to_params(RetirementPlanInputs.model_validate(DEFAULTS).model_dump())
    s = simulate(p, p.assets, 0.0, invest=False)
    assert s.portfolio_out is None
    assert all(x.portfolio == 0.0 for x in s.points)
    assert s.points[-1].age == p.end


# ── Validation: mock order and messages, then the backend guards ──────────────


def _raw(**kw) -> dict:
    d = RetirementPlanInputs.model_validate(DEFAULTS).model_dump()
    d.update(kw)
    return d


def _ev(raw: dict, group: str, i: int, **kw) -> dict:
    raw = copy.deepcopy(raw)
    raw[group][i].update(kw)
    return raw


@pytest.mark.parametrize("raw,msg", [
    (_raw(need=None), "Fill in every field"),
    (_raw(alt_rate=None), "Fill in every field"),
    (_ev(_raw(), "sv", 0, age=None), "Fill in every one time event (use 0 for none)"),
    (_ev(_raw(), "bx", 2, amt=None), "Fill in every one time event (use 0 for none)"),
    (_ev(_raw(), "bx", 2, amt=-1), "One time amounts must be 0 or more (the sign is fixed)"),
    (_ev(_raw(), "sv", 0, age=30), "One time event age must be from current age on"),
    (_raw(ret=35), "Retirement must be after current age"),
    (_raw(end=55), "Plan until must be after retirement"),
    (_raw(h_sell=35), "House value-until age must be after current age"),
    (_raw(need=0), "Check monthly need and tax %"),
    (_raw(tax=1), "Check monthly need and tax %"),
    (_raw(partial=1.01), "Partial profit must be 0–100%"),
    (_raw(exit=54), "Exit age must be from retirement age on"),
    (_raw(eq_monthly=-1), "Monthly investments must be 0 or more"),
    (_raw(h_tax=1), "Check house values and tax %"),
    (_raw(h2_price=-5), "Check house values and tax %"),
    (_raw(ret=55.5), "Ages must be whole years"),
    (_raw(end=121), "Plan until must be at most 120"),
    (_raw(now=-1e9), "Ages must be between 0 and 120"),
    (_raw(h_sell=10_000), "Ages must be between 0 and 120"),
    (_raw(infl=-1), "Rates must be between −100% and 100%"),
    (_raw(idx_rate=1.5), "Rates must be between −100% and 100%"),
    (_raw(need=2e9), "Amounts must be at most €1,000,000,000"),
    (_ev(_raw(), "sv", 1, amt=5e9), "Amounts must be at most €1,000,000,000"),
    (_raw(infl=-0.9999999999), "Inflation must be between −50% and 100%"),  # C2
    (_raw(infl=-0.51), "Inflation must be between −50% and 100%"),
    (_raw(need=1e-300, infl=-0.5, now=0, end=120, ret=60, exit=60, h_sell=60), "Check monthly need and tax %"),  # underflow
])
def test_validation_messages(raw, msg):
    assert validate_plan(raw) == msg


def test_validation_order_first_failure_wins():
    # empty field beats every later check
    assert validate_plan(_raw(need=None, ret=10)) == "Fill in every field"
    # retirement check comes before the tax check
    assert validate_plan(_raw(ret=35, tax=2)) == "Retirement must be after current age"
    # mock checks come before the appended guards
    assert validate_plan(_raw(end=200, tax=2)) == "Check monthly need and tax %"


def test_defaults_are_valid():
    assert validate_plan(_raw()) is None


def test_core_uses_no_builtin_sum_or_fsum():
    src = Path(core.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
            assert name not in ("sum", "fsum"), f"builtin {name}() at line {node.lineno}"


def test_c2_inflation_floor_keeps_need_positive():
    """C2 regression: infl ≈ −100% must be rejected, never reach a divide by zero."""
    assert validate_plan(_raw(infl=-0.9999999999)) == "Inflation must be between −50% and 100%"
    # the floor itself is accepted and every inflated need stays > 0
    raw = _raw(infl=-0.5)
    assert validate_plan(raw) is None
    r = calc(to_params(raw), 2026)
    assert all(c.need > 0 for c in r.by_age if not c.off)
