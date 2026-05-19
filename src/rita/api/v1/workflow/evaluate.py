"""Workflow router -- model evaluation jobs.

ADR-001: Tier 2 (Business Process). Calls BacktestService only.
ADR-001: Never calls repositories directly or Experience Layer routers.

Evaluation reuses BacktestRun storage; distinguished by triggered_by='evaluate'.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from rita.database import get_db
from rita.schemas.backtest import BacktestResult, BacktestRun, BacktestRunCreate
from rita.services.backtest_service import BacktestService

router = APIRouter(prefix="/api/v1/workflow/evaluate", tags=["workflow:evaluate"])


def get_service(db: Session = Depends(get_db)) -> BacktestService:
    return BacktestService(db)


@router.post("/", response_model=BacktestRun, status_code=202)
def start_evaluation(body: BacktestRunCreate, svc: BacktestService = Depends(get_service)):
    """Submit a new model evaluation job. Returns the created run with status=pending."""
    return svc.start_evaluation(body)


@router.get("/", response_model=list[BacktestRun])
def list_evaluations(svc: BacktestService = Depends(get_service)):
    return svc.list_evaluations()


@router.get("/{run_id}", response_model=BacktestRun)
def get_evaluation(run_id: str, svc: BacktestService = Depends(get_service)):
    run = svc.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Evaluation run {run_id!r} not found")
    return run


@router.get("/{run_id}/results", response_model=list[BacktestResult])
def get_results(run_id: str, svc: BacktestService = Depends(get_service)):
    run = svc.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Evaluation run {run_id!r} not found")
    return svc.list_results(run_id)
