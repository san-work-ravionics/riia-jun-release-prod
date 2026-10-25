"""Experience Layer — Optimal Allocation endpoint (F34 Phase 1).

ADR-001 Tier 3: read-only composition, no writes, no side effects.

GET /api/v1/experience/rita/optimal-allocation?horizon=short_term

Returns optimized portfolio allocations using OR-Tools CP-SAT solver.
Thin route over OptimalAllocationService (F44 P1 — shared with the MCP tool
portfolio.optimal_allocation): reads the instrument list, loads training history +
price data, and solves for optimal integer-percentage allocations.

Design decision: Returns 200 with solver_status communicating outcome
(even INFEASIBLE/NO_INSTRUMENTS) rather than 4xx, so frontend can
render helpful messages.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from rita.database import get_db
from rita.schemas.portfolio_optimizer import OptimalAllocationResponse
from rita.services.optimal_allocation_service import OptimalAllocationService

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
    return OptimalAllocationService(db).allocate(horizon)
