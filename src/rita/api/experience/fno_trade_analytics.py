"""Experience Layer — F42 Phase 3 Trade Analysis analytics (read-only).

ADR-001 Tier 3: six GET endpoints, one per panel, composed by FnoTradeAnalyticsService from the
caller's own imported rows (user_id = current_user.id).  No writes, no commit, the router never
touches a repository.  The buildup and suggestions handlers look up lot sizes from the Kite NFO
master in the ROUTER (only when include_lots=true; no personal data is sent) and pass the plain
result into the service; a middleware failure never fails the endpoint (lots_available=false).

GET /api/v1/experience/fno/trade-analysis/analytics/{foundation,overtrading,buildup,
    market-turn,margin-trap,suggestions}
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from rita.auth import get_current_user
from rita.config import get_settings
from rita.database import get_db
from rita.models.user import UserModel
from rita.schemas.fno_trade_analytics import (
    BuildupResponse, FoundationResponse, MarginTrapResponse, MarketTurnResponse,
    OvertradingResponse, SuggestionsResponse,
)
from rita.services import kite_middleware_client as kmc
from rita.services.fno_trade_analytics_service import AnalyticsParams, FnoTradeAnalyticsService

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/experience/fno", tags=["experience:fno-trade-analytics"])
_BASE = "/trade-analysis/analytics"


def _get_service(db: Session = Depends(get_db)) -> FnoTradeAnalyticsService:
    return FnoTradeAnalyticsService(db)


def _params(
    underlying: str = Query(default="ALL"),
    expiry_month: Optional[int] = Query(default=None, ge=1, le=12),
    date_from: Optional[date] = Query(default=None),
    date_to: Optional[date] = Query(default=None),
    include_expiry_estimate: Optional[bool] = Query(default=None),
    include_lots: bool = Query(default=True),
) -> AnalyticsParams:
    if underlying != "ALL" and underlying not in get_settings().trade_analysis.underlyings:
        raise HTTPException(status_code=422, detail="underlying must be ALL or a configured underlying")
    return AnalyticsParams(underlying, expiry_month, date_from, date_to, include_expiry_estimate,
                           include_lots)


def _master(p: AnalyticsParams) -> Any:
    if not p.include_lots:
        return None
    try:
        return kmc.fetch_instrument_master_nfo()
    except Exception as exc:  # defensive: lots are optional
        log.warning("fno_trade_analytics.master_failed", error_type=type(exc).__name__)
        return None


@router.get(f"{_BASE}/foundation", response_model=FoundationResponse)
def get_foundation(p: AnalyticsParams = Depends(_params),
                   current_user: UserModel = Depends(get_current_user),
                   svc: FnoTradeAnalyticsService = Depends(_get_service)) -> FoundationResponse:
    return svc.foundation(current_user.id, p)


@router.get(f"{_BASE}/overtrading", response_model=OvertradingResponse)
def get_overtrading(p: AnalyticsParams = Depends(_params),
                    current_user: UserModel = Depends(get_current_user),
                    svc: FnoTradeAnalyticsService = Depends(_get_service)) -> OvertradingResponse:
    return svc.overtrading(current_user.id, p)


@router.get(f"{_BASE}/buildup", response_model=BuildupResponse)
def get_buildup(p: AnalyticsParams = Depends(_params),
                current_user: UserModel = Depends(get_current_user),
                svc: FnoTradeAnalyticsService = Depends(_get_service)) -> BuildupResponse:
    return svc.buildup(current_user.id, p, _master(p))


@router.get(f"{_BASE}/market-turn", response_model=MarketTurnResponse)
def get_market_turn(p: AnalyticsParams = Depends(_params),
                    current_user: UserModel = Depends(get_current_user),
                    svc: FnoTradeAnalyticsService = Depends(_get_service)) -> MarketTurnResponse:
    return svc.market_turn(current_user.id, p)


@router.get(f"{_BASE}/margin-trap", response_model=MarginTrapResponse)
def get_margin_trap(p: AnalyticsParams = Depends(_params),
                    current_user: UserModel = Depends(get_current_user),
                    svc: FnoTradeAnalyticsService = Depends(_get_service)) -> MarginTrapResponse:
    return svc.margin_trap(current_user.id, p)


@router.get(f"{_BASE}/suggestions", response_model=SuggestionsResponse)
def get_suggestions(p: AnalyticsParams = Depends(_params),
                    current_user: UserModel = Depends(get_current_user),
                    svc: FnoTradeAnalyticsService = Depends(_get_service)) -> SuggestionsResponse:
    return svc.suggestions(current_user.id, p, _master(p))
