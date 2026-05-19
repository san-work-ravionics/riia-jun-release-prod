"""BacktestService — backtest and evaluate job tracking and dispatch.

ADR-001: Workflow routers call services only.
ADR-002: All data access via repository classes.

Sprint 2: Creates job records with status=pending and persists them.
Sprint 3: Plugs in actual backtest/evaluate execution logic via a daemon
          thread so the API returns immediately with status=pending.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy.orm import Session

from rita.core.backtest_dispatch import BacktestConfig, run_backtest
from rita.database import SessionLocal
from rita.repositories.backtest import BacktestResultsRepository, BacktestRunsRepository
from rita.schemas.backtest import BacktestResult, BacktestRun, BacktestRunCreate

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Module-level background worker
# ---------------------------------------------------------------------------


def _run_backtest_job(run_id: str, config: BacktestConfig) -> None:
    """Background thread: run backtest and persist all results."""
    db = SessionLocal()
    try:
        runs_repo = BacktestRunsRepository(db)
        results_repo = BacktestResultsRepository(db)

        run = runs_repo.find_by_id(run_id)
        if run is None:
            return

        run = BacktestRun(**{**run.model_dump(), "status": "running", "started_at": datetime.now(timezone.utc)})
        runs_repo.upsert(run)
        log.info("backtest.running", run_id=run_id)

        try:
            outcome = run_backtest(config)
        except Exception:
            log.error("backtest.failed", run_id=run_id, exc_info=True)
            run = runs_repo.find_by_id(run_id)
            if run is not None:
                runs_repo.upsert(
                    BacktestRun(**{**run.model_dump(), "status": "failed", "ended_at": datetime.now(timezone.utc)})
                )
            return

        ended_at = datetime.now(timezone.utc)
        run = runs_repo.find_by_id(run_id)
        if run is None:
            return

        runs_repo.upsert(BacktestRun(**{
            **run.model_dump(),
            "status": "complete",
            "ended_at": ended_at,
            "total_trades": outcome.total_trades,
        }))
        log.info("backtest.complete", run_id=run_id, total_trades=outcome.total_trades)

        results_repo.bulk_create([
            BacktestResult(
                result_id=str(uuid.uuid4()),
                run_id=run_id,
                date=daily.date,
                portfolio_value=daily.portfolio_value,
                benchmark_value=daily.benchmark_value,
                allocation=daily.allocation,
                close_price=daily.close_price,
                total_return=outcome.total_return,
                sharpe_ratio=outcome.sharpe_ratio,
                max_drawdown=outcome.max_drawdown,
                recorded_at=ended_at,
            )
            for daily in outcome.daily_results
        ])
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Service class
# ---------------------------------------------------------------------------


class BacktestService:
    def __init__(self, db: Session) -> None:
        self._runs = BacktestRunsRepository(db)
        self._results = BacktestResultsRepository(db)

    def start_backtest(self, body: BacktestRunCreate) -> BacktestRun:
        """Create a backtest run record with status=pending and dispatch."""
        return self._create_run(body, triggered_by=body.triggered_by or "api")

    def start_evaluation(self, body: BacktestRunCreate) -> BacktestRun:
        """Create an evaluation run record with status=pending and dispatch."""
        return self._create_run(body, triggered_by="evaluate")

    def get_run(self, run_id: str) -> BacktestRun | None:
        return self._runs.find_by_id(run_id)

    def list_runs(self) -> list[BacktestRun]:
        return [r for r in self._runs.read_all() if r.triggered_by != "evaluate"]

    def list_evaluations(self) -> list[BacktestRun]:
        return [r for r in self._runs.read_all() if r.triggered_by == "evaluate"]

    def list_results(self, run_id: str) -> list[BacktestResult]:
        return [r for r in self._results.read_all() if r.run_id == run_id]

    def _create_run(self, body: BacktestRunCreate, triggered_by: str) -> BacktestRun:
        now = datetime.now(timezone.utc)
        run_id = str(uuid.uuid4())
        run = BacktestRun(
            **{**body.model_dump(), "triggered_by": triggered_by},
            run_id=run_id,
            status="pending",
            started_at=None,
            ended_at=None,
            recorded_at=now,
        )
        self._runs.upsert(run)
        log.info("backtest.submitted", run_id=run_id)

        data = body.model_dump()
        config = BacktestConfig(
            run_id=run_id,
            instrument=data.get("instrument", "NIFTY"),
            start_date=data["start_date"],
            end_date=data["end_date"],
            model_version=data["model_version"],
            strategy_params=data.get("strategy_params"),
        )
        threading.Thread(target=_run_backtest_job, args=(run_id, config), daemon=True).start()
        return run
