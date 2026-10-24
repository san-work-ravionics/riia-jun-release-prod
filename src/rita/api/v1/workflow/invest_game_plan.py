"""Workflow router — Invest Game "What I Need" plan save (F43 Phase 1, D10).

ADR-001: Tier 2 (Business Process). Calls RetirementPlanService only; the service
validates, upserts through the repository and owns the single commit.
Registered in main.py with ``dependencies=[Depends(get_current_user)]``.
Reads (calculate / load) live in the Experience tier: ``api/experience/invest_game.py``.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from rita.auth import get_current_user
from rita.database import get_db
from rita.models.user import UserModel
from rita.schemas.retirement_plan import RetirementPlanInputs, RetirementPlanOut
from rita.services.retirement_plan_service import PlanValidationError, RetirementPlanService

router = APIRouter(prefix="/api/v1/workflow/invest-game", tags=["workflow:invest-game"])


def _get_service(db: Session = Depends(get_db)) -> RetirementPlanService:
    return RetirementPlanService(db)


@router.put("/retirement-plan", response_model=RetirementPlanOut)
def save_retirement_plan(
    body: RetirementPlanInputs,
    current_user: UserModel = Depends(get_current_user),
    svc: RetirementPlanService = Depends(_get_service),
) -> RetirementPlanOut:
    """Save (replace) the signed-in user's plan inputs. Invalid plans are never stored."""
    try:
        return svc.save(current_user.id, body)
    except PlanValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
