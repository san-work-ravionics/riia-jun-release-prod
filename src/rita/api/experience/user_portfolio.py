"""Experience-tier router — User Portfolio read-only endpoint.

ADR-001: Tier 1 (Experience Layer). Read-only — no db.commit(), no mutations.
ADR-002 / engineer.md §2: reads through ``UserPortfolioService.get`` (no direct repository call),
so this route and the v1 route share one retrieval rule (F44 P2 review #5).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from rita.auth import get_current_user
from rita.database import get_db
from rita.models.user import UserModel
from rita.schemas.user_portfolio import Location, UserPortfolioOut
from rita.services.user_portfolio_service import UserPortfolioService

router = APIRouter(prefix="/api/v1/experience", tags=["experience:user-portfolio"])


@router.get("/user-portfolio", response_model=UserPortfolioOut)
def get_user_portfolio(
    location: Location | None = Query(default=None, description="europe | india | us; omit = most recent"),
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserPortfolioOut:
    """Return the active portfolio for the authenticated user (read-only).

    F44 P2: ``location`` given → that location's active portfolio; omitted → the most recently
    saved active portfolio of any location (same rule as ``UserPortfolioService.get``).
    """
    portfolio = UserPortfolioService(db).get(current_user.id, location)
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active portfolio found",
        )
    return portfolio
