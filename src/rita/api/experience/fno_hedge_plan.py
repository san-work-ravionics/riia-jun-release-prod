"""Experience Layer — FnO Hedge Plan persistence endpoints (F29 Phase 1, F40 Phase 2).

GET  /api/v1/experience/fno/hedge-plan          — saved plan (read-only, no commit)
GET  /api/v1/experience/fno/hedge-plan/history  — own archived saves, newest first (read-only)
PUT  /api/v1/experience/fno/hedge-plan          — save; thin route over HedgePlanService

The PUT is a workflow-semantics write served under the Experience prefix — a recorded
ADR-001 exception (docs/ADR-004-hedge-plan-write-under-experience-prefix.md).  The
service owns the transaction (plan upsert + history append + one commit).
All endpoints require JWT auth.  duration is always stored as "1y" (business rule).
Consumers: hedge-workflow*.js and portfolio-hedge.js.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from rita.auth import get_current_user
from rita.database import get_db
from rita.models.user import UserModel
from rita.repositories.user_hedge_plan import UserHedgePlanRepo
from rita.repositories.user_portfolio_key import UserPortfolioKeyRepo
from rita.schemas.user_hedge_plan import (
    HedgePlanCreate,
    HedgePlanHistoryList,
    HedgePlanHistoryOut,
    HedgePlanOut,
)
from rita.services.hedge_plan_service import HedgePlanService, PortfolioKeyNotFound

router = APIRouter(prefix="/api/v1/experience/fno", tags=["experience:fno-hedge-plan"])


@router.get("/hedge-plan", response_model=Optional[HedgePlanOut])
def get_hedge_plan(
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Optional[HedgePlanOut]:
    """Return the saved hedge plan for the authenticated user, or null if none exists.

    Returns null (HTTP 200) when no portfolio key or hedge plan has been saved yet —
    this is a normal first-visit state, not an error.
    Does NOT auto-create a default row — read-only, no db.commit().
    """
    key = UserPortfolioKeyRepo(db).find_by_user_id(current_user.id)
    if key is None:
        return None

    plan = UserHedgePlanRepo(db).find_by_key_id(key.key_id)
    if plan is None:
        return None

    return HedgePlanOut.model_validate(plan)


@router.get("/hedge-plan/history", response_model=HedgePlanHistoryList)
def get_hedge_plan_history(
    limit: int = Query(50, ge=1, le=200),
    trigger: Optional[str] = Query(None),
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> HedgePlanHistoryList:
    """Own archived saves, newest first.  Empty list when the user has no portfolio key.

    Read-only, no db.commit().  No dashboard consumer yet (analysis / e2e assertion).
    """
    rows = HedgePlanService(db).history_for_user(current_user, limit=limit, trigger=trigger)
    items = [HedgePlanHistoryOut.model_validate(r) for r in rows]
    return HedgePlanHistoryList(items=items, count=len(items), limit=limit)


@router.put("/hedge-plan", response_model=HedgePlanOut)
def put_hedge_plan(
    body: HedgePlanCreate,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> HedgePlanOut:
    """Save the hedge plan (merge, enrich, append history, single commit — in the service)."""
    try:
        return HedgePlanService(db).save(current_user, body)
    except PortfolioKeyNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No portfolio key found",
        )
