"""Experience Layer -- FnO view aggregation router.

ADR-001: Tier 3 (Experience Layer). Read-only composition. No writes, no side effects.
Composes: option position snapshots + daily portfolio P&L + recent manoeuvres.

Greeks (delta/gamma/theta/vega) are computed in core/ and will be surfaced here
once Sprint 3 services are in place. For now the snapshots include per-leg P&L.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from rita.auth import get_current_user
from rita.database import get_db
from rita.models.user import UserModel
from rita.repositories.snapshots import SnapshotsRepository
from rita.repositories.user_portfolio import UserPortfolioRepo
from rita.repositories.user_portfolio_key import UserPortfolioKeyRepo
from rita.schemas.manoeuvres import Manoeuvre
from rita.schemas.portfolio import Portfolio
from rita.schemas.snapshots import Snapshot
from rita.services.manoeuvre_service import ManoeuvreService
from rita.services.portfolio_service import PortfolioService

router = APIRouter(prefix="/api/experience/fno", tags=["experience:fno"])

_FNO_ELIGIBLE: frozenset[str] = frozenset({"NIFTY", "BANKNIFTY"})


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


# ── Portfolio Hedge (Feature 27) ──────────────────────────────────────────────

class HedgeRecommendation(BaseModel):
    instrument_id: str
    allocation_pct: float
    eligible: bool
    risk_level: str          # "high" | "medium" | "low"
    hedge_type: str          # "index_put" | "index_put_spread" | "equity_note" | "na"
    recommendation: str
    cost_estimate_pct: float


class PortfolioHedgeResponse(BaseModel):
    portfolio_name: str
    total_allocated_pct: float
    recommendations: list[HedgeRecommendation]


def _hedge_for(instrument_id: str, allocation_pct: float) -> HedgeRecommendation:
    eligible = instrument_id.upper() in _FNO_ELIGIBLE
    risk_level = "high" if allocation_pct >= 30 else ("medium" if allocation_pct >= 15 else "low")

    if not eligible:
        return HedgeRecommendation(
            instrument_id=instrument_id,
            allocation_pct=allocation_pct,
            eligible=False,
            risk_level=risk_level,
            hedge_type="equity_note",
            recommendation=(
                f"{instrument_id} ({allocation_pct:.0f}%) — No NSE F&O contracts available. "
                "Consider diversifying or reducing position size if correlation with index is high."
            ),
            cost_estimate_pct=0.0,
        )

    if risk_level == "high":
        return HedgeRecommendation(
            instrument_id=instrument_id,
            allocation_pct=allocation_pct,
            eligible=True,
            risk_level="high",
            hedge_type="index_put",
            recommendation=(
                f"{instrument_id} ({allocation_pct:.0f}%) — Buy ATM weekly put. "
                "Large allocation warrants active downside protection against gap-down events."
            ),
            cost_estimate_pct=0.7,
        )
    if risk_level == "medium":
        return HedgeRecommendation(
            instrument_id=instrument_id,
            allocation_pct=allocation_pct,
            eligible=True,
            risk_level="medium",
            hedge_type="index_put_spread",
            recommendation=(
                f"{instrument_id} ({allocation_pct:.0f}%) — Put spread (−2%/−5% OTM) "
                "offers cost-effective downside buffer without full premium outlay."
            ),
            cost_estimate_pct=0.4,
        )
    return HedgeRecommendation(
        instrument_id=instrument_id,
        allocation_pct=allocation_pct,
        eligible=True,
        risk_level="low",
        hedge_type="na",
        recommendation=(
            f"{instrument_id} ({allocation_pct:.0f}%) — Small allocation. "
            "Hedge optional; index-level protection from larger positions covers tail risk."
        ),
        cost_estimate_pct=0.2,
    )


@router.get("/portfolio-hedge", response_model=PortfolioHedgeResponse)
def get_portfolio_hedge(
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PortfolioHedgeResponse:
    """Return per-instrument hedge recommendations for the authenticated user's saved portfolio."""
    key = UserPortfolioKeyRepo(db).find_by_user_id(current_user.id)
    if key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active portfolio found")
    portfolio = UserPortfolioRepo(db).find_active_by_key_id(key.key_id)
    if portfolio is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active portfolio found")

    holdings = portfolio.holdings or []
    total_pct = sum(h.get("allocation_pct", 0) if isinstance(h, dict) else h.allocation_pct for h in holdings)

    recommendations = []
    for h in holdings:
        inst_id = h.get("instrument_id") if isinstance(h, dict) else h.instrument_id
        alloc   = h.get("allocation_pct", 0) if isinstance(h, dict) else h.allocation_pct
        recommendations.append(_hedge_for(inst_id, alloc))

    recommendations.sort(key=lambda r: -r.allocation_pct)

    return PortfolioHedgeResponse(
        portfolio_name=portfolio.name or "Portfolio",
        total_allocated_pct=total_pct,
        recommendations=recommendations,
    )
