"""``whatineed.*`` — What I Need tools (owner: ``services/retirement_plan_service.py``)."""
from __future__ import annotations

from rita.interfaces.tools._base import ToolContext, ToolError, ToolSpec
from rita.schemas.goal_selection import GoalOut
from rita.schemas.mcp_tools import (
    BucketInstrumentStatus,
    BucketStatus,
    BucketStatusIn,
    BucketStatusOut,
    GoalIn,
    WhatINeedPlanIn,
    WhatINeedPlanOut,
    WhatINeedPlanResult,
)


def get_plan(inp: WhatINeedPlanIn, ctx: ToolContext) -> WhatINeedPlanOut:
    from rita.services.retirement_plan_service import PlanValidationError, RetirementPlanService

    user = ctx.require_user()
    with ctx.session() as db:
        try:
            plan = RetirementPlanService(db).load_with_result(user.id, inp.location)
        except PlanValidationError as exc:
            raise ToolError("invalid_input", str(exc)) from exc
    res = plan.result
    return WhatINeedPlanOut(
        saved=plan.saved,
        location=plan.location,
        currency=plan.currency,
        updated_at=plan.updated_at,
        result=WhatINeedPlanResult(
            retire_age=res.at_ret.age,
            need_at_retire=res.at_ret.need,
            monthly_at_retire=res.at_ret.monthly,
            portfolio_at_retire=res.value,
            sustainable_until=res.with_investing.savings_out,
            portfolio_out_age=res.with_investing.portfolio_out,
        ),
    )


def get_goal(inp: GoalIn, ctx: ToolContext) -> GoalOut:
    """F44 P3: the signed-in user's goal (blended expected return, horizon, goal value)."""
    from rita.services.retirement_plan_service import PlanValidationError, RetirementPlanService

    user = ctx.require_user()
    with ctx.session() as db:
        try:
            return RetirementPlanService(db).goal(user.id, inp.location)
        except PlanValidationError as exc:
            raise ToolError("invalid_input", str(exc)) from exc


def bucket_status(inp: BucketStatusIn, ctx: ToolContext) -> BucketStatusOut:
    """F45 Phase D: per-bucket plan-vs-portfolio status (the What I Need tab's bucket table).

    Calls services only: a tool handler never opens a nested MCP session (ADR-007 — no extra thread /
    event loop on the 1 GB box).  The maths is ``compute_bucket_breakdown``, shared with the page."""
    from rita.services.bucket_status_service import AT_RISK_THRESHOLD, BucketStatusService
    from rita.services.retirement_plan_service import PlanValidationError

    user = ctx.require_user()
    with ctx.session() as db:
        try:
            plan, breakdown = BucketStatusService(db).status(user.id, inp.location)
        except PlanValidationError as exc:
            raise ToolError("invalid_input", str(exc)) from exc
    buckets = [
        BucketStatus(
            key=b.key, target_rate=b.target_rate, target_to_date=b.target_to_date,
            ytd_return=b.ytd_return, gap=b.gap, at_risk=b.at_risk, monthly_target=b.monthly_target,
            instruments=[BucketInstrumentStatus(instrument_id=i.instrument_id, allocation_pct=i.allocation_pct,
                                                ytd_return=i.ytd_return) for i in b.instruments],
        )
        for b in breakdown
    ]
    return BucketStatusOut(
        location=plan.location, currency=plan.currency, saved=plan.saved,
        at_risk_threshold=AT_RISK_THRESHOLD, n_buckets=len(buckets),
        n_at_risk=sum(1 for b in buckets if b.at_risk is True),
        n_on_track=sum(1 for b in buckets if b.at_risk is False),
        n_no_data=sum(1 for b in buckets if b.at_risk is None),
        buckets=buckets,
    )


def _bucket_text(out: BucketStatusOut) -> str:
    if not out.saved:
        return f"No saved What I Need plan for {out.location} — save the plan first."
    return (f"Buckets ({out.location}): {out.n_at_risk} at risk, {out.n_on_track} on track, "
            f"{out.n_no_data} without data.")


def _goal_text(out: GoalOut) -> str:
    if not out.saved or out.goal_return is None:
        return f"No saved What I Need goal for {out.location} — save the plan first."
    return (f"Goal ({out.location}, {out.currency}): {out.goal_return:.2%} a year"
            + (f" over {out.horizon_years:g} years" if out.horizon_years is not None else "") + ".")


def _text(out: WhatINeedPlanOut) -> str:
    src = "saved plan" if out.saved else "preset defaults"
    return (f"What I Need ({out.location}, {src}): retire at {out.result.retire_age}; "
            f"portfolio needed at retirement {out.result.portfolio_at_retire:,.0f} {out.currency}.")


TOOLS = [
    ToolSpec(
        name="whatineed.get_plan",
        description=(
            "The signed-in user's What I Need (retirement) plan for a location — saved plan or the "
            "location's preset defaults — with key results: retirement age, need and monthly at "
            "retirement, portfolio needed at retirement, and the ages savings / portfolio run out."
        ),
        input_model=WhatINeedPlanIn,
        output_model=WhatINeedPlanOut,
        handler=get_plan,
        auth=frozenset({"user"}),
        text=_text,
        summary=lambda o: f"saved={o.saved} location={o.location}",
    ),
    ToolSpec(
        name="whatineed.get_goal",
        description=(
            "The signed-in user's goal from the saved What I Need plan for a location: expected "
            "annual return (asset rates blended by their monthly amounts), horizon in years "
            "(retire age − current age), goal value (portfolio needed at retirement), and the "
            "asset rates. No saved plan → saved=false and nulls (presets are not a goal)."
        ),
        input_model=GoalIn,
        output_model=GoalOut,
        handler=get_goal,
        auth=frozenset({"user", "system"}),
        text=_goal_text,
        summary=lambda o: f"saved={o.saved} location={o.location}",
    ),
    ToolSpec(
        name="whatineed.bucket_status",
        description=(
            "How the signed-in user's saved portfolio is tracking against their What I Need plan, per "
            "asset bucket (index / equity / commodities / alternate): the bucket's return over the "
            "return period, the plan's annual rate pro-rated over the same period, the gap, and an "
            "at-risk flag when the gap is below the threshold. No saved plan → saved=false, no buckets. "
            "A bucket with no priced holdings has at_risk=null."
        ),
        input_model=BucketStatusIn,
        output_model=BucketStatusOut,
        handler=bucket_status,
        auth=frozenset({"user"}),
        text=_bucket_text,
        summary=lambda o: (f"saved={o.saved} buckets={o.n_buckets} at_risk={o.n_at_risk} "
                           f"on_track={o.n_on_track} no_data={o.n_no_data}"),
    ),
]
