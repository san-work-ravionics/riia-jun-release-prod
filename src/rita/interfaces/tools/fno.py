"""``fno.*`` — FnO tools (owner: ``services/position_value_service.py``,
``services/hedge_plan_service.py``).

Lot sizes: neither tool takes nor returns a lot size; any lot size the services use comes from
``settings.instruments.*`` — never hardcoded (project.md §2).
"""
from __future__ import annotations

from rita.interfaces.tools._base import ToolContext, ToolError, ToolSpec
from rita.schemas.jarvis import SigmaLevelsOut
from rita.schemas.mcp_tools import NoArgsIn, PositionValueIn, SigmaLevelsIn
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


def sigma_levels(inp: SigmaLevelsIn, ctx: ToolContext) -> SigmaLevelsOut:
    """F44 P4: ±1σ monthly levels for one instrument (statistical, not a model; no user)."""
    from rita.services.position_value_service import PositionValueService

    with ctx.session() as db:
        return PositionValueService(db).sigma_levels(inp.instrument, inp.months)


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
    ToolSpec(
        name="fno.sigma_levels",
        description=(
            "±1σ monthly price levels for one instrument from the last 252 daily returns "
            "(entry anchor = last close, +1σ target, −1σ stop loss), per month and today. "
            "Statistical bands, not a model. No user data."
        ),
        input_model=SigmaLevelsIn,
        output_model=SigmaLevelsOut,
        handler=sigma_levels,
        auth=frozenset({"none"}),
        stdio=True,
        text=lambda o: f"{o.instrument_id} σ levels: {o.status}, as of {o.as_of or 'n/a'}.",
        summary=lambda o: f"status={o.status} months={len(o.monthly)}",
    ),
]
