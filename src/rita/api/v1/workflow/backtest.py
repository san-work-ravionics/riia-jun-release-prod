"""Workflow router -- backtest jobs.

ADR-001: Tier 2 (Business Process). Calls BacktestService only.
ADR-001: Never calls repositories directly or Experience Layer routers.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from rita.database import get_db
from rita.schemas.backtest import BacktestResult, BacktestRun, BacktestRunCreate
from rita.services.backtest_service import BacktestService

router = APIRouter(prefix="/api/v1/workflow/backtest", tags=["workflow:backtest"])


def get_service(db: Session = Depends(get_db)) -> BacktestService:
    return BacktestService(db)


@router.post("/", response_model=BacktestRun, status_code=202)
def start_backtest(body: BacktestRunCreate, svc: BacktestService = Depends(get_service)):
    """Submit a new backtest job. Returns the created run with status=pending."""
    return svc.start_backtest(body)


@router.get("/", response_model=list[BacktestRun])
def list_runs(svc: BacktestService = Depends(get_service)):
    return svc.list_runs()


@router.get("/{run_id}", response_model=BacktestRun)
def get_run(run_id: str, svc: BacktestService = Depends(get_service)):
    run = svc.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Backtest run {run_id!r} not found")
    return run


@router.get("/{run_id}/results", response_model=list[BacktestResult])
def get_results(run_id: str, svc: BacktestService = Depends(get_service)):
    run = svc.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Backtest run {run_id!r} not found")
    return svc.list_results(run_id)
