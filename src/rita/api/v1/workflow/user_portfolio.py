"""Workflow router — User Portfolio Store.

ADR-001: Tier 2 (Business Process). Calls UserPortfolioService only.
Reviewer advisory (task-brief-20260530-1554): direct-repo access is intentional
in the experience tier; if UserPortfolioService.get() logic changes, the
experience-tier endpoint must be kept in sync manually.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from rita.auth import get_current_user
from rita.database import get_db
from rita.models.user import UserModel
from rita.schemas.user_portfolio import UserPortfolioCreate, UserPortfolioOut
from rita.services.user_portfolio_service import UserPortfolioService

router = APIRouter(prefix="/api/v1/user-portfolio", tags=["workflow:user-portfolio"])


@router.post("/", response_model=UserPortfolioOut, status_code=status.HTTP_201_CREATED)
def save_portfolio(
    body: UserPortfolioCreate,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserPortfolioOut:
    """Save (replace) the active portfolio for the authenticated user."""
    try:
        return UserPortfolioService(db).save(current_user.id, body.holdings, body.name)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.get("/", response_model=UserPortfolioOut)
def get_portfolio(
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserPortfolioOut:
    """Return the active portfolio for the authenticated user."""
    result = UserPortfolioService(db).get(current_user.id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active portfolio found",
        )
    return result
