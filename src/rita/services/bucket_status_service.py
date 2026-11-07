"""F45: per-bucket plan-vs-portfolio status (idx / eq / com / alt).

Two parts:

* ``compute_bucket_breakdown`` — the pure maths, shared by the What I Need page
  (``JarvisPageService``) and the ``whatineed.bucket_status`` tool.
* ``BucketStatusService`` — a **DB-only** reader for the tool.  It calls services directly and never
  opens an MCP session: ADR-007 forbids a tool handler from nesting one (an extra thread and event
  loop per call on the 1 GB box).

The return period is the one the portfolio's returns cover (``perf.year_start`` .. ``perf.as_of``), and
the plan's annual rate is pro-rated over that same period.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import structlog
from sqlalchemy.orm import Session

from rita.schemas.jarvis import BucketBreakdownOut, BucketInstrumentOut

log = structlog.get_logger(__name__)

AT_RISK_THRESHOLD = -0.02
INDEX_INSTRUMENTS = {"NIFTY50", "BANKNIFTY", "NIFTYMIDCAP50", "FINNIFTY", "NIFTY_FIN_SERVICE"}
COMMODITY_INSTRUMENTS = {"GOLDM", "SILVERM", "GOLD", "SILVER", "CRUDEOIL", "NATURALGAS"}
ALT_INSTRUMENTS = {"BITCOIN", "ETH", "REIT"}
TRACKED = ("tracking", "reselect_proposed", "back_to_plan")


def classify_bucket(instrument_id: str) -> str:
    uid = instrument_id.upper()
    if uid in INDEX_INSTRUMENTS:
        return "idx"
    if uid in COMMODITY_INSTRUMENTS:
        return "com"
    if uid in ALT_INSTRUMENTS:
        return "alt"
    return "eq"


def compute_bucket_breakdown(instruments: list[Any], perf: Any, plan_inputs: Any,
                             today: date | None = None) -> list[BucketBreakdownOut]:
    """``instruments``: items with ``instrument_id``, ``allocation_pct`` and ``ret`` (return over the
    period).  ``perf``: anything with ``year_start`` and ``as_of`` (or None → calendar year to today)."""
    # The target must cover the SAME period as the actual returns (the later of 1 Jan and the
    # portfolio's save date, to the latest close) — not 1 Jan to today.
    if perf is not None and perf.year_start is not None and perf.as_of is not None:
        period_start, period_end = perf.year_start, perf.as_of
    else:
        today = today or date.today()
        period_start, period_end = date(today.year, 1, 1), today
    elapsed_fraction = max(0, (period_end - period_start).days) / 365.0

    bucket_map: dict[str, list[Any]] = {"idx": [], "eq": [], "com": [], "alt": []}
    for inst in instruments:
        bucket_map[classify_bucket(inst.instrument_id)].append(inst)

    bucket_config = [
        ("idx", plan_inputs.idx_rate, plan_inputs.idx_monthly),
        ("eq", plan_inputs.eq_rate, plan_inputs.eq_monthly),
        ("com", plan_inputs.com_rate, plan_inputs.com_monthly),
        ("alt", plan_inputs.alt_rate, plan_inputs.alt_monthly),
    ]

    result: list[BucketBreakdownOut] = []
    for key, rate, monthly in bucket_config:
        if rate is None:
            continue
        insts = bucket_map.get(key, [])
        inst_outs = [
            BucketInstrumentOut(instrument_id=i.instrument_id, allocation_pct=i.allocation_pct, ytd_return=i.ret)
            for i in insts
        ]
        total_w = sum(i.allocation_pct for i in insts if i.allocation_pct is not None and i.ret is not None)
        if total_w > 0:
            ytd: float | None = sum(
                i.ret * i.allocation_pct for i in insts if i.allocation_pct is not None and i.ret is not None
            ) / total_w
        else:
            ytd = None

        ttd = rate * elapsed_fraction
        gap = (ytd - ttd) if ytd is not None else None
        # No elapsed days = nothing measured yet: neither on track nor at risk.
        at_risk = (gap < AT_RISK_THRESHOLD) if (gap is not None and elapsed_fraction > 0) else None

        result.append(BucketBreakdownOut(
            key=key, target_rate=rate, target_to_date=ttd, ytd_return=ytd, gap=gap, at_risk=at_risk,
            monthly_target=monthly, instruments=inst_outs,
        ))
    return result


class _Held:
    """One instrument row for ``compute_bucket_breakdown``."""

    def __init__(self, instrument_id: str, allocation_pct: float | None, ret: float | None) -> None:
        self.instrument_id = instrument_id
        self.allocation_pct = allocation_pct
        self.ret = ret


class BucketStatusService:
    """The tool's reader: plan + the portfolio's period returns, straight from services."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def status(self, user_id: str, location: str):
        """``(plan, breakdown)``; ``breakdown`` is ``[]`` when no plan is saved."""
        from rita.services.retirement_plan_service import RetirementPlanService

        plans = RetirementPlanService(self._db)
        plan = plans.load(user_id, location)
        if not plan.saved:
            return plan, []
        goal = plans.goal(user_id, location)
        perf, instruments = self._portfolio(user_id, location, goal.goal_return if goal.saved else None)
        return plan, compute_bucket_breakdown(instruments, perf, plan.inputs)

    def _portfolio(self, user_id: str, location: str, plan_goal_return: float | None):
        """The portfolio's period performance and held rows, chosen as ``JarvisPageService.portfolio``
        chooses them: tracked journey → its segments; else the saved portfolio; else a selection preview."""
        from rita.services.jarvis_page_service import JarvisPageService, _open_mix
        from rita.services.journey_service import JourneyService
        from rita.services.portfolio_pnl_service import PnlError, PortfolioPnlService

        j = JourneyService(self._db).get_current(user_id, location)
        r = j.goal_return if j is not None and j.goal_return is not None else plan_goal_return
        tracked = j is not None and j.state in TRACKED and bool(j.segments)
        pnl_svc = PortfolioPnlService(self._db)

        def run(**kw):
            try:
                return pnl_svc.pnl(user_id, location, r, **kw)
            except PnlError:
                return None

        if tracked:
            perf = run(year_start=j.plan_year_start, segments=JarvisPageService._segments(j))
        else:
            perf = run(source="saved")
            if j is not None and j.selection is not None and j.selection.holdings and perf is None:
                perf = run(source="model_sleeves", preview=True, segments=JarvisPageService._preview_segment(j))

        held_ret: dict[str, float | None] = {}
        held_ids: list[str] = []
        if perf is not None and perf.money is not None:
            held_ids = [h.instrument_id for h in perf.money.holdings]
            held_ret = {h.instrument_id: h.return_since for h in perf.holdings}
        mix = {inst: pct for inst, pct, _tau in _open_mix(j)}
        alloc = {h.instrument_id: h.allocation_pct for h in (perf.holdings if perf is not None else [])}
        rows = [_Held(inst, mix[inst] if inst in mix else alloc.get(inst), held_ret.get(inst))
                for inst in dict.fromkeys([*held_ids, *mix])]
        return perf, rows
