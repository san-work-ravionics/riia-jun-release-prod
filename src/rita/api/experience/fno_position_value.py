"""Experience Layer — FnO position value chart data (F40 Phase 3).

GET /api/v1/experience/fno/position-value — read-only (no commit); thin route over
PositionValueService.  Never 404: unknown/option-only instruments return a status item.
Consumer: dashboard/js/fno/hedge-position-value.js (Exposure step candle card).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from rita.auth import get_current_user
from rita.database import get_db
from rita.models.user import UserModel
from rita.schemas.position_value import PositionValueResponse
from rita.services.position_value_service import PositionValueService

router = APIRouter(prefix="/api/v1/experience/fno", tags=["experience:fno-position-value"])


@router.get("/position-value", response_model=PositionValueResponse)
def get_position_value(
    instrument: Optional[str] = Query(None, description="Instrument id (case-insensitive); omit for all holdings"),
    months: int = Query(12, ge=1, le=36),
    ann_vol_pct: Optional[float] = Query(None, gt=0, description="Annualised vol % override for the ±1σ bands"),
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PositionValueResponse:
    """Monthly OHLC of shares x close (instrument currency) plus ±1σ monthly bands."""
    return PositionValueService(db).build(current_user, instrument, months, ann_vol_pct)
