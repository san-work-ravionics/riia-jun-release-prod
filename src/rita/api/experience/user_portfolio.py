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
from rita.schemas.user_portfolio import HoldingItem, Location, UserPortfolioOut
from rita.services.user_portfolio_service import UserPortfolioService

router = APIRouter(prefix="/api/v1/experience", tags=["experience:user-portfolio"])


def _merge_portfolios(portfolios: list[UserPortfolioOut]) -> UserPortfolioOut:
    """Merge multiple location portfolios into a single EUR-denominated view.

    Allocation percentages are re-weighted by each portfolio's total_value_eur so
    that (allocation_pct / 100 * merged.total_value_eur) yields the correct EUR
    position for every holding. Holdings are deduplicated by instrument_id (first
    portfolio's holding wins). Portfolios without a total_value_eur are skipped.
    """
    eligible = [p for p in portfolios if (p.total_value_eur or 0.0) > 0]
    if not eligible:
        # Fall back to the first portfolio as-is when no EUR totals are available.
        return portfolios[0]

    total_eur = sum(p.total_value_eur for p in eligible)  # type: ignore[arg-type]
    seen: set[str] = set()
    merged: list[HoldingItem] = []
    for p in eligible:
        weight = (p.total_value_eur or 0.0) / total_eur
        for h in p.holdings:
            if h.instrument_id not in seen:
                seen.add(h.instrument_id)
                merged.append(HoldingItem(
                    instrument_id=h.instrument_id,
                    allocation_pct=round(h.allocation_pct * weight, 6),
                    shares=h.shares,
                ))

    first = eligible[0]
    return UserPortfolioOut.model_construct(
        portfolio_id=first.portfolio_id,
        key_id=first.key_id,
        name="All Portfolios",
        holdings=merged,
        currency="EUR",
        location=None,
        total_value=total_eur,
        total_value_eur=total_eur,
        created_at=first.created_at,
        updated_at=first.updated_at,
        is_active=True,
    )


@router.get("/user-portfolio", response_model=UserPortfolioOut)
def get_user_portfolio(
    location: Location | None = Query(default=None, description="europe | india | us; omit = most recent"),
    all_locations: bool = Query(default=False, description="Return holdings merged from all active location buckets (EUR-denominated)"),
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserPortfolioOut:
    """Return the active portfolio for the authenticated user (read-only).

    F44 P2: ``location`` given → that location's active portfolio; omitted → the most recently
    saved active portfolio of any location (same rule as ``UserPortfolioService.get``).
    ``all_locations=true`` → all active location portfolios merged into one EUR-denominated view.
    """
    if all_locations:
        portfolios = UserPortfolioService(db).get_all(current_user.id)
        if not portfolios:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No active portfolio found",
            )
        if len(portfolios) == 1:
            return portfolios[0]
        return _merge_portfolios(portfolios)

    portfolio = UserPortfolioService(db).get(current_user.id, location)
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active portfolio found",
        )
    return portfolio
