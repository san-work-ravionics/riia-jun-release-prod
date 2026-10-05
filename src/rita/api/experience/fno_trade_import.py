"""Experience Layer — F42 Phase 2 imported Console data (read-only).

ADR-001 Tier 3: composes UI payloads through FnoImportReadService; no writes, no commit.
Always scoped to the caller (user_id = current_user.id) and to the configured option scope.

GET /api/v1/experience/fno/trade-analysis/import-status
GET /api/v1/experience/fno/trade-analysis/imported-trades
"""
from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from rita.auth import get_current_user
from rita.config import get_settings
from rita.database import get_db
from rita.models.user import UserModel
from rita.schemas.fno_console_import import ImportedTradesResponse, ImportStatusResponse
from rita.services.fno_import_service import FnoImportReadService

router = APIRouter(prefix="/api/v1/experience/fno", tags=["experience:fno-trade-import"])


def _get_service(db: Session = Depends(get_db)) -> FnoImportReadService:
    return FnoImportReadService(db)


@router.get("/trade-analysis/import-status", response_model=ImportStatusResponse)
def get_import_status(
    current_user: UserModel = Depends(get_current_user),
    svc: FnoImportReadService = Depends(_get_service),
) -> ImportStatusResponse:
    return svc.status(current_user.id)


@router.get("/trade-analysis/imported-trades", response_model=ImportedTradesResponse)
def get_imported_trades(
    underlying: str = Query(default="ALL"),
    include_fut: bool = Query(default=False),
    expiry_month: Optional[int] = Query(default=None, ge=1, le=12),
    date_from: Optional[date] = Query(default=None),
    date_to: Optional[date] = Query(default=None),
    side: Optional[Literal["buy", "sell"]] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    sort: Literal["trade_date_desc", "trade_date_asc"] = Query(default="trade_date_desc"),
    current_user: UserModel = Depends(get_current_user),
    svc: FnoImportReadService = Depends(_get_service),
) -> ImportedTradesResponse:
    if underlying != "ALL" and underlying not in get_settings().trade_analysis.underlyings:
        raise HTTPException(status_code=422, detail="underlying must be ALL or a configured underlying")
    return svc.trades(current_user.id, underlying, include_fut, expiry_month, date_from, date_to,
                      side, sort, page, page_size)
