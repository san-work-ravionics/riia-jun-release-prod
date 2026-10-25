"""``portfolio.*`` — Portfolio Builder tools (owner: ``services/user_portfolio_service.py``,
``services/optimal_allocation_service.py`` over ``core/portfolio_optimizer.py``)."""
from __future__ import annotations

from rita.interfaces.tools._base import ToolContext, ToolError, ToolSpec
from rita.schemas.mcp_tools import (
    OptimalAllocationIn,
    PortfolioHoldingOut,
    PortfolioHoldingsIn,
    PortfolioHoldingsOut,
)
from rita.schemas.portfolio_optimizer import OptimalAllocationResponse

def get_holdings(inp: PortfolioHoldingsIn, ctx: ToolContext) -> PortfolioHoldingsOut:
    """F44 P2: currency / location / total_value / cash from the saved portfolio (legacy rows:
    EUR, no location, ``total_value_eur`` / ``cash_eur``)."""
    from rita.services.user_portfolio_service import UserPortfolioService

    user = ctx.require_user()
    with ctx.session() as db:
        pf = UserPortfolioService(db).get(user.id, inp.location)
    if pf is None:
        raise ToolError("not_found", "no saved portfolio")
    return PortfolioHoldingsOut(
        portfolio_id=pf.portfolio_id,
        name=pf.name,
        currency=pf.currency,
        location=pf.location,
        total_value=pf.total_value,
        holdings=[
            PortfolioHoldingOut(
                instrument_id=h.instrument_id, allocation_pct=h.allocation_pct,
                shares=h.shares, cash=h.cash,
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
            "The signed-in user's active saved portfolio for a location (europe | india | us; omit = "
            "the most recently saved): holdings (instrument, allocation %, whole shares, leftover "
            "cash), total value, currency and location. Amounts are in the portfolio currency. "
            "not_found if none is saved."
        ),
        input_model=PortfolioHoldingsIn,
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
