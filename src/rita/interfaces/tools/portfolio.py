"""``portfolio.*`` — Portfolio Builder tools (owner: ``services/user_portfolio_service.py``,
``services/optimal_allocation_service.py`` over ``core/portfolio_optimizer.py``) and the F44 P3
goal-driven selection tools (owner: ``services/goal_selection_service.py``).

The three P3 tools (``select_for_goal``, ``required_return``, ``model_runs``) take no user data:
they answer for a signed-in user or the system identity and never call ``ctx.require_user()``."""
from __future__ import annotations

from rita.interfaces.tools._base import ToolContext, ToolError, ToolSpec
from rita.schemas.goal_selection import GoalSelectionOut, ModelRunsOut, RequiredReturnOut
from rita.schemas.jarvis import PnlOut, SleeveTraceOut
from rita.schemas.mcp_tools import (
    ModelRunsIn,
    PnlIn,
    SleeveTraceIn,
    OptimalAllocationIn,
    PortfolioHoldingOut,
    PortfolioHoldingsIn,
    PortfolioHoldingsOut,
    RequiredReturnIn,
    SelectForGoalIn,
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


def _goal_call(fn):
    """Run a GoalSelectionService call with the coded errors mapped to ToolError."""
    from rita.services.goal_selection_service import GoalSelectionError

    try:
        return fn()
    except GoalSelectionError as exc:
        raise ToolError(exc.code, exc.message) from exc


def select_for_goal(inp: SelectForGoalIn, ctx: ToolContext) -> GoalSelectionOut:
    from rita.services.goal_selection_service import GoalSelectionService

    with ctx.session() as db:
        return _goal_call(lambda: GoalSelectionService(db).select_for_goal(
            inp.location, inp.target_return, inp.as_of))


def required_return(inp: RequiredReturnIn, ctx: ToolContext) -> RequiredReturnOut:
    from rita.services.goal_selection_service import GoalSelectionService

    with ctx.session() as db:
        return _goal_call(lambda: GoalSelectionService(db).required_return(
            inp.location, inp.goal_return, inp.ytd_return, inp.as_of, inp.year_start,
            inp.reselections_used))


def model_runs(inp: ModelRunsIn, ctx: ToolContext) -> ModelRunsOut:
    from rita.services.goal_selection_service import GoalSelectionService

    with ctx.session() as db:
        return _goal_call(lambda: GoalSelectionService(db).model_runs(inp.location))


def pnl(inp: PnlIn, ctx: ToolContext) -> PnlOut:
    """F44 P4: the user's ytd path over [year_start, as_of] — saved portfolio on the days one was
    active, else the journey segments' model sleeves (rev 3), chained; ``target_to_date`` (B2)."""
    from rita.services.portfolio_pnl_service import PnlError, PortfolioPnlService

    user = ctx.require_user()
    segs = [s.model_dump(by_alias=True) for s in inp.segments] if inp.segments else None

    def run():
        try:
            return PortfolioPnlService(db).pnl(user.id, inp.location, inp.goal_return, inp.source,
                                               inp.year_start, segs, inp.preview)
        except PnlError as exc:
            raise ToolError(exc.code, exc.message) from exc

    with ctx.session() as db:
        return _goal_call(run)


def sleeve_trace(inp: SleeveTraceIn, ctx: ToolContext) -> SleeveTraceOut:
    """F44 P4: one instrument's DDQN v2 sleeve (P3 cache), SL and model inputs — no user data."""
    from rita.services.sleeve_trace_service import SleeveTraceService

    with ctx.session() as db:
        return _goal_call(lambda: SleeveTraceService(db).trace(
            inp.location, inp.instrument, inp.tolerance, inp.entry_date, inp.since, inp.detail))


def _selection_text(o: GoalSelectionOut) -> str:
    if o.holdings:
        mix = ", ".join(f"{h.instrument_id} {h.allocation_pct}%" for h in o.holdings)
        verdict = "meets the goal" if o.meets_goal else "falls short on the test window"
        return (f"Goal {o.target_return:.2%} ({o.location}): {mix} at tolerance {o.tolerance}; "
                f"test return {o.test_return:.2%} — {verdict}. Weights come from a min-variance "
                f"solver over the DDQN sleeves, not from a model.")
    return (f"Goal {o.target_return:.2%} ({o.location}) cannot be reached on the fit window; "
            f"best mix reaches {o.cap_fit:.2%} (fit) / {o.cap_test:.2%} (test).")


def _required_text(o: RequiredReturnOut) -> str:
    rp = "n/a" if o.required_return is None else f"{o.required_return:.2%}"
    return f"Required return for the rest of the year {rp}: {o.status} ({o.reason})."


def _model_runs_text(o: ModelRunsOut) -> str:
    return (f"{o.location}: {len(o.instruments)} model-managed instruments ({o.lineage}), "
            f"{len(o.excluded)} excluded, as of {o.as_of}.")


_GOAL_AUTH = frozenset({"user", "system"})

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
    ToolSpec(
        name="portfolio.select_for_goal",
        description=(
            "Goal-driven selection for a location (europe | india | us) and an annual target "
            "return: each instrument's own RITA DDQN v2 policy is replayed after its training "
            "window at every trained risk tolerance; the least-risk (min-variance) mix of those "
            "model-managed sleeves whose return on the lineage's val years (fit) is at least the "
            "target is proposed, and judged on the lineage's backtest window (test). Weights come "
            "from the solver, not from a model (see `method`). Holdings carry the model's action "
            "today and the sleeve-drawdown stop loss. Can't reach → `closest` and the caps."
        ),
        input_model=SelectForGoalIn,
        output_model=GoalSelectionOut,
        handler=select_for_goal,
        auth=_GOAL_AUTH,
        text=_selection_text,
        summary=lambda o: (f"meets_goal={o.meets_goal} holdings={len(o.holdings)} "
                           f"excluded={len(o.excluded)}"),
    ),
    ToolSpec(
        name="portfolio.required_return",
        description=(
            "Stop-loss response for an annual goal: from the goal return, the return since the "
            "year start and today's close, the rest-of-year return still needed and its "
            "annualised target r′; then the agreed guard — year end, on track, re-selection count, "
            "the fit cap — and, when allowed, a re-selection at r′ (`proposal`). A re-selection "
            "is counted only when one is proposed (`reselections_next`)."
        ),
        input_model=RequiredReturnIn,
        output_model=RequiredReturnOut,
        handler=required_return,
        auth=_GOAL_AUTH,
        text=_required_text,
        summary=lambda o: f"status={o.status} reason={o.reason}",
    ),
    ToolSpec(
        name="portfolio.model_runs",
        description=(
            "Evidence behind a goal-driven pick for a location: per instrument and trained risk "
            "tolerance, the DDQN v2 replay's fit (val years) and test (backtest) annual return, "
            "volatility, max drawdown and Sharpe (instrument risk-free rate), bars outside the "
            "training drawdown limit, and the model's action today; plus the exclusions."
        ),
        input_model=ModelRunsIn,
        output_model=ModelRunsOut,
        handler=model_runs,
        auth=_GOAL_AUTH,
        text=_model_runs_text,
        summary=lambda o: f"instruments={len(o.instruments)} excluded={len(o.excluded)}",
    ),
    ToolSpec(
        name="portfolio.pnl",
        description=(
            "The signed-in user's return this plan year for a location: the saved portfolio's "
            "value path on the days one was active, else the journey's RITA model sleeves "
            "(buy-and-drift per segment), chained over [year_start, as_of]; the goal's target "
            "path to date; and, for a saved portfolio, the money figures in its currency. "
            "not_found when there is no saved portfolio and no segments."
        ),
        input_model=PnlIn,
        output_model=PnlOut,
        handler=pnl,
        auth=_GOAL_AUTH,
        text=lambda o: f"P&L {o.location} ({o.source}) since {o.year_start}, as of {o.as_of}.",
        summary=lambda o: f"source={o.source} points={len(o.series)} holdings={len(o.holdings)}",
    ),
    ToolSpec(
        name="portfolio.sleeve_trace",
        description=(
            "One instrument's RITA DDQN v2 sleeve for a location: the model's action today, its "
            "entries / exits (action changes), the sleeve-drawdown stop loss (training limit "
            "hard_mdd_limit from the peak since entry / episode start — a config input, not a "
            "model output), the next episode reset, and with detail the chart series and the "
            "model inputs (observation) behind the last action."
        ),
        input_model=SleeveTraceIn,
        output_model=SleeveTraceOut,
        handler=sleeve_trace,
        auth=_GOAL_AUTH,
        text=lambda o: (f"{o.instrument_id}: {o.status}"
                        + (f", model today {o.today_action}" if o.today_action else "") + "."),
        summary=lambda o: f"status={o.status} detail={o.detail is not None}",
    ),
]
