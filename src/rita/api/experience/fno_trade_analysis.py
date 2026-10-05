"""Experience Layer — F42 FnO Trade Analysis (live feed).

ADR-001 Tier 3: composes a read-only UI payload from an external source
(fno-margin-fetch: today's Kite orders/trades/positions + NFO instrument master).
No DB access, no db.commit(). Always HTTP 200; failure is in-payload
(`available: false`, `reason`). Browser -> this route -> client -> middleware.

GET /api/v1/experience/fno/trade-analysis/live
    ?underlying=ALL|NIFTY|BANKNIFTY  &expiry_month=1-12  &include_closed=true|false
"""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query

from rita.auth import get_current_user
from rita.config import get_settings
from rita.models.user import UserModel
from rita.schemas.fno_trade_analysis import TradeAnalysisLiveResponse
from rita.services import kite_middleware_client as kmc
from rita.services.fno_trade_analysis_service import build_live_payload

router = APIRouter(prefix="/api/v1/experience/fno", tags=["experience:fno-trade-analysis"])


@router.get("/trade-analysis/live", response_model=TradeAnalysisLiveResponse)
def get_trade_analysis_live(
    underlying: Literal["ALL", "NIFTY", "BANKNIFTY"] = Query(default="ALL"),
    expiry_month: Optional[int] = Query(default=None, ge=1, le=12),
    include_closed: bool = Query(default=True),
    current_user: UserModel = Depends(get_current_user),
) -> TradeAnalysisLiveResponse:
    """Today's live Kite activity for the configured option scope. Never raises; always 200."""
    cfg = get_settings().trade_analysis
    return build_live_payload(
        orders=kmc.fetch_live_orders(),
        trades=kmc.fetch_live_trades(snapshot=True),
        positions=kmc.fetch_live_positions(),
        master=kmc.fetch_instrument_master_nfo(),
        snapshot=kmc.fetch_snapshot_status(),
        underlyings=cfg.underlyings,
        expiry_months=cfg.expiry_months,
        underlying=underlying,
        expiry_month=expiry_month,
        include_closed=include_closed,
    )
