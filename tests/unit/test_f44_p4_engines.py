"""F44 P4 — the page composition (JarvisPageService A4–A6): perf source rules, the guard runs
only while tracking (rev 3 P3-2b preview never reaches ``required_return``), engine rows against
the one target path T (B2: r = the annual goal, never target_return), the per-engine levels table
(rev 1 A2), N2 live holdings — and no DB write in the Experience tier (A11).
"""
# ruff: noqa: F811 — pytest fixtures imported from a sibling module are redefined as test params
from __future__ import annotations

import re
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest

from rita.core.goal_targets import target_to_date
from rita.interfaces.mcp_client import McpCallError, ToolCallResult
from rita.schemas.jarvis import (
    AstaTraceOut,
    JourneyOut,
    MarkerOut,
    PnlOut,
    PnlPointOut,
    SigmaLevelsOut,
    SleeveDetailOut,
)
from rita.services.jarvis_page_service import JarvisPageService, PageError

from .f44_p4_helpers import PLAN_T0, goal, journey_db, required, selection, trace  # noqa: F401

SRC = Path(__file__).resolve().parents[2] / "src" / "rita"
S = date(2026, 3, 2)
AS_OF = date(2026, 6, 30)


class FakeMcp:
    def __init__(self, payloads):
        self.payloads = payloads
        self.calls: list[tuple[str, dict]] = []

    def call(self, name, args=None):
        args = args or {}
        self.calls.append((name, args))
        p = self.payloads.get(name)
        p = p(args) if callable(p) else p
        if p is None:
            raise McpCallError(name, "not_found", "none", str(uuid.uuid4()))
        return ToolCallResult(name=name, structured=p.model_dump(mode="json"), text="", call_id="c")

    def names(self):
        return [n for n, _ in self.calls]


class User:
    id = "alice"


def _journey(state: str, segments=True, goal_return=0.0775, target_return=0.0913) -> JourneyOut:
    sel = selection()
    segs = [{"from": S.isoformat(), "to": None, "cause": "track",
             "holdings": [{"instrument_id": "E1", "allocation_pct": 60, "tolerance": "medium"},
                          {"instrument_id": "E2", "allocation_pct": 40, "tolerance": "medium"}]}] if segments else []
    trk = [{"instrument_id": h.instrument_id, "allocation_pct": h.allocation_pct, "tolerance": "medium",
            "entry_date": S.isoformat(), "entry_close": 100.0, "sl_drawdown_limit": -0.1}
           for h in sel.holdings] if segments else []
    return JourneyOut(journey_id="j", location="europe", currency="EUR", state=state, goal_return=goal_return,
                      target_return=target_return, plan_updated_at=PLAN_T0, reselect_count=0, max_reselections=2, selection=sel,
                      tracking=trk, segments=segs, plan_year_start=S if segments else None, version=3)


def _pnl(source: str, ytd: float, s: date = S) -> PnlOut:
    return PnlOut(location="europe", currency="EUR", source=source, as_of=AS_OF, year_start=s, ytd_return=ytd,
                  coverage=1.0, series=[PnlPointOut(date=s, ret=0.0, source="model_sleeves"),
                                        PnlPointOut(date=AS_OF, ret=ytd, source="model_sleeves")])


def _payloads(j: JourneyOut | None, saved: bool):
    def pnl(a):
        if a.get("source") == "model_sleeves":
            return _pnl("model_sleeves_preview" if a.get("preview") else "model_sleeves", 0.021,
                        date(2026, 1, 1) if a.get("preview") else S)
        if a.get("source") == "saved" or not a.get("segments"):
            return _pnl("saved", 0.034, date(2026, 2, 10)) if saved else None
        return _pnl("mixed" if saved else "model_sleeves", 0.028)

    return {
        "whatineed.get_goal": goal("europe"), "journey.get_current": j, "portfolio.pnl": pnl,
        "portfolio.required_return": lambda a: required(ytd=a["ytd_return"]),
        "portfolio.sleeve_trace": lambda a: trace(a["instrument"], as_of=AS_OF),
        "market.asta_trace": lambda a: AstaTraceOut(instrument_id=a["instrument"], status="no_model"),
    }


def test_untracked_preview_not_used_by_guard(journey_db):
    mcp = FakeMcp(_payloads(_journey("selected", segments=False), saved=False))
    out = JarvisPageService(journey_db, mcp, User()).portfolio("europe")
    assert out.pnl_source == "model_sleeves_preview" and out.perf.year_start == date(2026, 1, 1)
    assert out.required is None and "portfolio.required_return" not in mcp.names()
    pnl_args = [a for n, a in mcp.calls if n == "portfolio.pnl" and a.get("preview")]
    assert pnl_args and pnl_args[0]["segments"][0]["from"] == date(date.today().year, 1, 1).isoformat()


def test_tracking_runs_the_guard_with_s_and_goal(journey_db):
    j = _journey("tracking")
    mcp = FakeMcp(_payloads(j, saved=False))
    out = JarvisPageService(journey_db, mcp, User()).portfolio("europe")
    assert out.pnl_source == "model_sleeves" and out.required.status == "on_track"
    rr = next(a for n, a in mcp.calls if n == "portfolio.required_return")
    assert rr["year_start"] == S.isoformat() and rr["goal_return"] == 0.0775 and rr["ytd_return"] == 0.028
    t = target_to_date(0.0775, S, AS_OF)              # r = the annual goal, not target_return 0.0913
    rita = next(e for e in out.engines if e.engine == "rita")
    assert rita.model_based and rita.return_since == 0.021 and rita.target_to_date == pytest.approx(t)
    assert rita.gap == pytest.approx(0.021 - t) and rita.on_pace is (0.021 >= t)
    fno = next(e for e in out.engines if e.engine == "fno")
    assert not fno.model_based and fno.status == "levels_only" and fno.return_since is None
    assert next(e for e in out.engines if e.engine == "asta").status == "no_model"
    assert {i.instrument_id for i in out.instruments} == {"E1", "E2"}
    assert all(i.selected and not i.held and i.model_action == "full" for i in out.instruments)


def test_saved_portfolio_adds_held_row_and_rita_sleeves(journey_db):
    mcp = FakeMcp(_payloads(_journey("tracking"), saved=True))
    out = JarvisPageService(journey_db, mcp, User()).portfolio("europe")
    assert out.pnl_source == "mixed"
    sources = [a.get("source") for n, a in mcp.calls if n == "portfolio.pnl"]
    assert None in sources and "model_sleeves" in sources        # auto (held) + sleeves (RITA row)


def test_no_portfolio_no_selection_is_none(journey_db):
    mcp = FakeMcp(_payloads(None, saved=False))
    out = JarvisPageService(journey_db, mcp, User()).portfolio("europe")
    assert out.pnl_source == "none" and out.perf is None and out.required is None
    assert next(e for e in out.engines if e.engine == "rita").status == "none"


def test_state_live_holdings_from_sleeve_trace(journey_db):
    mcp = FakeMcp(_payloads(_journey("tracking"), saved=False))
    st = JarvisPageService(journey_db, mcp, User()).state("europe")
    assert [h.instrument_id for h in st.live_holdings] == ["E1", "E2"]
    h = st.live_holdings[0]
    assert h.model_action == "full" and h.invested_fraction == 1.0 and h.next_reset == date(2026, 12, 18)
    entry = [a.get("entry_date") for n, a in mcp.calls if n == "portfolio.sleeve_trace"]
    assert entry == [S.isoformat(), S.isoformat()]
    assert st.plan_stale is False and [c.text for c in st.chips][0] == "how am I doing"


# ── A6 levels per engine (rev 1 A2) ────────────────────────────────────────────

def _detail():
    d = [AS_OF - timedelta(days=k) for k in (5, 4, 3, 2, 1, 0)]
    mk = [MarkerOut(date=d[1], kind="entry", close=101.0, from_action="cash", to_action="full"),
          MarkerOut(date=d[3], kind="exit", close=99.0, from_action="full", to_action="cash"),
          MarkerOut(date=d[4], kind="entry", close=100.5, from_action="cash", to_action="half")]
    return SleeveDetailOut(dates=d, close=[100, 101, 100, 99, 100.5, 102], allocation=[0, 1, 1, 0, .5, .5],
                           hedged=[0] * 6, sleeve_value=[1, 1, 1.01, 1, 1, 1.02], sl_line=[.9] * 6,
                           episode_starts=[d[0]], markers=mk)


def test_instrument_levels_per_engine(journey_db, monkeypatch):
    from rita.services import goal_selection_service as gss

    monkeypatch.setattr(gss.GoalSelectionService, "universe", lambda self, loc: ["E1", "E2"])
    tr = trace("E1", as_of=AS_OF).model_copy(update={"detail": _detail(), "invested_fraction": 0.5,
                                                    "today_action": "half"})
    sig = SigmaLevelsOut(instrument_id="E1", currency="EUR", as_of=AS_OF, status="ok", last_close=102.0,
                         ann_vol_pct=18.0, monthly_sigma_pct=5.2, lookback_returns=252, anchor_close=102.0,
                         anchor_date=AS_OF, levels={"entry": 102.0, "plus_1sigma": 107.3, "minus_1sigma": 96.7},
                         closes=[{"date": AS_OF, "close": 102.0}],
                         monthly=[{"month": "2026-06", "anchor_close": 100.0, "plus_1sigma": 105.0,
                                   "minus_1sigma": 95.0, "ann_vol_pct": 18.0}])
    asta = AstaTraceOut(
        instrument_id="E1", status="ok", as_of=AS_OF, today_action="cash", since=S, return_since=0.04,
        last_signal={"date": AS_OF, "signal": "BUY", "setup": "s", "confidence": 0.7, "mandatory_met": 3,
                     "mandatory_total": 3, "optional_met": 1, "optional_total": 4, "stop_loss": 95.5,
                     "target": 110.0},
        detail={"dates": [AS_OF], "close": [102.0], "allocation": [0.0], "hedged": [0.0],
                "markers": [{"date": AS_OF - timedelta(days=9), "kind": "entry", "close": 98.0, "from_action": "cash",
                             "to_action": "full"},
                            {"date": AS_OF - timedelta(days=2), "kind": "exit", "close": 101.0, "from_action": "full",
                             "to_action": "cash"}], "signals": []})
    mcp = FakeMcp({**_payloads(_journey("tracking"), saved=False), "portfolio.sleeve_trace": tr,
                   "fno.sigma_levels": sig, "market.asta_trace": asta})
    out = JarvisPageService(journey_db, mcp, User()).instrument("europe", "e1")
    rita, fno, ast = out.engines
    assert rita.levels.entry.value == 100.5 and rita.levels.exit is None        # invested now → no exit
    assert rita.levels.stop_loss.value == tr.sl_level and "not a model output" in rita.levels.stop_loss.basis
    assert rita.levels.target is None and rita.series.sl_line == [0.9] * 6
    t = target_to_date(0.0775, S, AS_OF)
    assert rita.performance.target_to_date == pytest.approx(t)
    assert fno.status == "levels_only" and not fno.model_based
    assert (fno.levels.entry.value, fno.levels.stop_loss.value, fno.levels.target.value) == (102.0, 96.7, 107.3)
    assert fno.series.band_upper == [105.0] and fno.rationale.inputs[1].raw == 252
    assert ast.levels.entry.value == 98.0 and ast.levels.exit.value == 101.0     # in cash → exit shown
    assert (ast.levels.stop_loss.value, ast.levels.target.value) == (95.5, 110.0)
    assert "rule, not a model" in ast.levels.stop_loss.basis and ast.performance.return_since == 0.04
    trace_args = next(a for n, a in mcp.calls if n == "portfolio.sleeve_trace")
    assert trace_args["tolerance"] == "medium" and trace_args["detail"] is True


def test_unknown_instrument_is_not_found(journey_db, monkeypatch):
    from rita.services import goal_selection_service as gss

    monkeypatch.setattr(gss.GoalSelectionService, "universe", lambda self, loc: ["E1"])
    with pytest.raises(PageError) as e:
        JarvisPageService(journey_db, FakeMcp({}), User()).instrument("europe", "ZZZ")
    assert e.value.code == "not_found"


def test_experience_tier_never_writes():
    for f in (SRC / "api" / "experience" / "jarvis.py", SRC / "services" / "jarvis_page_service.py"):
        text = f.read_text(encoding="utf-8")
        assert not re.search(r"\.commit\(|\.add\(|upsert|\.delete\(", text), f
