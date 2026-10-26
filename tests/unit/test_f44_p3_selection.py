"""F44 P3 — selection over model sleeves (``core/goal_selection.py``; rev 1 A4/A5, R3 N1/N2, N9).

DoD items covered: least-risk objective (min σ s.t. fit μ ≥ r), fit/test separation (no test bar
in the fit; ``meets_goal`` / caps on test), union calendar + annual drift + calendar-time μ +
bars-per-year σ, Sharpe on the instruments' own rf, integer rounding + bounded repair, N9
fallback re-checked, τ rule + tie-break, deterministic output.
"""
from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

import rita.core.goal_selection as gsel
from rita.core.goal_selection import (
    build_matrix,
    metrics,
    portfolio_path,
    repair,
    round_weights,
    select,
    windows,
)
from rita.core.performance import TRADING_DAYS, sharpe_ratio

from .f44_p3_helpers import SPLIT, fixed_run

AS_OF = date(2026, 6, 30)
FIT, TEST = windows(SPLIT, AS_OF)
DATES = pd.bdate_range("2023-01-02", AS_OF)


def _sleeve(seed, mu, vol, dates=DATES):
    """Deterministic sleeve: drift ``mu`` + a ``vol``-sized oscillation (phase/period by seed)."""
    t = np.arange(len(dates))
    return mu + vol * math.sqrt(2) * np.sin(t / (2.0 + seed) + seed)


def _runs(spec: dict, tol="medium", tol_mdd=-0.15, rf=0.0):
    return {k: fixed_run(k, r, d, tolerance=tol, tolerance_mdd=tol_mdd, rf_daily=rf)
            for k, (r, d) in spec.items()}


def _two_assets(tol="medium", tol_mdd=-0.15):
    return _runs({"A": (_sleeve(1, 0.00015, 0.002), DATES), "B": (_sleeve(2, 0.0009, 0.015), DATES)},
                 tol, tol_mdd)


# ── matrix mechanics ───────────────────────────────────────────────────────────

def test_union_calendar_fills_zero_on_closed_days():
    d_c = DATES.delete([3, 10])
    runs = _runs({"A": (np.full(len(DATES), 0.001), DATES), "C": (np.full(len(d_c), 0.002), d_c)})
    m = build_matrix(runs, FIT)
    assert m.instruments == ["A", "C"]
    fit_dates = DATES[(DATES >= "2023-01-01") & (DATES <= "2024-12-31")]
    assert list(m.dates) == list(fit_dates)                    # no row dropped
    # C's growth is flat over its two closed days
    assert m.growth[3, 1] == pytest.approx(m.growth[2, 1])


def test_bought_at_year_start_and_drifting():
    d = pd.DatetimeIndex(["2023-06-01", "2023-12-29", "2024-06-03", "2024-12-31"])
    a = [0.10, 0.0, 0.0, 0.0]          # A +10 % in 2023, flat in 2024
    b = [0.0, 0.0, 0.20, 0.0]          # B flat in 2023, +20 % in 2024
    m = build_matrix(_runs({"A": (a, d), "B": (b, d)}), FIT)
    V = portfolio_path(m, np.array([0.5, 0.5]))
    assert V[1] == pytest.approx(1.05)                         # drift inside 2023
    assert V[-1] == pytest.approx(1.05 * 1.10)                 # re-bought 50/50 on Jan 1 2024
    # inside a year the weights drift: +50 % then −50 % on A at 50/50 is not daily-rebalanced
    d2 = pd.DatetimeIndex(["2023-03-01", "2023-04-03"])
    m2 = build_matrix(_runs({"A": ([0.5, -0.5], d2), "B": ([0.0, 0.0], d2)}), FIT)
    v2 = portfolio_path(m2, np.array([0.5, 0.5]))
    assert v2[-1] == pytest.approx(0.5 * 1.5 * 0.5 + 0.5)       # drift, not 1.25*0.75


def test_calendar_time_mu_and_bars_per_year_sigma():
    runs = _two_assets()
    m = build_matrix(runs, FIT)
    w = np.array([0.3, 0.7])
    mt = metrics(m, w)
    V = np.concatenate([[1.0], portfolio_path(m, w)])
    days = (m.dates[-1].date() - SPLIT.train_end).days
    assert mt.ret == pytest.approx(V[-1] ** (365.25 / days) - 1)
    R = np.diff(V) / V[:-1]
    assert mt.vol == pytest.approx(np.std(R) * math.sqrt(len(R) / (days / 365.25)))
    assert mt.mdd == pytest.approx(float(np.min(V / np.maximum.accumulate(V) - 1)))


def test_sharpe_uses_the_instruments_own_rf():
    runs = {"A": fixed_run("A", _sleeve(1, 0.0003, 0.004), DATES, rf_daily=0.035 / 252),
            "B": fixed_run("B", _sleeve(2, 0.0006, 0.01), DATES, rf_daily=0.07 / 252)}
    m = build_matrix(runs, TEST)
    w = np.array([0.25, 0.75])
    mt = metrics(m, w)
    assert mt.rf_annual == pytest.approx(0.25 * 0.035 + 0.75 * 0.07)
    V = np.concatenate([[1.0], portfolio_path(m, w)])
    assert mt.sharpe == pytest.approx(sharpe_ratio(np.diff(V) / V[:-1], mt.rf_annual))
    assert TRADING_DAYS == 252


# ── integer weights ────────────────────────────────────────────────────────────

def test_round_weights_largest_remainder_ties_by_id():
    assert list(round_weights(np.array([1 / 3] * 3), ["B", "A", "C"])) == [33, 34, 33]
    assert list(round_weights(np.array([0.125, 0.875]), ["Z", "A"])) == [12, 88]
    assert round_weights(np.array([0.2, 0.3, 0.5]), ["A", "B", "C"]).sum() == 100


def test_repair_moves_low_to_high_mu_and_is_bounded():
    runs = _two_assets()
    m = build_matrix(runs, FIT)
    mu = np.array([metrics(m, np.eye(2)[i]).ret for i in range(2)])
    target = metrics(m, np.array([0.6, 0.4])).ret
    w, ok = repair(m, np.array([100, 0]), target, mu)
    assert ok and w.sum() == 100 and 0 < w[1] <= 100
    assert metrics(m, w / 100).ret >= target
    assert metrics(m, (w + np.array([1, -1])) / 100).ret < target    # minimal move count
    # unreachable target: stops after at most 100 moves, infeasible
    w2, ok2 = repair(m, np.array([100, 0]), 5.0, mu)
    assert not ok2 and list(w2) == [0, 100]
    # equal μ: no move helps
    _w3, ok3 = repair(m, np.array([50, 50]), 5.0, np.array([0.1, 0.1]))
    assert not ok3


# ── the selection ──────────────────────────────────────────────────────────────

def _brute_min_vol(m, target):
    best = math.inf
    for b in range(101):
        mt = metrics(m, np.array([100 - b, b]) / 100)
        if mt.ret >= target:
            best = min(best, mt.vol)
    return best


def test_least_risk_mix_meeting_the_target_on_fit():
    runs = _two_assets()
    m = build_matrix(runs, FIT)
    mu_a, mu_b = (metrics(m, np.eye(2)[i]).ret for i in range(2))
    target = mu_a + 0.4 * (mu_b - mu_a)
    sel = select({"medium": runs}, target, SPLIT, AS_OF)
    assert sel.tolerance == "medium" and sel.solver == "slsqp"
    assert sum(sel.weights.values()) == 100 and set(sel.weights) == {"A", "B"}
    assert sel.fit.ret >= target
    assert sel.fit.vol <= _brute_min_vol(m, target) * 1.005       # least risk (integer grid)
    # not profit maximisation: the cap mix returns more
    assert sel.cap_fit > sel.fit.ret


def test_no_test_bar_reaches_the_fit():
    base = _two_assets()
    test_mask = [d >= SPLIT.backtest_start for d in base["B"].dates]
    altered = {k: fixed_run(k, [(-0.01 if t else r) for r, t in zip(v.daily_returns, test_mask)],
                            v.dates) for k, v in base.items()}
    target = 0.05
    a = select({"medium": base}, target, SPLIT, AS_OF)
    b = select({"medium": altered}, target, SPLIT, AS_OF)
    assert a.weights == b.weights and a.fit == b.fit and a.cap_fit == b.cap_fit
    assert a.test != b.test


def test_meets_goal_is_judged_on_test():
    # B great on fit, bad on test → fit-feasible proposal, meets_goal false, test gap
    fit_mask = np.array([d < pd.Timestamp(SPLIT.backtest_start) for d in DATES])
    b = np.where(fit_mask, 0.0008, -0.0003)
    runs = _runs({"A": (np.full(len(DATES), 0.0001), DATES), "B": (b, DATES)})
    sel = select({"medium": runs}, 0.10, SPLIT, AS_OF)
    assert sel.fit.ret >= 0.10 and not sel.meets_goal
    assert sel.gap == pytest.approx(0.10 - sel.test.ret) and sel.closest is None
    assert sel.weights and sel.years and {y.split for y in sel.years} == {"fit", "test"}


def test_cannot_reach_returns_closest_max_mu_mix_and_caps():
    runs = _two_assets()
    sel = select({"medium": runs}, 1.5, SPLIT, AS_OF)
    assert not sel.meets_goal and sel.tolerance is None and sel.weights == {}
    assert sel.closest is not None and sel.closest.weights == {"B": 100}
    assert sel.cap_fit == pytest.approx(sel.closest.fit.ret)
    assert sel.cap_test == pytest.approx(sel.closest.test.ret)
    assert sel.closest.gap == pytest.approx(1.5 - sel.closest.test.ret)
    assert all(not row["feasible"] for row in sel.ladder)


def test_tau_with_lowest_fit_sigma_wins_and_ties_go_to_smaller_tolerance():
    calm = _runs({"A": (_sleeve(1, 0.00030, 0.0015), DATES), "B": (_sleeve(2, 0.0009, 0.015), DATES)},
                 "high", -0.25)
    rough = _two_assets("low", -0.08)
    sel = select({"low": rough, "high": calm}, 0.04, SPLIT, AS_OF)
    assert sel.tolerance == "high" and sel.tolerance_sensitive
    same = {t: _two_assets(t, m) for t, m in (("low", -0.08), ("medium", -0.15), ("high", -0.25))}
    sel2 = select(same, 0.04, SPLIT, AS_OF)
    assert sel2.tolerance == "low" and not sel2.tolerance_sensitive
    assert [row["tolerance"] for row in sel2.ladder] == ["low", "medium", "high"]


def test_fallback_segment_is_rechecked(monkeypatch):
    runs = _two_assets()
    monkeypatch.setattr(gsel, "min_variance_at", lambda *a, **k: None)   # "SLSQP did not converge"
    m = build_matrix(runs, FIT)
    target = metrics(m, np.array([0.5, 0.5])).ret
    sel = select({"medium": runs}, target, SPLIT, AS_OF)
    assert sel.solver == "fallback_segment" and sel.fallback_checked
    w = np.array([sel.weights.get("A", 0), sel.weights.get("B", 0)]) / 100
    assert metrics(m, w).ret >= target                        # rounded weights re-checked
    assert sel.fit.vol <= _brute_min_vol(m, target) * 1.02


def test_single_instrument():
    runs = _runs({"A": (_sleeve(1, 0.0004, 0.005), DATES)})
    ok = select({"medium": runs}, 0.0, SPLIT, AS_OF)
    assert ok.weights == {"A": 100}
    no = select({"medium": runs}, 0.9, SPLIT, AS_OF)
    assert no.closest.weights == {"A": 100}


def test_years_split_and_partial_flags():
    sel = select({"medium": _two_assets()}, 0.03, SPLIT, AS_OF)
    assert [(y.year, y.split, y.partial) for y in sel.years] == \
        [(2023, "fit", False), (2024, "fit", False), (2025, "test", False), (2026, "test", True)]


def test_selection_is_deterministic():
    a = select({"medium": _two_assets()}, 0.05, SPLIT, AS_OF)
    b = select({"medium": _two_assets()}, 0.05, SPLIT, AS_OF)
    assert a == b
