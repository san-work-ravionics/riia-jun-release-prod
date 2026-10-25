"""``fno.*`` — FnO tools (owner: ``services/position_value_service.py``,
``services/hedge_plan_service.py``).

Lot sizes: neither tool takes nor returns a lot size; any lot size the services use comes from
``settings.instruments.*`` — never hardcoded (project.md §2).
"""
from __future__ import annotations

from rita.interfaces.tools._base import ToolContext, ToolError, ToolSpec
from rita.schemas.mcp_tools import NoArgsIn, PositionValueIn
from rita.schemas.position_value import PositionValueResponse
from rita.schemas.user_hedge_plan import HedgePlanOut


def position_value(inp: PositionValueIn, ctx: ToolContext) -> PositionValueResponse:
    from rita.services.position_value_service import PositionValueService

    user = ctx.require_user()
    with ctx.session() as db:
        return PositionValueService(db).build(user, inp.instrument, inp.months, inp.ann_vol_pct)


def get_hedge_plan(_inp: NoArgsIn, ctx: ToolContext) -> HedgePlanOut:
    from rita.services.hedge_plan_service import HedgePlanService

    user = ctx.require_user()
    with ctx.session() as db:
        plan = HedgePlanService(db).get_for_user(user)
    if plan is None:
        raise ToolError("not_found", "no saved hedge plan")
    return plan


TOOLS = [
    ToolSpec(
        name="fno.position_value",
        description=(
            "Monthly OHLC of the signed-in user's position value (shares x close, instrument "
            "currency) with ±1σ bands (entry / target / stop-loss levels), per holding or for one "
            "instrument. Same data as the FnO Exposure step candle card."
        ),
        input_model=PositionValueIn,
        output_model=PositionValueResponse,
        handler=position_value,
        auth=frozenset({"user"}),
        text=lambda o: f"Position value: {len(o.items)} instruments, as of {o.as_of or 'n/a'}.",
        summary=lambda o: f"items={len(o.items)} as_of={o.as_of}",
    ),
    ToolSpec(
        name="fno.get_hedge_plan",
        description="The signed-in user's saved FnO hedge plan. not_found if none is saved.",
        input_model=NoArgsIn,
        output_model=HedgePlanOut,
        handler=get_hedge_plan,
        auth=frozenset({"user"}),
        text=lambda o: (f"Hedge plan: {len(o.hedged_ids)} hedged instruments, "
                        f"coverage {o.coverage}%, step {o.last_step}."),
        summary=lambda o: f"hedged={len(o.hedged_ids)}",
    ),
]
