"""``whatineed.*`` — What I Need tools (owner: ``services/retirement_plan_service.py``)."""
from __future__ import annotations

from rita.interfaces.tools._base import ToolContext, ToolError, ToolSpec
from rita.schemas.goal_selection import GoalOut
from rita.schemas.mcp_tools import GoalIn, WhatINeedPlanIn, WhatINeedPlanOut, WhatINeedPlanResult


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
]
