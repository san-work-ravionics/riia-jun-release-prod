"""F45 Phase D — the chat tool and the What I Need page must show the same bucket numbers.

``BucketStatusService`` (the ``whatineed.bucket_status`` tool, services only) and
``JarvisPageService._bucket_breakdown`` (the A7 page, built from ``portfolio()`` over MCP tools) pick
their performance period and held rows independently.  This seeds a real plan, a saved portfolio and
prices, routes the page's MCP calls to the real services, and asserts the two agree — so a change to
either selection logic that makes them drift fails here.
"""
# ruff: noqa: F811 — pytest fixtures imported from a sibling module are redefined as test params
from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from rita.interfaces.mcp_client import McpCallError, ToolCallResult
from rita.models.user import UserModel
from rita.services.bucket_status_service import BucketStatusService
from rita.services.jarvis_page_service import JarvisPageService
from rita.services.journey_service import JourneyService
from rita.services.portfolio_pnl_service import PnlError, PortfolioPnlService
from rita.services.retirement_plan_service import RetirementPlanService, default_plan

from .f44_p4_helpers import journey_db  # noqa: F401 — fixture used by pnl_db
from .test_f44_p4_pnl import DATES, FakeGoal, _closes, _portfolio, pnl_db  # noqa: F401 — fixtures/helpers


class RealServicesMcp:
    """The tools the page's ``portfolio()`` calls, answered by the real services (no network, no server).
    Anything else (traces, ASTA, required return) is ``not_found`` — the page degrades the same way in prod
    when a model is missing."""

    def __init__(self, db, user_id: str):
        self.db, self.user_id = db, user_id

    def call(self, name, args=None):
        args = args or {}
        loc = args.get("location")
        if name == "journey.get_current":
            out = JourneyService(self.db).get_current(self.user_id, loc)
        elif name == "whatineed.get_goal":
            out = RetirementPlanService(self.db).goal(self.user_id, loc)
        elif name == "portfolio.pnl":
            try:
                out = PortfolioPnlService(self.db, goal=FakeGoal({})).pnl(
                    self.user_id, loc, args.get("goal_return"), args.get("source", "auto"))
            except PnlError as exc:
                raise McpCallError(name, exc.code, exc.message, "c") from exc
        else:
            out = None
        if out is None:
            raise McpCallError(name, "not_found", "none", "c")
        return ToolCallResult(name=name, structured=out.model_dump(mode="json"), text="", call_id="c")


def _rows(breakdown):
    return [(b.key, b.target_rate, b.target_to_date, b.ytd_return, b.gap, b.at_risk, b.monthly_target,
             [(i.instrument_id, i.allocation_pct, i.ytd_return) for i in b.instruments])
            for b in breakdown]


@pytest.fixture
def seeded(pnl_db):
    db = pnl_db
    n = len(DATES)
    _closes(db, "E1", 100 * np.cumprod(1 + np.full(n, 0.0004)))      # equity, rising
    _closes(db, "BANKNIFTY", 100 * np.cumprod(1 + np.full(n, -0.0003)))  # index, falling
    _portfolio(db, "p1", date(2026, 3, 2), [
        {"instrument_id": "E1", "allocation_pct": 50, "shares": 10, "cash": 0.0},
        {"instrument_id": "BANKNIFTY", "allocation_pct": 50, "shares": 5, "cash": 0.0},
    ])
    plan = RetirementPlanService(db).save("alice", default_plan("europe").inputs, "europe")
    return db, plan


def test_chat_tool_and_page_agree_on_every_bucket(seeded):
    db, plan = seeded
    tool_plan, tool_rows = BucketStatusService(db).status("alice", "europe")
    page_rows = JarvisPageService(db, RealServicesMcp(db, "alice"), UserModel(id="alice"))._bucket_breakdown(
        "europe", plan.inputs)

    assert tool_plan.saved
    assert _rows(tool_rows) == _rows(page_rows)

    # not vacuous: both buckets have priced holdings and a measured period
    by = {b.key: b for b in tool_rows}
    assert by["eq"].ytd_return is not None and by["idx"].ytd_return is not None
    assert by["eq"].target_to_date > 0 and by["eq"].at_risk is not None
    assert [i.instrument_id for i in by["idx"].instruments] == ["BANKNIFTY"]
    assert by["idx"].ytd_return < 0 < by["eq"].ytd_return
    assert by["com"].instruments == [] and by["com"].at_risk is None


def test_no_saved_plan_gives_no_buckets(pnl_db):
    plan, rows = BucketStatusService(pnl_db).status("alice", "europe")
    assert plan.saved is False and rows == []
