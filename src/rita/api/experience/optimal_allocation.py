"""Experience Layer — Optimal Allocation endpoint (F34 Phase 1).

ADR-001 Tier 3: read-only composition, no writes, no side effects.

GET /api/v1/experience/rita/optimal-allocation?horizon=short_term

Returns optimized portfolio allocations using OR-Tools CP-SAT solver.
Reads instrument list from DB, loads training history + price data,
and solves for optimal integer-percentage allocations.

Design decision: Returns 200 with solver_status communicating outcome
(even INFEASIBLE/NO_INSTRUMENTS) rather than 4xx, so frontend can
render helpful messages.
"""
from __future__ import annotations

from typing import Literal

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from rita.database import get_db
from rita.repositories.instrument import InstrumentRepository
from rita.core.portfolio_optimizer import optimize_allocation
from rita.schemas.portfolio_optimizer import OptimalAllocationResponse

log = structlog.get_logger()

router = APIRouter(
    prefix="/api/v1/experience/rita",
    tags=["experience:rita"],
)


@router.get("/optimal-allocation", response_model=OptimalAllocationResponse)
def get_optimal_allocation(
    horizon: Literal["short_term", "medium_term", "long_term"] = Query(
        ..., description="Investment horizon for instrument filtering and metric lookback"
    ),
    db: Session = Depends(get_db),
) -> OptimalAllocationResponse:
    """Return optimized portfolio allocations for the given investment horizon.

    Reads available instruments from the DB, gathers Sharpe and MDD metrics
    from model training history or proxy estimates from price data, then runs
    the CP-SAT solver to find optimal allocation percentages.

    Read-only: no db.commit() calls.
    """
    try:
        repo = InstrumentRepository(db)
        all_instruments = repo.read_all()

        # Filter to available instruments only
        instruments = [
            {
                "instrument_id": inst.instrument_id,
                "name": inst.name,
                "ticker": inst.instrument_id,
                "yf_ticker": getattr(inst, "yf_ticker", inst.instrument_id),
            }
            for inst in all_instruments
            if getattr(inst, "is_available", True)
        ]

        log.info(
            "optimal_allocation.request",
            horizon=horizon,
            available_instruments=len(instruments),
        )

        return optimize_allocation(instruments=instruments, horizon=horizon)

    except Exception as exc:
        log.error(
            "optimal_allocation.error",
            horizon=horizon,
            error=str(exc),
            exc_info=True,
        )
        return OptimalAllocationResponse(
            horizon=horizon,
            instrument_count=0,
            solver_status="ERROR",
            estimated_sharpe=0.0,
            estimated_mdd_pct=0.0,
            allocations=[],
        )
