"""Experience Layer -- Dashboard aggregation router.

ADR-001: Tier 3 (Experience Layer). Read-only composition. No writes, no side effects.
Composes: live positions + latest model state (training run) + recent alerts.

One GET per view -- the UI makes a single call to get everything it needs.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from rita.database import get_db
from rita.repositories.alerts import AlertsRepository
from rita.repositories.positions import PositionsRepository
from rita.schemas.alerts import Alert
from rita.schemas.positions import Position
from rita.schemas.training import TrainingRun
from rita.services.workflow_service import WorkflowService

router = APIRouter(prefix="/api/experience/dashboard", tags=["experience:dashboard"])


class DashboardPayload(BaseModel):
    positions: list[Position]
    latest_training_run: Optional[TrainingRun]
    recent_alerts: list[Alert]


def get_positions_repo(db: Session = Depends(get_db)) -> PositionsRepository:
    return PositionsRepository(db)


def get_alerts_repo(db: Session = Depends(get_db)) -> AlertsRepository:
    return AlertsRepository(db)


def get_workflow_svc(db: Session = Depends(get_db)) -> WorkflowService:
    return WorkflowService(db)


@router.get("/", response_model=DashboardPayload)
def get_dashboard(
    alert_limit: int = Query(default=20, ge=1, le=200),
    positions_repo: PositionsRepository = Depends(get_positions_repo),
    alerts_repo: AlertsRepository = Depends(get_alerts_repo),
    workflow_svc: WorkflowService = Depends(get_workflow_svc),
) -> DashboardPayload:
    """Return a single aggregated payload for the RITA trading dashboard."""
    positions = positions_repo.read_all()

    runs = workflow_svc.list_runs()
    latest_run = max(runs, key=lambda r: r.recorded_at, default=None) if runs else None

    alerts = alerts_repo.read_all()
    recent_alerts = sorted(alerts, key=lambda a: a.timestamp, reverse=True)[:alert_limit]

    return DashboardPayload(
        positions=positions,
        latest_training_run=latest_run,
        recent_alerts=recent_alerts,
    )
