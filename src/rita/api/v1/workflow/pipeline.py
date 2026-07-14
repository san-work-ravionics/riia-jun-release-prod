"""Workflow router for pipeline orchestration and instrument selection.

ADR-001 Tier 2: stateful orchestrations and long-running ML jobs.
  - POST /instrument/select  — set active instrument (persists to config_overrides)
  - GET  /training-progress  — live training progress poll
  - POST /pipeline           — full train+backtest orchestration (JWT required)
  - POST /backtest           — convenience no-auth quick backtest

URLs preserved from observability.py (Option A migration).
"""
from __future__ import annotations

import threading
import uuid
from datetime import date, datetime, timezone, timedelta
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from rita.auth import get_current_user
from rita.core.ml_dispatch import load_instrument_defaults
from rita.database import get_db, SessionLocal
from rita.repositories.instrument import InstrumentRepository
from rita.repositories.config_overrides import ConfigOverridesRepository
from rita.schemas.config_overrides import ConfigOverride
from rita.services.workflow_service import get_live_progress
from rita.logging_config import log_event

log = structlog.get_logger()

router = APIRouter(prefix="/api/v1", tags=["workflow:pipeline"])

_COUNTRY_FLAG = {"IN": "\U0001f1ee\U0001f1f3", "US": "\U0001f1fa\U0001f1f8", "NL": "\U0001f1f3\U0001f1f1"}


# ── Active instrument helpers ─────────────────────────────────────────────────

def _get_active_instrument_id(db: Session) -> str:
    try:
        cfg = ConfigOverridesRepository(db).find_by_id("active_instrument_id")
        if cfg and cfg.value:
            return cfg.value.upper()
    except Exception:
        log_event(log, "error", "pipeline.error", stage="read_active_instrument_id", exc_info=True)
    return "NIFTY"


def _set_active_instrument_id(db: Session, instrument_id: str) -> None:
    now = datetime.now(timezone.utc)
    ConfigOverridesRepository(db).upsert(ConfigOverride(
        override_id="active_instrument_id",
        key="active_instrument_id",
        value=instrument_id,
        stage="active",
        description="Currently active trading instrument",
        saved_at=now,
        recorded_at=now,
    ))


# ── POST /api/v1/instrument/select ────────────────────────────────────────────

class _SelectInstrumentBody(BaseModel):
    instrument_id: str


@router.post("/instrument/select", summary="Set the active instrument")
def select_instrument(
    body: _SelectInstrumentBody,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Switch the active instrument. Persists to config_overrides (survives restart)."""
    repo = InstrumentRepository(db)
    inst = repo.find_by_id(body.instrument_id.upper())
    if inst is None:
        raise HTTPException(status_code=404, detail=f"Instrument '{body.instrument_id}' not found.")
    _set_active_instrument_id(db, inst.instrument_id)
    log.info("instrument.selected", instrument_id=inst.instrument_id)
    return {
        "id":       inst.instrument_id,
        "name":     inst.name,
        "flag":     _COUNTRY_FLAG.get(inst.country_code, ""),
        "exchange": inst.exchange,
        "lot_size": inst.lot_size,
    }


# ── GET /api/v1/training-progress ─────────────────────────────────────────────

@router.get("/training-progress", summary="Live training progress for the current run")
def training_progress(run_id: Optional[str] = None) -> list[dict[str, Any]]:
    """Return live progress records polled every 2 s by the DS dashboard during training."""
    return get_live_progress(run_id)


# ── POST /api/v1/pipeline (JWT required) ──────────────────────────────────────

class PipelineRequest(BaseModel):
    instrument: str = "NIFTY"
    target_return_pct: float = 15.0
    time_horizon_days: int = 365
    risk_tolerance: str = "moderate"
    timesteps: int = 200_000
    force_retrain: bool = False
    n_seeds: int = 1
    sim_start: Optional[str] = None
    sim_end: Optional[str] = None


class PipelineResponse(BaseModel):
    status: str
    message: str
    train_run_id: Optional[str] = None
    backtest_run_id: Optional[str] = None


def _run_pipeline_job(
    train_run_id: str,
    backtest_run_id: str,
    req: PipelineRequest,
) -> None:
    """Background thread: run full train → backtest pipeline."""
    from rita.schemas.training import TrainingRunCreate, TrainingRun
    from rita.schemas.backtest import BacktestRunCreate, BacktestRun
    from rita.repositories.training import TrainingRunsRepository
    from rita.repositories.backtest import BacktestRunsRepository
    from rita.core.ml_dispatch import TrainingConfig
    from rita.core.data_loader import model_dir
    from rita.core.backtest_dispatch import BacktestConfig
    from rita.services.backtest_service import _run_backtest_job

    db = SessionLocal()
    try:
        inst_defaults = load_instrument_defaults(req.instrument)
        train_body = TrainingRunCreate(
            instrument=req.instrument,
            model_version=f"pipeline-{train_run_id[:8]}",
            algorithm="DoubleDQN",
            timesteps=req.timesteps,
            learning_rate=inst_defaults.get("learning_rate", 1e-4),
            buffer_size=inst_defaults.get("buffer_size", 50_000),
            net_arch="[128, 128]",
            exploration_pct=inst_defaults.get("exploration_pct", 0.1),
            notes=f"pipeline risk={req.risk_tolerance} target={req.target_return_pct}%",
        )
        now = datetime.now(timezone.utc)
        run = TrainingRun(
            **train_body.model_dump(),
            run_id=train_run_id,
            status="pending",
            started_at=None,
            ended_at=None,
            recorded_at=now,
        )
        TrainingRunsRepository(db).upsert(run)

        mdir = model_dir(req.instrument)
        config = TrainingConfig(
            run_id=train_run_id,
            instrument=req.instrument,
            model_version=train_body.model_version,
            algorithm=train_body.algorithm,
            timesteps=train_body.timesteps,
            learning_rate=train_body.learning_rate,
            buffer_size=train_body.buffer_size,
            net_arch=train_body.net_arch,
            exploration_pct=train_body.exploration_pct,
            output_dir=str(mdir),
            n_seeds=req.n_seeds,
        )

        existing_zips = sorted(mdir.glob("*.zip"))
        if not req.force_retrain and existing_zips:
            existing_model_path = existing_zips[-1]
            reused_model_version = existing_model_path.stem
            log.info("pipeline.reuse_model", instrument=req.instrument, model_path=str(existing_model_path))
            runs_repo2 = TrainingRunsRepository(db)
            reused_run = runs_repo2.find_by_id(train_run_id)
            if reused_run is not None:
                runs_repo2.upsert(TrainingRun(**{
                    **reused_run.model_dump(),
                    "status": "complete",
                    "started_at": datetime.now(timezone.utc),
                    "ended_at": datetime.now(timezone.utc),
                    "model_path": str(existing_model_path),
                    "notes": (reused_run.notes or "") + " [reused existing model]",
                }))
        else:
            from rita.services.workflow_service import _run_training_job
            _run_training_job(config)
            reused_model_version = train_body.model_version

        if req.sim_end:
            end_date = date.fromisoformat(req.sim_end)
        else:
            end_date = date.today()
        if req.sim_start:
            start_date = date.fromisoformat(req.sim_start)
        else:
            start_date = end_date - timedelta(days=req.time_horizon_days)

        bt_run = BacktestRun(
            **BacktestRunCreate(
                instrument=req.instrument,
                start_date=start_date,
                end_date=end_date,
                model_version=reused_model_version,
                triggered_by="pipeline",
            ).model_dump(),
            run_id=backtest_run_id,
            status="pending",
            started_at=None,
            ended_at=None,
            recorded_at=datetime.now(timezone.utc),
        )
        BacktestRunsRepository(db).upsert(bt_run)
        bt_config = BacktestConfig(
            run_id=backtest_run_id,
            start_date=start_date,
            end_date=end_date,
            model_version=reused_model_version,
            strategy_params=None,
            instrument=req.instrument,
        )
        _run_backtest_job(backtest_run_id, bt_config)
    except Exception:
        log.error("pipeline.failed", train_run_id=train_run_id, exc_info=True)
    finally:
        db.close()


@router.post(
    "/pipeline",
    response_model=PipelineResponse,
    status_code=202,
    dependencies=[Depends(get_current_user)],
    summary="Trigger a full train+backtest pipeline run (JWT required)",
)
def run_pipeline(req: PipelineRequest) -> PipelineResponse:
    """Start train → backtest asynchronously. Poll /progress or /workflow/train/{id} for status."""
    train_run_id    = str(uuid.uuid4())
    backtest_run_id = str(uuid.uuid4())
    threading.Thread(
        target=_run_pipeline_job,
        args=(train_run_id, backtest_run_id, req),
        daemon=True,
    ).start()
    log.info("pipeline.submitted", train_run_id=train_run_id, backtest_run_id=backtest_run_id,
             timesteps=req.timesteps, n_seeds=req.n_seeds, force_retrain=req.force_retrain,
             instrument=req.instrument)
    return PipelineResponse(
        status="accepted",
        message="Pipeline started. Poll /progress for status.",
        train_run_id=train_run_id,
        backtest_run_id=backtest_run_id,
    )


# ── POST /api/v1/backtest (convenience, no auth) ──────────────────────────────

class _BacktestQuickRequest(BaseModel):
    instrument: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    model_version: str = "latest"
    triggered_by: str = "user"


@router.post("/backtest", summary="Submit a backtest run (convenience, no auth)", status_code=202)
def submit_backtest_quick(
    req: _BacktestQuickRequest = _BacktestQuickRequest(),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Trigger a backtest without JWT. Defaults to 1-year lookback ending today."""
    from rita.repositories.backtest import BacktestRunsRepository
    from rita.schemas.backtest import BacktestRun
    from rita.core.backtest_dispatch import BacktestConfig
    from rita.services.backtest_service import _run_backtest_job

    end = date.today()
    start = end - timedelta(days=365)

    if req.end_date:
        try:
            end = date.fromisoformat(req.end_date)
        except ValueError:
            pass
    if req.start_date:
        try:
            start = date.fromisoformat(req.start_date)
        except ValueError:
            pass

    instrument = (req.instrument or _get_active_instrument_id(db)).upper()
    run_id = str(uuid.uuid4())
    now    = datetime.now(timezone.utc)

    run = BacktestRun(
        run_id=run_id,
        instrument=instrument,
        start_date=start,
        end_date=end,
        model_version=req.model_version,
        triggered_by=req.triggered_by,
        status="pending",
        started_at=None,
        ended_at=None,
        recorded_at=now,
    )
    BacktestRunsRepository(db).upsert(run)

    cfg = BacktestConfig(
        run_id=run_id,
        instrument=instrument,
        start_date=start,
        end_date=end,
        model_version=req.model_version,
        strategy_params=None,
    )
    threading.Thread(target=_run_backtest_job, args=(run_id, cfg), daemon=True).start()
    log.info("backtest_quick.submitted", run_id=run_id)
    return {"status": "accepted", "run_id": run_id, "message": "Backtest started."}
