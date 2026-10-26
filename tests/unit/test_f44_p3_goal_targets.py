"""F44 P3 — annual targets and the SL guard (``core/goal_targets.py``; design A8 + R3 N2).

DoD: annual mechanics tested — g, r′, r′_eff incl. a partial first year and the year reset;
Dec 31 → ``year_end``; guard order; the guard limit comes from settings (no literal).
"""
from __future__ import annotations

from datetime import date

import pytest

from rita.config import get_settings
from rita.core.goal_targets import (
    RequiredReturn,
    blend_goal_return,
    decide_sl_response,
    required_return,
    year_fraction,
)

R = 0.07675


def test_blend_goal_return_weighted_by_monthly():
    # Europe preset: idx 1000@7%, eq 700@10%, com 150@4%, alt 150@5% → 7.675 %
    assert blend_goal_return([(1000, 0.07), (700, 0.10), (150, 0.04), (150, 0.05)]) == \
        pytest.approx(0.07675)
    assert blend_goal_return([(0, 0.07), (None, 0.1)]) is None
    assert blend_goal_return([(100, None), (100, 0.1)]) == pytest.approx(0.05)


def test_blend_matches_the_three_location_presets():
    want = {"europe": 0.07675, "india": 0.117, "us": 0.0754}
    for loc, preset in get_settings().retirement_plan.locations.items():
        d = preset.defaults
        pairs = [(d[f"{c}Monthly"], d[f"{c}Rate"]) for c in ("idx", "eq", "com", "alt")]
        assert blend_goal_return(pairs) == pytest.approx(want[loc], abs=1e-9)


def test_year_fraction_start_inclusive():
    assert year_fraction(date(2026, 1, 1), date(2026, 12, 31)) == 1.0
    assert year_fraction(date(2024, 7, 1), date(2024, 12, 31)) == pytest.approx(184 / 366)


def test_full_year_rest_of_year_is_the_users_formula():
    res = required_return(R, -0.05, date(2026, 6, 30), date(2026, 1, 1))
    assert res.year_fraction == 1.0
    assert res.rest_of_year_return == pytest.approx((1 + R) / (1 - 0.05) - 1)
    phi = (date(2026, 12, 31) - date(2026, 6, 30)).days / 365
    assert res.remaining_fraction == pytest.approx(phi)
    assert res.required_return == pytest.approx(((1 + R) / 0.95) ** (1 / phi) - 1)
    assert res.effective_return == res.required_return > R


def test_r_prime_equals_r_at_year_start_exactly():
    for s in (date(2026, 1, 1), date(2026, 3, 17), date(2024, 2, 29)):
        res = required_return(R, 0.0, date.fromordinal(s.toordinal() - 1), s)
        assert res.required_return == R
        assert res.rest_of_year_return == pytest.approx((1 + R) ** res.year_fraction - 1)


def test_partial_first_year_target_is_pro_rata():
    s = date(2026, 7, 1)
    res = required_return(R, 0.02, date(2026, 9, 30), s)
    f = (date(2026, 12, 31) - s).days + 1
    assert res.year_fraction == pytest.approx(f / 365)
    assert res.rest_of_year_return == pytest.approx((1 + R) ** (f / 365) / 1.02 - 1)


def test_ahead_of_plan_gives_r_prime_below_r_and_effective_r():
    res = required_return(R, 0.09, date(2026, 8, 31), date(2026, 1, 1))
    assert res.required_return < R and res.effective_return == R


def test_dec31_is_year_end_not_an_error():
    res = required_return(R, -0.1, date(2026, 12, 31), date(2026, 1, 1))
    assert res.year_end and res.required_return is None and res.effective_return is None
    assert decide_sl_response(res, 1.0, 0, 2).reason == "year_end"


def test_year_reset_new_year_starts_from_r():
    # Jan 1 of the next year: fresh target, count reset is the caller's (year_start moves on)
    res = required_return(R, 0.0, date(2026, 12, 31), date(2027, 1, 1))
    assert res.required_return == R and not res.year_end


@pytest.mark.parametrize("ytd,as_of,s", [
    (-1.0, date(2026, 5, 1), date(2026, 1, 1)),
    (-1.5, date(2026, 5, 1), date(2026, 1, 1)),
    (0.0, date(2025, 12, 30), date(2026, 1, 1)),
    (0.0, date(2027, 1, 1), date(2026, 1, 1)),
])
def test_invalid_inputs_raise(ytd, as_of, s):
    with pytest.raises(ValueError):
        required_return(R, ytd, as_of, s)


def _req(r_prime, year_end=False) -> RequiredReturn:
    return RequiredReturn(R, -0.05, 1.0, 0.5, 0.1, None if year_end else r_prime,
                          None if year_end else max(r_prime, R), year_end)


def test_guard_order():
    # (1) year end first — even when the count is spent and r′ is unknown
    assert decide_sl_response(_req(0.2, year_end=True), 0.1, 5, 2).reason == "year_end"
    # (2) on track before the count: a portfolio ahead of plan never spends a re-selection
    d = decide_sl_response(_req(0.05), 0.1, 2, 2)
    assert (d.action, d.reason) == ("on_track", "on_track")
    # (3) count
    assert decide_sl_response(_req(0.09), 0.5, 2, 2).reason == "count"
    # (4) cap (fit cap)
    assert decide_sl_response(_req(0.30), 0.25, 0, 2).reason == "cap"
    # (5) solve
    assert decide_sl_response(_req(0.12), 0.25, 1, 2).action == "solve"
    assert decide_sl_response(_req(0.25), 0.25, 1, 2).action == "solve"   # = cap is reachable


def test_guard_limit_comes_from_settings():
    assert get_settings().goal_selection.max_reselections_per_year == 2
    assert decide_sl_response(_req(0.12), 0.25, 2, 3).action == "solve"
