"""Experience-tier router — FX rate read (F44 P2).

ADR-001: Tier 1 (Experience Layer). Read-only — the rate comes from ``market_data_cache`` via
``FxService``; no network call is made from request code (org.md §3: FX rows are written only by
the ``/refresh-all-instruments-data`` skill run, ``services/data_refresh.refresh_fx``).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from rita.database import get_db
from rita.schemas.fx import Currency, FxRateOut
from rita.services.fx_service import FxService

router = APIRouter(prefix="/api/v1/experience", tags=["experience:fx"])


def _get_service(db: Session = Depends(get_db)) -> FxService:
    return FxService(db)


@router.get("/rita/fx", response_model=FxRateOut)
def get_fx_rate(
    base: Currency = Query(default="EUR"),
    quote: Currency = Query(...),
    svc: FxService = Depends(_get_service),
) -> FxRateOut:
    """Latest cached rate: units of ``quote`` per 1 ``base``. 404 ``no fx rate`` when not cached."""
    r = svc.rate(base, quote)
    if r is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no fx rate")
    return FxRateOut(base=r.base, quote=r.quote, rate=r.rate, as_of=r.as_of, source=r.source)
