"""Core portfolio optimization engine using OR-Tools CP-SAT solver (F34 Phase 1).

Given a set of instruments with Sharpe ratios and MDD values (from model training
history or proxy estimates from price data), solves for optimal integer-percentage
allocations that maximize weighted portfolio Sharpe while respecting budget,
diversification, Sharpe floor, and MDD ceiling constraints.

Formulation:
    Maximize   sum(w_i * sharpe_i)
    Subject to:
        sum(w_i) = 100                           (budget)
        w_i >= MIN_ALLOC  for all i               (min allocation)
        w_i <= MAX_ALLOC  for all i               (max allocation)
        sum(w_i * sharpe_i) / 100 >= SHARPE_FLOOR  (portfolio Sharpe floor)
        sum(w_i * |mdd_i|) / 100 <= MDD_CEILING    (portfolio |MDD| ceiling)

Note: Portfolio MDD is approximated as weighted-average MDD (ignoring correlation).
This is acceptable for a guided exploration tool per eng-context.md.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd
import structlog

from rita.config import settings
from rita.core.data_loader import load_instrument_data
from rita.core.investment_horizons import INVESTMENT_HORIZONS
from rita.schemas.portfolio_optimizer import AllocationItem, OptimalAllocationResponse

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Module-level constants — no inline magic numbers
# ---------------------------------------------------------------------------

MIN_ALLOC: int = 5
MAX_ALLOC: int = 60
MAX_INSTRUMENTS: int = 7
SHARPE_SCALE: int = 1000
MDD_SCALE: int = 100
SOLVER_TIME_LIMIT_MS: int = 200


# ---------------------------------------------------------------------------
# Metric helpers
# ---------------------------------------------------------------------------

def _load_training_history(instrument: str) -> pd.DataFrame | None:
    """Load training_history.csv for an instrument, or return None if absent/empty."""
    history_path = Path(settings.model.path) / instrument.upper() / "training_history.csv"
    if not history_path.exists():
        return None
    try:
        df = pd.read_csv(str(history_path))
        if df.empty:
            return None
        return df
    except Exception as exc:
        log.warning(
            "portfolio_optimizer.training_history_load_failed",
            instrument=instrument,
            error=str(exc),
        )
        return None


def _best_model_metrics(df: pd.DataFrame) -> tuple[float, float, str]:
    """Extract best Sharpe and corresponding MDD from training history.

    Prefers runs where backtest_constraints_met is True.
    Returns (sharpe, mdd_pct, metric_source).
    """
    # Prefer constrained runs
    if "backtest_constraints_met" in df.columns:
        constrained = df[df["backtest_constraints_met"] == True]  # noqa: E712
        if not constrained.empty and "backtest_sharpe" in constrained.columns:
            best_idx = constrained["backtest_sharpe"].idxmax()
            row = constrained.loc[best_idx]
            return (
                float(row["backtest_sharpe"]),
                float(row.get("backtest_mdd_pct", 0.0)),
                "model",
            )

    # Fall back to best Sharpe across all runs
    if "backtest_sharpe" in df.columns and not df["backtest_sharpe"].isna().all():
        best_idx = df["backtest_sharpe"].idxmax()
        row = df.loc[best_idx]
        return (
            float(row["backtest_sharpe"]),
            float(row.get("backtest_mdd_pct", 0.0)),
            "model",
        )

    return (0.0, 0.0, "model")


def _proxy_sharpe_from_prices(df: pd.DataFrame, lookback_td: int) -> float:
    """Compute annualized Sharpe ratio from daily returns as a proxy.

    Sharpe = (annualized_return) / (annualized_volatility)
    Uses the most recent `lookback_td` trading days.
    """
    closes = df["Close"].dropna()
    if len(closes) < max(20, lookback_td):
        closes = closes.tail(max(20, len(closes)))
    else:
        closes = closes.tail(lookback_td)

    daily_returns = closes.pct_change().dropna()
    if len(daily_returns) < 10:
        return 0.0

    mean_daily = float(daily_returns.mean())
    std_daily = float(daily_returns.std())
    if std_daily < 1e-10:
        return 0.0

    annualized_return = mean_daily * 252
    annualized_vol = std_daily * math.sqrt(252)
    return round(annualized_return / annualized_vol, 4)


def _proxy_mdd_from_prices(df: pd.DataFrame, lookback_td: int) -> float:
    """Compute max drawdown percentage from close prices over the lookback period.

    Returns a negative number (e.g. -15.2 for a 15.2% drawdown).
    """
    closes = df["Close"].dropna()
    if len(closes) < max(20, lookback_td):
        closes = closes.tail(max(20, len(closes)))
    else:
        closes = closes.tail(lookback_td)

    if len(closes) < 2:
        return 0.0

    prices = closes.values.astype(float)
    peak = prices[0]
    max_dd = 0.0
    for price in prices[1:]:
        if price > peak:
            peak = price
        dd = (price - peak) / peak
        if dd < max_dd:
            max_dd = dd

    return round(max_dd * 100, 2)  # e.g. -15.2


def _get_instrument_metrics(
    instrument_id: str,
    instrument_name: str,
    ticker: str,
    lookback_td: int,
) -> dict[str, Any] | None:
    """Get Sharpe and MDD for an instrument, from model or proxy.

    Returns None if the instrument cannot be evaluated (e.g. no price data).
    """
    # Try model metrics first
    history_df = _load_training_history(instrument_id)
    if history_df is not None:
        sharpe, mdd_pct, source = _best_model_metrics(history_df)
        if sharpe != 0.0 or mdd_pct != 0.0:
            return {
                "instrument_id": instrument_id,
                "instrument_name": instrument_name,
                "ticker": ticker,
                "sharpe": sharpe,
                "mdd_pct": mdd_pct,
                "metric_source": source,
            }

    # Fall back to proxy metrics from price data
    try:
        price_df = load_instrument_data(instrument_id)
    except Exception as exc:
        log.warning(
            "portfolio_optimizer.price_data_unavailable",
            instrument=instrument_id,
            error=str(exc),
        )
        return None

    if price_df.empty or len(price_df) < 20:
        log.warning(
            "portfolio_optimizer.insufficient_price_data",
            instrument=instrument_id,
            rows=len(price_df),
        )
        return None

    sharpe = _proxy_sharpe_from_prices(price_df, lookback_td)
    mdd_pct = _proxy_mdd_from_prices(price_df, lookback_td)

    return {
        "instrument_id": instrument_id,
        "instrument_name": instrument_name,
        "ticker": ticker,
        "sharpe": sharpe,
        "mdd_pct": mdd_pct,
        "metric_source": "proxy",
    }


# ---------------------------------------------------------------------------
# CP-SAT solver
# ---------------------------------------------------------------------------

def _solve_allocation(
    instruments: list[dict[str, Any]],
    sharpe_floor: float,
    mdd_ceiling: float,
) -> tuple[str, list[tuple[int, int]]]:
    """Run the CP-SAT solver on a list of instrument metrics.

    Returns (solver_status, [(instrument_index, allocation_pct), ...]).
    """
    from ortools.sat.python import cp_model

    n = len(instruments)
    model = cp_model.CpModel()

    # Decision variables: w_i in [MIN_ALLOC, MAX_ALLOC]
    weights = [model.new_int_var(MIN_ALLOC, MAX_ALLOC, f"w_{i}") for i in range(n)]

    # Constraint 1: Budget — sum(w_i) == 100
    model.add(sum(weights) == 100)

    # Scale Sharpe values for integer domain
    scaled_sharpes = [int(round(inst["sharpe"] * SHARPE_SCALE)) for inst in instruments]

    # Scale absolute MDD values for integer domain
    scaled_abs_mdds = [int(round(abs(inst["mdd_pct"]) * MDD_SCALE)) for inst in instruments]

    # Constraint 2: Sharpe floor — sum(w_i * scaled_sharpe_i) >= 100 * sharpe_floor * SHARPE_SCALE
    sharpe_floor_scaled = int(round(100 * sharpe_floor * SHARPE_SCALE))
    model.add(
        sum(weights[i] * scaled_sharpes[i] for i in range(n)) >= sharpe_floor_scaled
    )

    # Constraint 3: MDD ceiling — sum(w_i * scaled_abs_mdd_i) <= 100 * mdd_ceiling * MDD_SCALE
    mdd_ceiling_scaled = int(round(100 * mdd_ceiling * MDD_SCALE))
    model.add(
        sum(weights[i] * scaled_abs_mdds[i] for i in range(n)) <= mdd_ceiling_scaled
    )

    # Objective: Maximize sum(w_i * scaled_sharpe_i)
    model.maximize(sum(weights[i] * scaled_sharpes[i] for i in range(n)))

    # Solve with time limit
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = SOLVER_TIME_LIMIT_MS / 1000.0

    status = solver.solve(model)

    if status == cp_model.OPTIMAL:
        allocations = [(i, solver.value(weights[i])) for i in range(n)]
        return "OPTIMAL", allocations
    elif status == cp_model.FEASIBLE:
        allocations = [(i, solver.value(weights[i])) for i in range(n)]
        return "FEASIBLE", allocations
    else:
        return "INFEASIBLE", []


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def optimize_allocation(
    instruments: list[dict[str, Any]],
    horizon: str,
) -> OptimalAllocationResponse:
    """Compute optimal portfolio allocation for the given instruments and horizon.

    Parameters
    ----------
    instruments : list[dict]
        Each dict must have: instrument_id, name, ticker, yf_ticker.
        Loaded from the instruments DB table.
    horizon : str
        One of "short_term", "medium_term", "long_term".

    Returns
    -------
    OptimalAllocationResponse
        Complete response with solver status, allocations, and portfolio estimates.
    """
    horizon_config = INVESTMENT_HORIZONS.get(horizon)
    if horizon_config is None:
        log.error("portfolio_optimizer.invalid_horizon", horizon=horizon)
        return OptimalAllocationResponse(
            horizon=horizon,
            instrument_count=0,
            solver_status="ERROR",
            estimated_sharpe=0.0,
            estimated_mdd_pct=0.0,
            allocations=[],
        )

    lookback_td = horizon_config["lookback_td"]

    # Gather metrics for each instrument
    instrument_metrics: list[dict[str, Any]] = []
    for inst in instruments:
        inst_id = inst.get("instrument_id", "")
        inst_name = inst.get("name", inst_id)
        ticker = inst.get("yf_ticker", inst.get("ticker", inst_id))

        metrics = _get_instrument_metrics(inst_id, inst_name, ticker, lookback_td)
        if metrics is not None:
            instrument_metrics.append(metrics)

    log.info(
        "portfolio_optimizer.metrics_gathered",
        horizon=horizon,
        total_instruments=len(instruments),
        qualified=len(instrument_metrics),
    )

    # Edge case E5: No instruments
    if len(instrument_metrics) == 0:
        return OptimalAllocationResponse(
            horizon=horizon,
            instrument_count=0,
            solver_status="NO_INSTRUMENTS",
            estimated_sharpe=0.0,
            estimated_mdd_pct=0.0,
            allocations=[],
        )

    # Sort by Sharpe descending and take top MAX_INSTRUMENTS
    instrument_metrics.sort(key=lambda m: m["sharpe"], reverse=True)
    instrument_metrics = instrument_metrics[:MAX_INSTRUMENTS]

    # Edge case E2: Single instrument
    if len(instrument_metrics) == 1:
        m = instrument_metrics[0]
        return OptimalAllocationResponse(
            horizon=horizon,
            instrument_count=1,
            solver_status="SINGLE_INSTRUMENT",
            estimated_sharpe=round(m["sharpe"], 4),
            estimated_mdd_pct=round(m["mdd_pct"], 2),
            allocations=[
                AllocationItem(
                    instrument_name=m["instrument_name"],
                    ticker=m["ticker"],
                    allocation_pct=100,
                    sharpe=round(m["sharpe"], 4),
                    mdd_pct=round(m["mdd_pct"], 2),
                    metric_source=m["metric_source"],
                )
            ],
        )

    # Read environment-specific optimizer thresholds
    sharpe_floor = settings.optimizer.sharpe_floor
    mdd_ceiling = settings.optimizer.mdd_ceiling

    # Run CP-SAT solver
    solver_status, raw_allocations = _solve_allocation(
        instrument_metrics, sharpe_floor, mdd_ceiling
    )

    if solver_status == "INFEASIBLE":
        log.warning(
            "portfolio_optimizer.infeasible",
            horizon=horizon,
            instruments=len(instrument_metrics),
        )
        return OptimalAllocationResponse(
            horizon=horizon,
            instrument_count=len(instrument_metrics),
            solver_status="INFEASIBLE",
            estimated_sharpe=0.0,
            estimated_mdd_pct=0.0,
            allocations=[],
        )

    # Build allocation items and compute portfolio estimates
    allocations: list[AllocationItem] = []
    portfolio_sharpe = 0.0
    portfolio_mdd = 0.0

    for idx, alloc_pct in raw_allocations:
        m = instrument_metrics[idx]
        weight = alloc_pct / 100.0
        portfolio_sharpe += weight * m["sharpe"]
        portfolio_mdd += weight * m["mdd_pct"]
        allocations.append(
            AllocationItem(
                instrument_name=m["instrument_name"],
                ticker=m["ticker"],
                allocation_pct=alloc_pct,
                sharpe=round(m["sharpe"], 4),
                mdd_pct=round(m["mdd_pct"], 2),
                metric_source=m["metric_source"],
            )
        )

    # Sort allocations by allocation_pct descending for presentation
    allocations.sort(key=lambda a: a.allocation_pct, reverse=True)

    log.info(
        "portfolio_optimizer.solved",
        horizon=horizon,
        status=solver_status,
        instruments=len(allocations),
        portfolio_sharpe=round(portfolio_sharpe, 4),
        portfolio_mdd=round(portfolio_mdd, 2),
    )

    return OptimalAllocationResponse(
        horizon=horizon,
        instrument_count=len(allocations),
        solver_status=solver_status,
        estimated_sharpe=round(portfolio_sharpe, 4),
        estimated_mdd_pct=round(portfolio_mdd, 2),
        allocations=allocations,
    )
