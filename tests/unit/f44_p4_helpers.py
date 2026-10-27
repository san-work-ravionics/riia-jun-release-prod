"""Shared builders for the F44 P4 unit tests: valid P3 tool payloads (GoalSelectionOut,
RequiredReturnOut, GoalOut, ModelRunsOut, SleeveTraceOut …) and a journey DB."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from rita.database import Base
from rita.schemas.goal_selection import (
    GoalOut,
    GoalSelectionOut,
    HoldingOut,
    InstrumentRunsOut,
    LadderOut,
    MixOut,
    ModelRunOut,
    ModelRunsOut,
    RequiredReturnOut,
    RunMetricsOut,
    WindowOut,
)
from rita.schemas.jarvis import JourneyGoalIn, JourneySaveIn, SleeveTraceOut, TrackingIn

CCY = {"europe": "EUR", "india": "INR", "us": "USD"}
PLAN_T0 = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)
FIT = WindowOut(start=date(2023, 1, 1), end=date(2024, 12, 31))
TEST = WindowOut(start=date(2025, 1, 1), end=date(2026, 6, 30))


def holding(inst: str, pct: int, tau: str = "medium", action: str = "full") -> HoldingOut:
    return HoldingOut(instrument_id=inst, allocation_pct=pct, tolerance=tau, tolerance_mdd=-0.15,
                      model_action=action, model_exit=action == "cash", model_derisk=action in ("half", "hedged"),
                      invested_pct=float(pct), sl_drawdown_limit=-0.10, episode_start=date(2026, 1, 2),
                      episode_day=100, episode_length=252, model_sha12="abc123def456")


def ladder() -> list[LadderOut]:
    return [LadderOut(tolerance=t, tolerance_mdd=m, feasible=True, cap_fit=0.21, cap_test=0.18, fit_vol=0.1)
            for t, m in (("low", -0.10), ("medium", -0.15), ("high", -0.20))]


def selection(location: str = "europe", target: float = 0.0775, holdings=None, meets: bool = True,
              closest: bool = False) -> GoalSelectionOut:
    hs = [] if closest else (holdings if holdings is not None else [holding("E1", 60), holding("E2", 40)])
    mix = MixOut(tolerance="high", tolerance_mdd=-0.2, holdings=[holding("E1", 100, "high")], fit_return=0.0612,
                 fit_vol=0.1, fit_mdd=-0.12, test_return=0.0534, test_vol=0.1, test_mdd=-0.11, gap=0.0241)
    return GoalSelectionOut(
        location=location, currency=CCY[location], target_return=target, meets_goal=meets and bool(hs),
        lineage="f34p25", tolerance=None if closest else "medium", tolerance_mdd=None if closest else -0.15,
        fit_window=FIT, test_window=TEST, fit_return=None if closest else 0.0912,
        fit_vol=0.11, fit_mdd=-0.09, test_return=None if closest else (0.0855 if meets else 0.0611),
        test_vol=0.12, test_mdd=None if closest else -0.0874, test_sharpe=0.8, rf_annual=0.02,
        gap=None if (meets or closest) else round(target - 0.0611, 6), holdings=hs,
        closest=mix if closest else None, cap_fit=0.0612 if closest else 0.2133,
        cap_test=0.0534 if closest else 0.1877, ladder=ladder(), tolerance_sensitive=True,
        as_of=date(2026, 6, 30), window_start=date(2023, 1, 1), excluded=[])


def required(status: str = "on_track", reason: str = "on_track", ytd: float = 0.031, used: int = 0,
             proposal: GoalSelectionOut | None = None, goal: float = 0.0775) -> RequiredReturnOut:
    nxt = used + 1 if status == "reselect_proposed" else used
    return RequiredReturnOut(
        location="europe", goal_return=goal, ytd_return=ytd, year_fraction=0.5, remaining_fraction=0.5,
        rest_of_year_return=0.0447, required_return=0.0913, effective_return=0.0913 if proposal else None,
        cap_fit=0.2133, cap_test=0.1877, status=status, reason=reason, reselections_used=used,
        reselections_next=nxt, max_reselections=2, proposal=proposal)


def goal(location: str = "europe", saved: bool = True, updated: datetime = PLAN_T0, r: float = 0.0775) -> GoalOut:
    return GoalOut(location=location, currency=CCY[location], saved=saved,
                   plan_updated_at=updated if saved else None, goal_return=r if saved else None,
                   horizon_years=13.0 if saved else None, goal_value=264804.0 if saved else None)


def goal_in(g: GoalOut) -> JourneyGoalIn:
    return JourneyGoalIn(saved=g.saved, plan_updated_at=g.plan_updated_at, goal_return=g.goal_return,
                         horizon_years=g.horizon_years, goal_value=g.goal_value)


def tracking(sel: GoalSelectionOut, entry: date) -> list[TrackingIn]:
    return [TrackingIn(instrument_id=h.instrument_id, allocation_pct=h.allocation_pct, tolerance=h.tolerance,
                       entry_date=entry, entry_close=100.0, sl_drawdown_limit=h.sl_drawdown_limit,
                       episode_start=h.episode_start, episode_length=h.episode_length,
                       model_sha12=h.model_sha12) for h in sel.holdings]


def save_in(event: str, location: str = "europe", **kw) -> JourneySaveIn:
    return JourneySaveIn(location=location, event=event, **kw)


def runs_out(location: str, sel: GoalSelectionOut) -> ModelRunsOut:
    m = RunMetricsOut(ann_return=0.1012, ann_vol=0.12, mdd=-0.0931, sharpe=0.9, bars=400)
    t = RunMetricsOut(ann_return=0.0856, ann_vol=0.13, mdd=-0.1043, sharpe=0.7, bars=300)
    ins = [InstrumentRunsOut(instrument_id=h.instrument_id, lineage="f34p25", model_sha12="abc123def456",
                             rf_annual=0.02, episode_length=252,
                             runs=[ModelRunOut(tolerance=tau, tolerance_mdd=-0.15, fit=m, test=t, oob_bars=0,
                                               today_action="full") for tau in ("low", "medium", "high")])
           for h in sel.holdings]
    return ModelRunsOut(location=location, lineage="f34p25", as_of=date(2026, 6, 30),
                        window_start=date(2023, 1, 1), fit_window=FIT, test_window=TEST, instruments=ins)


def trace(inst: str, *, sl_hit: bool = False, as_of: date = date(2026, 6, 30), ret: float = 0.0213) -> SleeveTraceOut:
    return SleeveTraceOut(
        instrument_id=inst, status="ok", lineage="f34p25", model_sha12="abc123def456", tolerance="medium",
        tolerance_rule="selection", as_of=as_of, window_start=date(2023, 1, 1), episode_length=252,
        episode_start=date(2026, 1, 2), episode_day=120, next_reset=date(2026, 12, 18), hard_mdd_limit=-0.10,
        today_action="full", invested_fraction=1.0, last_close=123.45, since=date(2026, 1, 2),
        return_since=ret, sleeve_peak=1.05, sleeve_now=1.0213, sl_level=0.945, sl_distance=-0.0747,
        sl_hit=sl_hit, last_entry_date=date(2026, 2, 3))


@pytest.fixture
def journey_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine)
    db = maker()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()
