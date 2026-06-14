"""Experience Layer — FnO Hedge Plan persistence endpoints (F29 Phase 1).

ADR-001 Tier 3 (Experience Layer).
GET  /api/v1/experience/fno/hedge-plan  — returns the saved hedge plan for the user
PUT  /api/v1/experience/fno/hedge-plan  — upserts the hedge plan and returns the persisted row

Both endpoints require JWT auth.  duration is always stored as "1y" (business rule).
Phase 2 consumer: portfolio-hedge.js — GET on load, PUT on user change (debounced).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from rita.auth import get_current_user
from rita.database import get_db
from rita.models.user import UserModel
from rita.models.user_hedge_plan import UserHedgePlanModel
from rita.repositories.user_hedge_plan import UserHedgePlanRepo
from rita.repositories.user_portfolio_key import UserPortfolioKeyRepo
from rita.schemas.user_hedge_plan import HedgePlanCreate, HedgePlanOut

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


@router.put("/hedge-plan", response_model=HedgePlanOut)
def put_hedge_plan(
    body: HedgePlanCreate,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> HedgePlanOut:
    """Upsert the hedge plan for the authenticated user.

    duration from the request body is accepted but always overwritten with "1y"
    (business rule: F29 Phase 0 removed variable duration support).
    Exactly one db.commit() per ADR-001 Experience-tier write rule.
    """
    key = UserPortfolioKeyRepo(db).find_by_user_id(current_user.id)
    if key is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No portfolio key found",
        )

    repo = UserHedgePlanRepo(db)
    plan = UserHedgePlanModel(
        key_id=key.key_id,
        hedged_ids=body.hedged_ids,
        coverage=body.coverage,
        scenario_tab=body.scenario_tab,
        duration="1y",  # business rule: always 1-year horizon
        updated_at=datetime.now(timezone.utc),
    )
    repo.upsert(plan)
    db.commit()  # exactly one commit — ADR-001 §Experience tier write rule

    updated = repo.find_by_key_id(key.key_id)
    return HedgePlanOut.model_validate(updated)
