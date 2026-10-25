"""OptimalAllocationService — instrument list + CP-SAT allocation (F44 P1, moved from the route).

The logic of ``GET /api/v1/experience/rita/optimal-allocation`` (F34) moved here unchanged so the
route and the MCP tool ``portfolio.optimal_allocation`` share it (ADR-007 §2).

- Reads the instruments through ``InstrumentRepository`` (available ones only).
- Calls ``core.portfolio_optimizer.optimize_allocation``.
- Never raises: any failure returns ``solver_status="ERROR"`` with no allocations (the route has
  always answered 200 with a status so the frontend can show a message).
"""
from __future__ import annotations

import structlog
from sqlalchemy.orm import Session

from rita.core.portfolio_optimizer import optimize_allocation
from rita.repositories.instrument import InstrumentRepository
from rita.schemas.portfolio_optimizer import OptimalAllocationResponse

log = structlog.get_logger()

HORIZONS = ("short_term", "medium_term", "long_term")


class OptimalAllocationService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def allocate(self, horizon: str) -> OptimalAllocationResponse:
        """Optimal allocation for ``horizon`` over the available instruments. Read-only."""
        try:
            repo = InstrumentRepository(self._db)
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
