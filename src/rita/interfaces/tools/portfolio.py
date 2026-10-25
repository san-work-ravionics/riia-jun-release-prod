"""``portfolio.*`` — Portfolio Builder tools (owner: ``services/user_portfolio_service.py``,
``services/optimal_allocation_service.py`` over ``core/portfolio_optimizer.py``)."""
from __future__ import annotations

from rita.interfaces.tools._base import ToolContext, ToolError, ToolSpec
from rita.schemas.mcp_tools import (
    NoArgsIn,
    OptimalAllocationIn,
    PortfolioHoldingOut,
    PortfolioHoldingsOut,
)
from rita.schemas.portfolio_optimizer import OptimalAllocationResponse

# P1: every saved portfolio is a legacy EUR portfolio (no location yet).  P2 adds currency +
# location columns and this tool reads them (Spec_DB § F44).
_P1_CURRENCY = "EUR"


def get_holdings(_inp: NoArgsIn, ctx: ToolContext) -> PortfolioHoldingsOut:
    from rita.services.user_portfolio_service import UserPortfolioService

    user = ctx.require_user()
    with ctx.session() as db:
        pf = UserPortfolioService(db).get(user.id)
    if pf is None:
        raise ToolError("not_found", "no saved portfolio")
    return PortfolioHoldingsOut(
        portfolio_id=pf.portfolio_id,
        name=pf.name,
        currency=_P1_CURRENCY,
        location=None,
        total_value=pf.total_value_eur,
        holdings=[
            PortfolioHoldingOut(
                instrument_id=h.instrument_id, allocation_pct=h.allocation_pct,
                shares=h.shares, cash=h.cash_eur,
            )
            for h in pf.holdings
        ],
        updated_at=pf.updated_at,
    )


def optimal_allocation(inp: OptimalAllocationIn, ctx: ToolContext) -> OptimalAllocationResponse:
    from rita.services.optimal_allocation_service import OptimalAllocationService

    with ctx.session() as db:
        return OptimalAllocationService(db).allocate(inp.horizon)


TOOLS = [
    ToolSpec(
        name="portfolio.get_holdings",
        description=(
            "The signed-in user's active saved portfolio: holdings (instrument, allocation %, "
            "whole shares, leftover cash), total value and currency. not_found if none is saved."
        ),
        input_model=NoArgsIn,
        output_model=PortfolioHoldingsOut,
        handler=get_holdings,
        auth=frozenset({"user", "system"}),
        text=lambda o: (f"Portfolio '{o.name}': {len(o.holdings)} holdings"
                        + (f", total {o.total_value:,.0f} {o.currency}" if o.total_value else "") + "."),
        summary=lambda o: f"holdings={len(o.holdings)}",
    ),
    ToolSpec(
        name="portfolio.optimal_allocation",
        description=(
            "Optimal integer-percentage allocation over the available instruments for an investment "
            "horizon (CP-SAT solver on Sharpe / max drawdown). Same result as the RITA Portfolio "
            "Builder's optimal allocation."
        ),
        input_model=OptimalAllocationIn,
        output_model=OptimalAllocationResponse,
        handler=optimal_allocation,
        auth=frozenset({"none"}),
        stdio=True,
        text=lambda o: (f"Optimal allocation ({o.horizon}): {o.solver_status}, "
                        f"{len(o.allocations)} instruments, est. Sharpe {o.estimated_sharpe:.2f}."),
        summary=lambda o: f"solver_status={o.solver_status} allocations={len(o.allocations)}",
    ),
]
