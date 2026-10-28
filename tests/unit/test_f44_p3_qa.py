"""F44 P3 QA — goal-driven selection over DDQN v2 sleeves (design 2 + Rev 1–3 + N9/N10).

Gap tests on top of the Engineer's ``test_f44_p3_*.py`` (103 tests).  Synthetic data only
(seeded), the shared helpers in ``f44_p3_helpers``, no model zips, no network.

Property tests pin the contract:
  (a) the chosen mix is the least-σ fit-feasible mix (integer grid / 1-pt perturbation)
  (b) ``meets_goal`` ⇔ fit-feasible AND test return ≥ r
  (c) r′ is monotone in ytd (lower ytd ⇒ higher r′); ytd on the target path ⇒ r′ == r
  (d) guard order year_end → on_track → count → cap; a count is spent only on reselect_proposed
  (e) no hand-set window: fit / test windows come from the lineage split
  (f) determinism (two independent runs, input order)
Edge cases: short / empty windows, NaN indicators outside the window, single eligible
instrument, all-τ infeasible ladder → closest + gap, rounding sums to 100, cap invariant.
Design contract: the Architect's module targets (as revised) exist with the agreed shapes.
"""
from __future__ import annotations

import inspect
import itertools
import math
from dataclasses import fields
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

import rita.services.goal_selection_service as svc_mod
from rita.core import goal_model_runs as gmr
from rita.core import goal_selection as gsel
from rita.core import goal_targets as gt
from rita.core.data_integrity import IntegrityResult, check_window
from rita.core.goal_model_runs import LineageSplit, parse_lineage_split, run_policy
from rita.core.goal_selection import build_matrix, metrics, round_weights, select, windows
from rita.core.goal_targets import (
    RequiredReturn,
    decide_sl_response,
    required_return,
    target_to_date,
)
from rita.core.instrument_config import DEFAULT_ENV_CONFIG
from rita.models.instrument import InstrumentModel
from rita.repositories.model_artifact import ModelArtifactRepository
from rita.repositories.model_run_cache import ModelRunCacheRepository
from rita.services.goal_selection_service import GoalSelectionError, GoalSelectionService

from .f44_p3_helpers import SPLIT, FakeArtifacts, PolicyModel, fixed_run, indicator_frame

AS_OF = date(2026, 6, 30)
DATES = pd.bdate_range("2023-01-02", AS_OF)
FIT, TEST = windows(SPLIT, AS_OF)
TAUS = (("low", -0.08), ("medium", -0.15), ("high", -0.25))
R = 0.07675


def _sleeve(seed: int, mu: float, vol: float, dates=DATES) -> np.ndarray:
    t = np.arange(len(dates))
    return mu + vol * math.sqrt(2) * np.sin(t / (2.0 + seed) + seed)


def _three(tol="medium", tol_mdd=-0.15, scale=1.0):
    spec = {"A": _sleeve(1, 0.0001, 0.002 * scale), "B": _sleeve(2, 0.0005, 0.008 * scale),
            "C": _sleeve(3, 0.0009, 0.015 * scale)}
    return {k: fixed_run(k, v, DATES, tolerance=tol, tolerance_mdd=tol_mdd) for k, v in spec.items()}


def _w(sel, ids=("A", "B", "C")) -> np.ndarray:
    return np.array([sel.weights.get(i, 0) for i in ids])


# ── (a) least-σ among fit-feasible mixes ───────────────────────────────────────

def test_a_chosen_mix_is_least_sigma_on_the_integer_grid():
    """3 sleeves, brute force over all 5151 integer mixes.  The continuous SLSQP solution is
    the least-σ fit-feasible point (≤ the best integer mix); the published integer mix is within
    the 1-pt rounding + repair effect of the best feasible integer mix (QA-O1: largest
    remainder + the design's low-μ → high-μ repair is not integer-optimal; ≤ 2 % σ)."""
    runs = _three()
    m = build_matrix(runs, FIT)
    grid = [np.array([a, b, 100 - a - b]) for a in range(101) for b in range(101 - a)]
    mts = [(metrics(m, g / 100.0), g) for g in grid]
    cap = max(mt.ret for mt, _ in mts)
    w_max = gsel.max_return_mix(m)
    lo = metrics(m, np.array([1.0, 0, 0])).ret
    for frac in (0.2, 0.5, 0.8):
        target = lo + frac * (cap - lo)
        best = min(mt.vol for mt, _ in mts if mt.ret >= target)
        w_star = gsel.min_variance_at(m, target, w_max)
        assert metrics(m, w_star).ret >= target - 1e-9
        assert metrics(m, w_star).vol <= best + 1e-9                # solver: least σ
        sel = select({"medium": runs}, target, SPLIT, AS_OF)
        assert sel.tolerance == "medium" and sel.solver == "slsqp"
        assert sel.fit.ret >= target                                # feasible after rounding
        assert best <= sel.fit.vol <= best * 1.02


def test_a_one_point_perturbation_never_lowers_sigma_materially():
    runs = _three()
    m = build_matrix(runs, FIT)
    for target in (0.04, 0.07, 0.09):
        sel = select({"medium": runs}, target, SPLIT, AS_OF)
        w = _w(sel)
        base = metrics(m, w / 100.0).vol
        for i, j in itertools.permutations(range(3), 2):
            if w[j] == 0:
                continue
            p = w.copy()
            p[i] += 1
            p[j] -= 1
            mt = metrics(m, p / 100.0)
            if mt.ret >= target:
                assert mt.vol >= base * (1 - 0.02), (target, w, p)      # QA-O1 bound


def test_a_not_profit_maximisation_when_target_is_slack():
    """A target below every sleeve's fit return: the least-σ mix is chosen, not the max-μ mix."""
    runs = _three()
    sel = select({"medium": runs}, -0.20, SPLIT, AS_OF)
    m = build_matrix(runs, FIT)
    mv = gsel.min_variance_mix(m)
    assert sel.fit.vol <= metrics(m, mv).vol * 1.005
    assert sel.fit.ret < sel.cap_fit


# ── (b) meets_goal ⇔ fit-feasible AND test ≥ r ─────────────────────────────────

def _fit_test_divergent():
    fit_mask = np.array([d < pd.Timestamp(SPLIT.backtest_start) for d in DATES])
    a = np.where(fit_mask, 0.0002, 0.0004) + _sleeve(1, 0.0, 0.002)
    b = np.where(fit_mask, 0.0009, -0.0001) + _sleeve(2, 0.0, 0.01)
    c = np.where(fit_mask, 0.0005, 0.0007) + _sleeve(3, 0.0, 0.006)
    return {k: fixed_run(k, v, DATES) for k, v in (("A", a), ("B", b), ("C", c))}


@pytest.mark.parametrize("target", [-0.05, 0.0, 0.05, 0.08, 0.12, 0.16, 0.20, 0.30, 0.60])
def test_b_meets_goal_iff_fit_feasible_and_test_return_reaches_target(target):
    sel = select({"medium": _fit_test_divergent()}, target, SPLIT, AS_OF)
    fit_feasible = sel.tolerance is not None
    assert fit_feasible == any(row["feasible"] for row in sel.ladder)
    assert sel.meets_goal == (fit_feasible and sel.test.ret >= target - 1e-12)
    if fit_feasible:
        assert sel.fit.ret >= target - 1e-12
        assert sum(sel.weights.values()) == 100 and all(v > 0 for v in sel.weights.values())
        assert sel.closest is None
        assert (sel.gap is None) == sel.meets_goal
        if not sel.meets_goal:
            assert sel.gap == pytest.approx(target - sel.test.ret)
    else:
        assert not sel.meets_goal and sel.weights == {} and sel.closest is not None


def test_b_cap_invariant_target_at_or_below_cap_fit_is_always_feasible():
    """Reviewer N2 claim: r ≤ cap_fit ⇒ some τ is feasible (the guard's cap step and the solver
    agree); r just above the best cap ⇒ none is."""
    rng = np.random.default_rng(11)
    rbt = {t: {f"I{i}": fixed_run(f"I{i}", rng.normal(rng.uniform(-0.0002, 0.001),
                                                       rng.uniform(0.003, 0.02), len(DATES)),
                                  DATES, tolerance=t, tolerance_mdd=mdd) for i in range(3)}
           for t, mdd in TAUS}
    cap = select(rbt, 0.0, SPLIT, AS_OF).cap_fit
    for target in (cap - 0.03, cap - 1e-6, cap):
        assert select(rbt, float(target), SPLIT, AS_OF).tolerance is not None
    assert select(rbt, cap + 1e-3, SPLIT, AS_OF).tolerance is None


def test_b_all_tau_infeasible_gives_closest_cap_mix_and_gap():
    rbt = {t: _three(t, mdd, scale=s) for (t, mdd), s in zip(TAUS, (1.0, 0.8, 1.2))}
    sel = select(rbt, 2.0, SPLIT, AS_OF)
    assert not sel.meets_goal and sel.tolerance is None and sel.weights == {}
    assert [r["tolerance"] for r in sel.ladder] == ["low", "medium", "high"]
    assert not any(r["feasible"] for r in sel.ladder)
    best = max(sel.ladder, key=lambda r: r["cap_fit"])
    assert sel.cap_fit == best["cap_fit"] and sel.closest.tolerance == best["tolerance"]
    assert sel.closest is sel.cap_mix
    assert sum(sel.closest.weights.values()) == 100
    assert sel.closest.gap == pytest.approx(2.0 - sel.closest.test.ret)
    assert sel.cap_test == pytest.approx(sel.closest.test.ret)


# ── (c) r′ monotone in ytd; on the target path r′ == r ─────────────────────────

@pytest.mark.parametrize("s,as_of", [
    (date(2026, 1, 1), date(2026, 3, 31)),
    (date(2026, 1, 1), date(2026, 11, 30)),
    (date(2026, 7, 1), date(2026, 9, 15)),
    (date(2024, 2, 29), date(2024, 12, 30)),
])
def test_c_r_prime_strictly_decreasing_in_ytd(s, as_of):
    ytds = np.linspace(-0.5, 0.5, 41)
    rp = [required_return(R, float(y), as_of, s).required_return for y in ytds]
    assert all(a >= b for a, b in zip(rp, rp[1:]))
    # strict wherever r′ is not saturated at −1 in float (far ahead of plan with days left ≈ 0)
    assert all(a > b for a, b in zip(rp, rp[1:]) if b > -0.999)
    g = [required_return(R, float(y), as_of, s).rest_of_year_return for y in ytds]
    assert all(a > b for a, b in zip(g, g[1:]))


@pytest.mark.parametrize("r", [0.0, 0.03, R, 0.117, 0.5])
@pytest.mark.parametrize("s", [date(2026, 1, 1), date(2026, 4, 15), date(2024, 2, 29)])
def test_c_on_the_target_path_r_prime_equals_r(r, s):
    for days in (0, 1, 30, 120, 200):
        as_of = s + timedelta(days=days - 1)
        if as_of >= date(s.year, 12, 31):
            continue
        ytd = target_to_date(r, s, as_of)
        req = required_return(r, ytd, as_of, s)
        assert req.required_return == pytest.approx(r, abs=1e-12)
        d = decide_sl_response(req, 1.0, 0, 2)
        # a hair below the path → off track (r′ > r); a hair above → on track
        below = required_return(r, ytd - 1e-6, as_of, s).required_return
        above = required_return(r, ytd + 1e-6, as_of, s).required_return
        assert below > r > above
        assert d.action in ("on_track", "solve")


# ── (d) guard order + count spent only on a proposal ───────────────────────────

def _expected(year_end, rel, used, cap_rel, max_n):
    if year_end:
        return ("back_to_plan", "year_end")
    if rel <= 0:
        return ("on_track", "on_track")
    if used >= max_n:
        return ("back_to_plan", "count")
    if cap_rel is None or cap_rel < 0:
        return ("back_to_plan", "cap")
    return ("solve", "ok")


def test_d_guard_order_exhaustive():
    for year_end, rel, used, cap_rel, max_n in itertools.product(
            (True, False), (-0.02, 0.0, 0.03), (0, 1, 2, 3), (None, -0.01, 0.0, 0.05), (2, 3)):
        rp = R + rel
        req = RequiredReturn(R, -0.05, 1.0, 0.5, 0.1, None if year_end else rp,
                             None if year_end else max(rp, R), year_end)
        cap = None if cap_rel is None else rp + cap_rel
        d = decide_sl_response(req, cap, used, max_n)
        assert (d.action, d.reason) == _expected(year_end, rel, used, cap_rel, max_n)


def _add(db, inst, cc):
    db.add(InstrumentModel(instrument_id=inst, name=inst, exchange="X", country_code=cc,
                           is_available=True, created_at=datetime.now(timezone.utc)))


@pytest.fixture(autouse=True)
def _fresh_memo():
    svc_mod.clear_memo()
    yield
    svc_mod.clear_memo()


def _world(db, tmp_path, insts=("Q1", "Q2", "Q3"), cc="NL", end="2026-06-30", split=SPLIT, **frame_kw):
    for i in insts:
        _add(db, i, cc)
    db.commit()
    fa = FakeArtifacts(split=split)
    fa.frames = {i: indicator_frame(seed=10 + n, end=end, drift=0.0002 + 0.0003 * n, **frame_kw)
                 for n, i in enumerate(insts)}
    fa.models = {i: PolicyModel() for i in insts}
    return fa, ModelRunCacheRepository(tmp_path / "cache")


def test_d_service_count_spent_only_on_reselect_proposed(db_session, tmp_path):
    """Real solve (no monkeypatch): across ytd values every status obeys the count rule and the
    contract of its reason."""
    fa, cache = _world(db_session, tmp_path)
    s = GoalSelectionService(db_session, artifacts=fa, cache=cache)
    seen = set()
    for ytd in (0.20, 0.0, -0.02, -0.05, -0.10, -0.30):
        for used in (0, 1, 2):
            out = s.required_return("europe", 0.03, ytd, date(2026, 6, 30), date(2026, 1, 1), used)
            seen.add((out.status, out.reason))
            assert out.reselections_next == used + (out.status == "reselect_proposed")
            if out.status == "on_track":
                assert out.required_return <= 0.03 and out.proposal is None
            if used >= 2 and out.required_return is not None and out.required_return > 0.03:
                assert out.reason == "count"
            if out.status == "reselect_proposed":
                p = out.proposal
                assert p.meets_goal and p.target_return == out.required_return
                assert p.test_return >= out.required_return and out.required_return <= out.cap_fit
                assert sum(h.allocation_pct for h in p.holdings) == 100
            if out.reason == "cap":
                assert out.required_return > out.cap_fit and out.closest is not None
            if out.reason == "test_shortfall":
                assert out.closest.test_return < out.required_return
    assert ("on_track", "on_track") in seen and ("back_to_plan", "count") in seen
    assert seen & {("reselect_proposed", "ok"), ("back_to_plan", "test_shortfall"),
                   ("back_to_plan", "cap")}


# ── (e) no hand-set window: windows follow the lineage split ───────────────────

ALT = LineageSplit(date(2023, 6, 30), date(2023, 7, 1), date(2024, 6, 30), date(2024, 7, 1))


def test_e_core_windows_follow_the_split():
    f2, t2 = windows(ALT, AS_OF)
    assert (FIT.start, FIT.end, TEST.start) == (SPLIT.val_start, SPLIT.val_end, SPLIT.backtest_start)
    assert (f2.start, f2.end, t2.start, t2.end) == (ALT.val_start, ALT.val_end, ALT.backtest_start, AS_OF)
    a = select({"medium": _three()}, 0.03, SPLIT, AS_OF)
    b = select({"medium": _three()}, 0.03, ALT, AS_OF)
    assert (a.fit_window, b.fit_window) == (FIT, f2) and a.fit != b.fit
    assert [y.year for y in b.years if y.split == "fit"] == [2023, 2024]
    assert all(y.partial for y in b.years if y.split == "fit")


def test_e_replay_window_starts_after_the_split_train_end():
    df = indicator_frame(seed=3, end="2025-06-30")
    for split in (SPLIT, ALT):
        run = run_policy(PolicyModel(), df, DEFAULT_ENV_CONFIG, split, "medium",
                         instrument="X", lineage="f34p25", model_sha12="0" * 12)
        assert run.window_start == df.index[df.index > pd.Timestamp(split.train_end)][0].date()
        assert run.dates[0] > split.train_end and run.episode_starts[0] == run.window_start


def test_e_service_windows_change_with_the_split_and_the_cache_rekeys(db_session, tmp_path):
    fa, cache = _world(db_session, tmp_path)
    a = GoalSelectionService(db_session, artifacts=fa, cache=cache).select_for_goal("europe", 0.03)
    svc_mod.clear_memo()
    fa.loads.clear()
    fa.split = ALT
    b = GoalSelectionService(db_session, artifacts=fa, cache=cache).select_for_goal("europe", 0.03)
    assert a.fit_window.start == SPLIT.val_start and b.fit_window.start == ALT.val_start
    assert b.test_window.start == ALT.backtest_start and b.window_start > ALT.train_end
    assert sorted(fa.loads) == ["Q1", "Q2", "Q3"]              # split_hash in the cache key


def test_e_split_parsed_from_source_drives_the_window():
    src = ('TRAIN_END = "2021-12-31"\nVAL_START, VAL_END = "2022-01-01", "2023-06-30"\n'
           'BACKTEST_START = "2023-07-01"\n')
    sp = parse_lineage_split(src)
    f, t = windows(sp, AS_OF)
    assert (f.start, f.end, t.start) == (date(2022, 1, 1), date(2023, 6, 30), date(2023, 7, 1))


# ── (f) determinism ────────────────────────────────────────────────────────────

def test_f_two_independent_service_runs_are_identical(db_session, tmp_path):
    fa, _ = _world(db_session, tmp_path)
    outs = []
    for n in range(2):
        svc_mod.clear_memo()
        cache = ModelRunCacheRepository(tmp_path / f"cache{n}")
        s = GoalSelectionService(db_session, artifacts=fa, cache=cache)
        outs.append((s.select_for_goal("europe", 0.04).model_dump_json(),
                     s.model_runs("europe").model_dump_json()))
    assert outs[0] == outs[1]
    assert len(fa.loads) == 6                                   # both runs replayed from scratch


def test_f_selection_is_invariant_to_input_order():
    rbt = {t: _three(t, mdd, scale=s) for (t, mdd), s in zip(TAUS, (1.0, 0.7, 1.3))}
    a = select(rbt, 0.05, SPLIT, AS_OF)
    rev = {t: dict(reversed(list(rbt[t].items()))) for t in reversed(list(rbt))}
    b = select(rev, 0.05, SPLIT, AS_OF)
    assert (a.tolerance, a.weights, a.fit, a.test, a.cap_fit) == \
        (b.tolerance, b.weights, b.fit, b.test, b.cap_fit)


# ── edge cases ─────────────────────────────────────────────────────────────────

def test_edge_rounding_always_sums_to_100_and_keeps_zeros():
    rng = np.random.default_rng(5)
    for _ in range(500):
        k = int(rng.integers(1, 8))
        w = rng.dirichlet(np.ones(k))
        w[rng.random(k) < 0.3] = 0.0
        if w.sum() == 0:
            w[0] = 1.0
        w = w / w.sum()
        ids = [f"I{i}" for i in rng.permutation(k)]
        r = round_weights(w, ids)
        assert r.sum() == 100 and (r >= 0).all()
        assert np.all(np.abs(r - w * 100) < 1.0 + 1e-9)
        assert np.all(r[w == 0] == 0)


def test_edge_one_bar_after_train_end_is_no_data(db_session, tmp_path):
    fa, cache = _world(db_session, tmp_path, insts=("Q1", "Q2"))
    fa.frames["Q2"] = fa.frames["Q2"][fa.frames["Q2"].index <= "2023-01-02"]
    lr = GoalSelectionService(db_session, artifacts=fa, cache=cache).location_runs("europe")
    ex = {e.instrument_id: e for e in lr.excluded}
    assert ex["Q2"].reason == "no_data" and "after 2022-12-31" in ex["Q2"].detail
    assert set(lr.runs) == {"Q1"}
    with pytest.raises(ValueError):
        run_policy(PolicyModel(), fa.frames["Q2"], DEFAULT_ENV_CONFIG, SPLIT, "medium",
                   instrument="Q2", lineage="f34p25", model_sha12="0" * 12)


def test_edge_data_ending_before_the_test_window_is_unavailable(db_session, tmp_path):
    """Every sleeve ends inside the fit years → no test bar → a coded ``unavailable``."""
    fa, cache = _world(db_session, tmp_path, end="2024-09-30")
    with pytest.raises(GoalSelectionError) as e:
        GoalSelectionService(db_session, artifacts=fa, cache=cache).select_for_goal("europe", 0.03)
    assert e.value.code == "unavailable" and "test" in e.value.message


def test_edge_nan_indicator_before_train_end_does_not_exclude(db_session, tmp_path):
    """Only the model's window is validated: a NaN in the training years is not a window bar."""
    fa, cache = _world(db_session, tmp_path, insts=("Q1", "Q2"))
    df = fa.frames["Q2"].copy()
    df.loc[df.index[50], "rsi_14"] = np.nan
    df.loc[df.index[60], "macd"] = np.inf
    fa.frames["Q2"] = df
    lr = GoalSelectionService(db_session, artifacts=fa, cache=cache).location_runs("europe")
    assert set(lr.runs) == {"Q1", "Q2"} and lr.excluded == []
    # …and the same NaN inside the window is bad_data
    svc_mod.clear_memo()
    df2 = df.copy()
    df2.loc[df2.index[-5], "bb_pct_b"] = np.nan
    fa.frames["Q2"] = df2
    lr2 = GoalSelectionService(db_session, artifacts=fa,
                               cache=ModelRunCacheRepository(tmp_path / "c2")).location_runs("europe")
    assert [(e.instrument_id, e.reason) for e in lr2.excluded] == [("Q2", "bad_data")]


def test_edge_single_eligible_instrument_service(db_session, tmp_path):
    fa, cache = _world(db_session, tmp_path, insts=("U9",), cc="US")
    s = GoalSelectionService(db_session, artifacts=fa, cache=cache)
    ok = s.select_for_goal("us", -0.5)
    assert ok.currency == "USD" and [(h.instrument_id, h.allocation_pct) for h in ok.holdings] == [("U9", 100)]
    h = ok.holdings[0]
    assert h.invested_pct == pytest.approx(100 * gmr.ACTION_ALLOCATION[h.model_action])
    no = s.select_for_goal("us", 2.0)
    assert not no.meets_goal and no.holdings == [] and no.tolerance is None
    assert [(x.instrument_id, x.allocation_pct) for x in no.closest.holdings] == [("U9", 100)]
    assert no.closest.gap == pytest.approx(2.0 - no.closest.test_return)


def test_edge_all_instruments_excluded_is_not_found_listing_each(db_session, tmp_path):
    fa, cache = _world(db_session, tmp_path, insts=("Q1", "Q2"))
    fa.models.pop("Q1")
    fa.models["Q2"] = PolicyModel(n_actions=3)
    s = GoalSelectionService(db_session, artifacts=fa, cache=cache)
    for call in (lambda: s.select_for_goal("europe", 0.05), lambda: s.model_runs("europe")):
        with pytest.raises(GoalSelectionError) as e:
            call()
        assert e.value.code == "not_found"
        assert "Q1:no_model" in e.value.message and "Q2:feature_mismatch" in e.value.message


def test_edge_integrity_threshold_is_inclusive():
    """A post-train_end move equal to the pre-train_end max passes; just above fails."""
    idx = pd.bdate_range("2022-12-26", "2023-01-06")
    lr = [0.0, 0.10, -0.05, 0.02, 0.01, 0.10, 0.0, 0.1001, 0.0, 0.0]
    close = pd.Series(100 * np.exp(np.cumsum(lr)), index=idx)
    res = check_window(close, date(2022, 12, 31))
    assert isinstance(res, IntegrityResult) and res.threshold == pytest.approx(0.10)
    assert [d for d, _ in res.failures] == [idx[7].date()]


def test_edge_holdings_invested_pct_is_weight_times_todays_model_allocation(db_session, tmp_path):
    fa, cache = _world(db_session, tmp_path)
    out = GoalSelectionService(db_session, artifacts=fa, cache=cache).select_for_goal("europe", 0.0)
    assert out.holdings
    for h in out.holdings:
        assert h.invested_pct == pytest.approx(h.allocation_pct * gmr.ACTION_ALLOCATION[h.model_action])
        assert h.model_derisk == (h.model_action in ("half", "hedged"))
        assert h.tolerance == out.tolerance and h.sl_drawdown_limit == DEFAULT_ENV_CONFIG.hard_mdd_limit


# QA-F1 (fixed): design edge 7 — the combined stream is checked finite before the solve.
def test_qa_f1_non_finite_sleeve_return_is_rejected_before_the_solve():
    runs = _three()
    x = list(runs["A"].daily_returns)
    x[100] = float("nan")
    runs["A"] = fixed_run("A", x, DATES)
    with pytest.raises(ValueError, match="(?i)finite"):
        select({"medium": runs}, 0.03, SPLIT, AS_OF)


# ── design contract: Architect module targets (as revised) ─────────────────────

def _params(fn):
    return list(inspect.signature(fn).parameters)


def test_contract_core_targets():
    assert _params(gt.blend_goal_return) == ["assets"]
    assert _params(gt.year_fraction) == ["start", "end"]
    assert _params(gt.required_return) == ["goal_return", "ytd_return", "as_of", "year_start"]
    assert {f.name for f in fields(RequiredReturn)} >= {
        "year_fraction", "remaining_fraction", "rest_of_year_return", "required_return",
        "effective_return", "year_end"}
    # R2-3 / R3 N2: the guard takes the RequiredReturn, the fit cap, the count and the
    # settings limit (no literal default)
    sig = inspect.signature(gt.decide_sl_response)
    assert list(sig.parameters) == ["required", "cap_fit", "reselections_used", "max_reselections"]
    assert sig.parameters["max_reselections"].default is inspect.Parameter.empty

    assert _params(gmr.run_policy)[:5] == ["model", "df_full", "env_config", "split", "tolerance"]
    assert _params(gmr.check_compat) == ["model", "df", "env_config"]
    assert _params(gmr.parse_lineage_split) == ["source"]
    run_fields = {f.name for f in fields(gmr.ModelRun)}
    assert run_fields >= {"instrument", "lineage", "model_sha12", "tolerance", "dates",
                          "daily_returns", "allocations", "hedge_flags", "today_action", "as_of",
                          "window_start", "episode_starts", "oob_bars", "rf_daily"}
    assert hasattr(gmr.ModelRun, "today_allocation") and hasattr(gmr.ModelRun, "today_hedged")
    assert gmr.TOLERANCE_LEVELS == ("low", "medium", "high")

    from rita.core import data_integrity
    assert _params(data_integrity.check_window) == ["close", "train_end"]
    assert _params(gsel.select) == ["runs_by_tau", "target_return", "split", "as_of"]
    assert _params(gsel.max_return_mix) == ["m"]

    from rita.core.trading_env_v2 import run_episode_v2
    p = inspect.signature(run_episode_v2).parameters
    for k in ("days_denominator", "predict_last", "clip_step_return"):
        assert p[k].kind is inspect.Parameter.KEYWORD_ONLY
    assert (p["days_denominator"].default, p["predict_last"].default,
            p["clip_step_return"].default) == (None, False, False)


def test_contract_repositories_services_schemas_and_tools():
    for name in ("find", "load", "load_indicator_frame", "lineage_split", "sha256", "rewrite_marker"):
        assert callable(getattr(ModelArtifactRepository, name))
    assert _params(ModelRunCacheRepository.get) == ["self", "instrument", "lineage", "tolerance", "key"]
    assert _params(ModelRunCacheRepository.put) == ["self", "instrument", "lineage", "tolerance", "key", "run"]
    assert _params(GoalSelectionService.__init__)[:2] == ["self", "db"]
    for name in ("universe", "model_runs", "select_for_goal", "required_return", "warm"):
        assert callable(getattr(GoalSelectionService, name))
    assert _params(GoalSelectionService.select_for_goal) == ["self", "location", "target_return", "as_of"]
    assert _params(GoalSelectionService.required_return) == [
        "self", "location", "goal_return", "ytd_return", "as_of", "year_start", "reselections_used"]

    from rita.services.retirement_plan_service import RetirementPlanService
    assert _params(RetirementPlanService.goal) == ["self", "user_id", "location"]

    from rita.schemas import goal_selection as sch
    for cls in ("GoalOut", "ModelRunOut", "HoldingOut", "GoalSelectionOut", "RequiredReturnOut",
                "ExcludedOut", "ModelRunsOut", "MixOut", "LadderOut", "MethodOut"):
        assert hasattr(sch, cls), cls
    gso = sch.GoalSelectionOut.model_fields
    for f in ("meets_goal", "fit_window", "test_window", "fit_return", "test_return", "test_sharpe",
              "cap_fit", "cap_test", "ladder", "tolerance_sensitive", "graded", "solver",
              "fallback_checked", "method", "excluded", "closest", "years", "holdings", "lineage"):
        assert f in gso, f
    rr = sch.RequiredReturnOut.model_fields
    for f in ("status", "reason", "reselections_next", "proposal", "closest", "cap_fit", "cap_test"):
        assert f in rr, f
    ho = sch.HoldingOut.model_fields
    for f in ("allocation_pct", "tolerance", "tolerance_mdd", "model_action", "model_exit",
              "model_derisk", "invested_pct", "sl_drawdown_limit", "sl_basis", "episode_start",
              "episode_day", "episode_length", "model_sha12"):
        assert f in ho, f

    from rita.config import get_settings
    gs = get_settings().goal_selection
    assert gs.max_reselections_per_year == 2 and gs.model_lineages
    assert gs.model_lineages[0].name == "f34p25"

    import rita.interfaces.mcp_tools as mt
    names = set(mt.REGISTRY)
    assert {"whatineed.get_goal", "portfolio.select_for_goal", "portfolio.required_return",
            "portfolio.model_runs"} <= names
