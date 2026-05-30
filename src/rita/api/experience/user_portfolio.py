"""Experience-tier router — User Portfolio read-only endpoint.

ADR-001: Tier 1 (Experience Layer). Read-only — no db.commit(), no mutations.
Calls UserPortfolioRepo directly (no service layer), per ADR-001 experience-tier rules.
NOTE: If UserPortfolioService.get() retrieval logic changes, this endpoint must be
kept in sync manually (reviewer advisory from task-brief-20260530-1554).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from rita.auth import get_current_user
from rita.database import get_db
from rita.models.user import UserModel
from rita.repositories.user_portfolio import UserPortfolioRepo
from rita.repositories.user_portfolio_key import UserPortfolioKeyRepo
from rita.schemas.user_portfolio import UserPortfolioOut

router = APIRouter(prefix="/api/v1/experience", tags=["experience:user-portfolio"])


@router.get("/user-portfolio", response_model=UserPortfolioOut)
def get_user_portfolio(
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserPortfolioOut:
    """Return the active portfolio for the authenticated user (read-only)."""
    key = UserPortfolioKeyRepo(db).find_by_user_id(current_user.id)
    if key is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active portfolio found",
        )
    portfolio = UserPortfolioRepo(db).find_active_by_key_id(key.key_id)
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active portfolio found",
        )
    return UserPortfolioOut.model_validate(portfolio)
