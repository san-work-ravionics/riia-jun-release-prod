"""F44 P3 — ``GoalSelectionService``, ``RetirementPlanService.goal`` and the start-up warm-up.

Uses a fake artifact repository (synthetic indicator frames + deterministic stand-in policies)
and a real file cache in tmp — no model zips, no CSVs, no network.

DoD items covered: exclusion reasons (incl. ``retrain_needed`` from the step-0 marker), stale
data, the location rule, cache key + disk cache + per-instrument lock, the SL guard flows
(``on_track`` needs no model run; a re-selection is spent only on ``reselect_proposed``),
the goal from What I Need (presets are never the goal), warm-up thread with its own session.
"""
from __future__ import annotations

import threading
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

import rita.services.goal_selection_service as svc_mod
from rita.config import get_settings
from rita.core.goal_selection import GoalSelection, Metrics, MixResult, windows
from rita.models.instrument import InstrumentModel
from rita.repositories.model_run_cache import ModelRunCacheRepository
from rita.services.goal_selection_service import GoalSelectionError, GoalSelectionService
from rita.services.retirement_plan_service import RetirementPlanService, default_plan

from .f44_p3_helpers import SPLIT, FakeArtifacts, PolicyModel, indicator_frame

END = "2026-06-30"


def _add(db, inst, cc):
    db.add(InstrumentModel(instrument_id=inst, name=inst, exchange="X", country_code=cc,
                           is_available=True, created_at=datetime.now(timezone.utc)))


@pytest.fixture(autouse=True)
def _fresh_memo():
    svc_mod.clear_memo()
    yield
    svc_mod.clear_memo()


@pytest.fixture
def world(db_session, tmp_path):
    """Europe: E1, E2 eligible; E3 no model; E4 rewritten (marker); E5 split jump; E6 stale;
    E7 load fails; E8 wrong obs width; E9 NaN feature in window; E0 no data. US: U1."""
    for inst in ("E0", "E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8", "E9"):
        _add(db_session, inst, "NL")
    _add(db_session, "U1", "US")
    db_session.commit()
    fa = FakeArtifacts()
    fa.frames = {i: indicator_frame(seed=n, end=END, drift=0.0003 + 0.0002 * n)
                 for n, i in enumerate(("E1", "E2", "E3", "E4", "E5", "E7", "E8", "U1"))}
    fa.frames["E6"] = indicator_frame(seed=6, end="2026-05-29")
    jump = fa.frames["E5"].copy()
    jump.loc[jump.index >= "2024-11-12", "Close"] *= 86
    fa.frames["E5"] = jump
    nan = indicator_frame(seed=9, end=END)
    nan.iloc[-30, nan.columns.get_loc("rsi_14")] = np.nan
    fa.frames["E9"] = nan
    fa.models = {i: PolicyModel() for i in ("E0", "E1", "E2", "E4", "E5", "E6", "E9", "U1")}
    fa.models["E7"] = RuntimeError("bad zip")
    fa.models["E8"] = PolicyModel(n_obs=13)
    fa.markers["E4"] = {"rewritten_at": "2026-10-26T10:00:00", "integrity_after_passed": False,
                        "lineages_invalidated": ["f34p25"]}
    cache = ModelRunCacheRepository(tmp_path / "cache")
    return db_session, fa, cache, tmp_path


def _svc(world):
    db, fa, cache, _ = world
    return GoalSelectionService(db, artifacts=fa, cache=cache)


# ── universe, exclusions ───────────────────────────────────────────────────────

def test_universe_uses_the_location_rule(world):
    s = _svc(world)
    assert s.universe("europe") == ["E0", "E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8", "E9"]
    assert s.universe("us") == ["U1"]
    with pytest.raises(GoalSelectionError) as e:
        s.universe("mars")
    assert e.value.code == "invalid_input"


def test_every_exclusion_reason(world):
    lr = _svc(world).location_runs("europe")
    reasons = {e.instrument_id: e.reason for e in lr.excluded}
    assert reasons == {"E0": "no_data", "E3": "no_model", "E4": "retrain_needed",
                       "E5": "data_integrity", "E6": "stale_data", "E7": "load_failed",
                       "E8": "feature_mismatch", "E9": "bad_data"}
    assert set(lr.runs) == {"E1", "E2"}
    assert lr.as_of == date(2026, 6, 30) and lr.window_start > SPLIT.train_end
    assert "2024-11-12" in next(e.detail for e in lr.excluded if e.reason == "data_integrity")
    assert "trained on the old data" in next(e.detail for e in lr.excluded if e.reason == "retrain_needed")


def test_retrain_needed_only_for_the_invalidated_lineage(world):
    db, fa, cache, _ = world
    fa.markers["E4"]["lineages_invalidated"] = ["f40_new"]
    lr = GoalSelectionService(db, artifacts=fa, cache=cache).location_runs("europe")
    assert "E4" in lr.runs


# ── select_for_goal ────────────────────────────────────────────────────────────

def test_select_for_goal_output(world):
    out = _svc(world).select_for_goal("europe", 0.03)
    assert out.currency == "EUR" and out.lineage == "f34p25" and out.engine == "rita_ddqn_v2"
    assert out.method.weights == "min-variance solver over model sleeves, μ ≥ target (not a model)"
    assert out.method.sleeves == "ddqn_v2 replay" and out.method.window == "lineage fit/test"
    assert out.fit_window.start == SPLIT.val_start and out.test_window.end == out.as_of
    assert len(out.excluded) == 8
    if out.holdings:
        assert sum(h.allocation_pct for h in out.holdings) == 100
        for h in out.holdings:
            assert h.sl_basis == "sleeve_drawdown_from_episode_peak" and h.sl_drawdown_limit == -0.10
            assert h.model_exit == (h.model_action == "cash")
            assert h.invested_pct <= h.allocation_pct
            assert h.episode_start >= out.window_start and 0 <= h.episode_day < h.episode_length
        assert out.meets_goal == (out.test_return >= 0.03)
    assert [r.tolerance for r in out.ladder] == ["low", "medium", "high"]


def test_as_of_must_be_the_cached_data_date(world):
    s = _svc(world)
    with pytest.raises(GoalSelectionError) as e:
        s.select_for_goal("europe", 0.05, as_of=date(2026, 6, 1))
    assert e.value.code == "invalid_input"
    assert s.select_for_goal("europe", 0.05, as_of=date(2026, 6, 30)).as_of == date(2026, 6, 30)


def test_no_eligible_instrument_is_not_found_with_exclusions(world):
    db, fa, cache, _ = world
    fa.models.pop("U1")
    with pytest.raises(GoalSelectionError) as e:
        GoalSelectionService(db, artifacts=fa, cache=cache).select_for_goal("us", 0.05)
    assert e.value.code == "not_found" and "U1:no_model" in e.value.message


# ── cache + lock ───────────────────────────────────────────────────────────────

def test_disk_cache_reproduces_without_loading_models(world):
    db, fa, cache, tmp = world
    first = GoalSelectionService(db, artifacts=fa, cache=cache).select_for_goal("europe", 0.04)
    # E6 is replayed (and cached) before the location's latest date marks it stale
    assert sorted(fa.loads) == ["E1", "E2", "E6", "E7", "E8", "E9"]
    assert (tmp / "cache" / "E1" / "f34p25_medium.json").is_file()
    svc_mod.clear_memo()
    fa.loads.clear()
    again = GoalSelectionService(db, artifacts=fa, cache=cache).select_for_goal("europe", 0.04)
    assert fa.loads == ["E7", "E8", "E9"]          # only the never-cached failures reload
    assert again == first


def test_new_data_invalidates_the_cache(world):
    db, fa, cache, _ = world
    GoalSelectionService(db, artifacts=fa, cache=cache).location_runs("europe")
    svc_mod.clear_memo()
    fa.loads.clear()
    fa.frames["E1"] = indicator_frame(seed=1, end=END, drift=0.0009)
    GoalSelectionService(db, artifacts=fa, cache=cache).location_runs("europe")
    assert "E1" in fa.loads and "E2" not in fa.loads


def test_concurrent_callers_replay_each_instrument_once(world):
    db, fa, cache, _ = world
    errors = []

    def go():
        try:
            GoalSelectionService(db, artifacts=fa, cache=cache).location_runs("us")
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=go) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors and fa.loads == ["U1"]


# ── required_return guard flows ────────────────────────────────────────────────

R = 0.07675


def test_on_track_and_count_and_year_end_need_no_model_run(world):
    db, fa, cache, _ = world
    s = GoalSelectionService(db, artifacts=fa, cache=cache)
    on = s.required_return("europe", R, 0.10, date(2026, 8, 31), date(2026, 1, 1), 0)
    assert (on.status, on.reason, on.reselections_next) == ("on_track", "on_track", 0)
    cnt = s.required_return("europe", R, -0.08, date(2026, 8, 31), date(2026, 1, 1), 2)
    assert (cnt.status, cnt.reason, cnt.reselections_next) == ("back_to_plan", "count", 2)
    ye = s.required_return("europe", R, -0.08, date(2026, 12, 31), date(2026, 1, 1), 0)
    assert (ye.status, ye.reason, ye.required_return) == ("back_to_plan", "year_end", None)
    assert fa.loads == [] and on.cap_fit is None and on.max_reselections == 2


def test_required_return_overflow_late_in_year_is_back_to_plan_cap(world):
    """Code Review P3 #1: a deep loss on Dec 30 overflows r′ — back to plan, never an error."""
    db, fa, cache, _ = world
    out = GoalSelectionService(db, artifacts=fa, cache=cache).required_return(
        "europe", 0.07, -0.85, date(2026, 12, 30), date(2026, 1, 1), 0)
    assert (out.status, out.reason, out.required_return) == ("back_to_plan", "cap", None)
    assert fa.loads == []                           # no model run for an unreachable r′
    out.model_dump_json()                           # serialises (no inf in the payload)


def test_replay_version_invalidates_the_cache(world, monkeypatch):
    """Code Review P3 #2: a change to the replay code (REPLAY_VERSION) re-runs the models."""
    db, fa, cache, _ = world
    GoalSelectionService(db, artifacts=fa, cache=cache).location_runs("europe")
    svc_mod.clear_memo()
    fa.loads.clear()
    monkeypatch.setattr(svc_mod, "REPLAY_VERSION", "test-next")
    GoalSelectionService(db, artifacts=fa, cache=cache).location_runs("europe")
    assert "E1" in fa.loads and "E2" in fa.loads


def test_required_return_invalid_input(world):
    with pytest.raises(GoalSelectionError) as e:
        _svc(world).required_return("europe", R, 0.0, date(2027, 2, 1), date(2026, 1, 1), 0)
    assert e.value.code == "invalid_input"


def _metrics(ret):
    return Metrics(ret=ret, vol=0.08, mdd=-0.05, sharpe=0.9, rf_annual=0.035, bars=400)


def _fake_sel(target, *, feasible, test_ret, cap_fit=0.30):
    fit_w, test_w = windows(SPLIT, date(2026, 6, 30))
    mix = MixResult("medium", -0.15, {"E1": 100}, _metrics(cap_fit), _metrics(0.2), target - 0.2)
    sel = GoalSelection(target_return=target, meets_goal=False, fit_window=fit_w, test_window=test_w,
                        cap_fit=cap_fit, cap_test=0.2, cap_mix=mix)
    if feasible:
        sel.tolerance, sel.tolerance_mdd, sel.weights = "medium", -0.15, {"E1": 60, "E2": 40}
        sel.fit, sel.test, sel.solver = _metrics(target + 0.01), _metrics(test_ret), "slsqp"
        sel.meets_goal = test_ret >= target
        sel.gap = None if sel.meets_goal else target - test_ret
    else:
        sel.closest = mix
    return sel


@pytest.mark.parametrize("feasible,test_ret,cap,status,reason,nxt", [
    (True, 0.50, 0.30, "reselect_proposed", "ok", 2),
    (True, 0.01, 0.30, "back_to_plan", "test_shortfall", 1),
    (False, 0.0, 0.30, "back_to_plan", "cap", 1),       # fit-infeasible after rounding
    (False, 0.0, 0.05, "back_to_plan", "cap", 1),       # r′ > cap_fit
])
def test_sl_response_solve_paths_spend_a_count_only_on_a_proposal(world, monkeypatch, feasible,
                                                                   test_ret, cap, status, reason, nxt):
    seen = []

    def fake_select(runs_by_tau, target, split, as_of):
        seen.append(target)
        return _fake_sel(target, feasible=feasible, test_ret=test_ret, cap_fit=cap)

    monkeypatch.setattr(svc_mod, "select", fake_select)
    out = _svc(world).required_return("europe", R, -0.03, date(2026, 6, 30), date(2026, 1, 1), 1)
    assert (out.status, out.reason, out.reselections_next) == (status, reason, nxt)
    assert seen == [out.required_return] and out.required_return > R      # solved at r′
    assert out.cap_fit == cap
    if status == "reselect_proposed":
        assert out.proposal.meets_goal and [h.allocation_pct for h in out.proposal.holdings] == [60, 40]
        assert out.closest is None
    else:
        assert out.proposal is None and out.closest is not None and out.closest.gap > 0


# ── model_runs ─────────────────────────────────────────────────────────────────

def test_model_runs_evidence(world):
    out = _svc(world).model_runs("europe")
    assert [i.instrument_id for i in out.instruments] == ["E1", "E2"]
    for inst in out.instruments:
        assert [r.tolerance for r in inst.runs] == ["low", "medium", "high"]
        assert inst.rf_annual == pytest.approx(0.07)       # DEFAULT_ENV_CONFIG rf (unknown ids)
        for r in inst.runs:
            assert r.fit.bars > 0 and r.test.bars > 0 and r.oob_bars >= 0
    assert {e.reason for e in out.excluded} >= {"no_model", "retrain_needed"}


# ── RetirementPlanService.goal ─────────────────────────────────────────────────

def test_goal_is_null_without_a_saved_plan(db_session):
    g = RetirementPlanService(db_session).goal("nobody", "europe")
    assert not g.saved and g.goal_return is None and g.horizon_years is None
    assert g.goal_value is None and g.assets == [] and g.currency == "EUR"


def test_goal_from_the_saved_plan(db_session):
    from rita.models.user import UserModel

    db_session.add(UserModel(id="alice"))
    db_session.commit()
    plan = default_plan("india").inputs
    svc = RetirementPlanService(db_session)
    svc.save("alice", plan, "india")
    g = svc.goal("alice", "india")
    assert g.saved and g.currency == "INR" and g.location == "india"
    assert g.goal_return == pytest.approx(0.117)
    assert g.horizon_years == 20.0
    assert g.goal_value == pytest.approx(svc.load_with_result("alice", "india").result.value)
    assert [a.asset_class for a in g.assets] == ["idx", "eq", "com", "alt"]


# ── warm-up ────────────────────────────────────────────────────────────────────

def test_warm_thread_uses_its_own_session_and_closes_it():
    fake_db = MagicMock()
    started = threading.Event()
    with patch("rita.database.SessionLocal", return_value=fake_db), \
            patch("rita.services.asta_trace_service.warm_job"), \
            patch.object(GoalSelectionService, "warm", side_effect=lambda: started.set()):
        # the P4 ASTA warm-up runs in the same thread with its own session — stubbed here
        t = svc_mod.start_warm_thread()
        t.join(timeout=5)
    assert started.is_set() and t.daemon
    fake_db.close.assert_called_once()


def test_warm_never_raises(world, monkeypatch):
    s = _svc(world)
    monkeypatch.setattr(s, "location_runs", MagicMock(side_effect=RuntimeError("boom")))
    assert s.warm() == {}


def test_lifespan_starts_warm_up_only_when_enabled(monkeypatch):
    from fastapi.testclient import TestClient

    from rita.main import app

    started = MagicMock()
    monkeypatch.setattr(svc_mod, "start_warm_thread", started)
    assert get_settings().goal_selection.warm_on_startup is False      # tests: off (conftest)
    with TestClient(app):
        pass
    started.assert_not_called()
    monkeypatch.setattr(get_settings().goal_selection, "warm_on_startup", True)
    with TestClient(app):
        pass
    started.assert_called_once()
