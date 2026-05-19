"""Experience Layer -- FnO view aggregation router.

ADR-001: Tier 3 (Experience Layer). Read-only composition. No writes, no side effects.
Composes: option position snapshots + daily portfolio P&L + recent manoeuvres.

Greeks (delta/gamma/theta/vega) are computed in core/ and will be surfaced here
once Sprint 3 services are in place. For now the snapshots include per-leg P&L.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from rita.database import get_db
from rita.repositories.snapshots import SnapshotsRepository
from rita.schemas.manoeuvres import Manoeuvre
from rita.schemas.portfolio import Portfolio
from rita.schemas.snapshots import Snapshot
from rita.services.manoeuvre_service import ManoeuvreService
from rita.services.portfolio_service import PortfolioService

router = APIRouter(prefix="/api/experience/fno", tags=["experience:fno"])


class FnoPayload(BaseModel):
    snapshots: list[Snapshot]
    portfolio: list[Portfolio]
    recent_manoeuvres: list[Manoeuvre]


def get_snapshots_repo(db: Session = Depends(get_db)) -> SnapshotsRepository:
    return SnapshotsRepository(db)


def get_manoeuvre_service(db: Session = Depends(get_db)) -> ManoeuvreService:
    return ManoeuvreService(db)


def get_portfolio_service(db: Session = Depends(get_db)) -> PortfolioService:
    return PortfolioService(db)


@router.get("/", response_model=FnoPayload)
def get_fno(
    manoeuvre_limit: int = Query(default=50, ge=1, le=500),
    snapshots_repo: SnapshotsRepository = Depends(get_snapshots_repo),
    manoeuvre_svc: ManoeuvreService = Depends(get_manoeuvre_service),
    portfolio_svc: PortfolioService = Depends(get_portfolio_service),
) -> FnoPayload:
    """Return a single aggregated payload for the FnO portfolio view."""
    snapshots = snapshots_repo.read_all()
    portfolio = portfolio_svc.list_all()
    recent_manoeuvres = manoeuvre_svc.list_recent(manoeuvre_limit)

    return FnoPayload(
        snapshots=snapshots,
        portfolio=portfolio,
        recent_manoeuvres=recent_manoeuvres,
    )
