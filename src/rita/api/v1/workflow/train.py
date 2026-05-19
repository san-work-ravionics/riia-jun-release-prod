"""Workflow router -- DQN training jobs.

ADR-001: Tier 2 (Business Process). Calls WorkflowService only.
ADR-001: Never calls repositories directly or Experience Layer routers.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from rita.database import get_db
from rita.schemas.training import TrainingMetric, TrainingRun, TrainingRunCreate
from rita.services.workflow_service import WorkflowService

router = APIRouter(prefix="/api/v1/workflow/train", tags=["workflow:train"])


def get_service(db: Session = Depends(get_db)) -> WorkflowService:
    return WorkflowService(db)


@router.post("/", response_model=TrainingRun, status_code=202)
def start_training(body: TrainingRunCreate, svc: WorkflowService = Depends(get_service)):
    """Submit a new DQN training job. Returns the created run with status=pending."""
    return svc.start_training(body)


@router.get("/", response_model=list[TrainingRun])
def list_runs(svc: WorkflowService = Depends(get_service)):
    return svc.list_runs()


@router.get("/{run_id}", response_model=TrainingRun)
def get_run(run_id: str, svc: WorkflowService = Depends(get_service)):
    run = svc.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Training run {run_id!r} not found")
    return run


@router.get("/{run_id}/metrics", response_model=list[TrainingMetric])
def get_metrics(run_id: str, svc: WorkflowService = Depends(get_service)):
    run = svc.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Training run {run_id!r} not found")
    return svc.list_metrics(run_id)
