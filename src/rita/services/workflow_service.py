"""WorkflowService — DQN training job tracking and dispatch.

ADR-001: Workflow routers call services only.
ADR-002: All data access via repository classes.

Sprint 2: Creates job records with status=pending and persists them.
Sprint 3: Plugs in actual ML dispatch (stable-baselines3 DoubleDQN) via a
          daemon thread so the API returns immediately with status=pending.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy.orm import Session

from rita.core.ml_dispatch import TrainingConfig, load_instrument_defaults, train
from rita.database import SessionLocal
from rita.logging_config import log_event
from rita.repositories.training import TrainingMetricsRepository, TrainingRunsRepository
from rita.schemas.training import TrainingMetric, TrainingRun, TrainingRunCreate

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Live training progress — in-memory, per run_id
# Keyed by run_id; value is list of {timestep, loss, ep_rew_mean} records.
# Cleared when a new run starts; retained after completion for the last read.
# ---------------------------------------------------------------------------
_live_progress: dict[str, list[dict]] = {}
_current_run_id: str | None = None


def get_live_progress(run_id: str | None = None) -> list[dict]:
    """Return live progress records for run_id, or the most recent run."""
    if run_id and run_id in _live_progress:
        return _live_progress[run_id]
    if _current_run_id and _current_run_id in _live_progress:
        return _live_progress[_current_run_id]
    return []


# ---------------------------------------------------------------------------
# Module-level background worker
# ---------------------------------------------------------------------------


def _run_training_job(config: TrainingConfig) -> None:
    """Background thread: run training and persist all results."""
    db = SessionLocal()
    try:
        runs_repo = TrainingRunsRepository(db)
        metrics_repo = TrainingMetricsRepository(db)

        run = runs_repo.find_by_id(config.run_id)
        if run is None:
            return

        run = TrainingRun(
            **{**run.model_dump(), "status": "running", "started_at": datetime.now(timezone.utc)}
        )
        runs_repo.upsert(run)
        log_event(log, "info", "training.running", run_id=config.run_id)

        # Set up live progress tracking
        global _current_run_id
        _current_run_id = config.run_id
        _live_progress[config.run_id] = []

        def _push_progress(record: dict) -> None:
            _live_progress[config.run_id].append(record)

        try:
            outcome = train(config, progress_fn=_push_progress)
        except Exception as _exc:
            log_event(log, "error", "training.failed", run_id=config.run_id, error=str(_exc))
            run = runs_repo.find_by_id(config.run_id)
            if run is not None:
                runs_repo.upsert(
                    TrainingRun(
                        **{**run.model_dump(), "status": "failed", "ended_at": datetime.now(timezone.utc)}
                    )
                )
            return

        ended_at = datetime.now(timezone.utc)
        run = runs_repo.find_by_id(config.run_id)
        if run is None:
            return

        val_mdd_pct = round(outcome.max_drawdown * 100, 2)
        val_constraints = outcome.sharpe >= 1.0 and abs(val_mdd_pct) < 10
        complete_run = TrainingRun(
            **{
                **run.model_dump(),
                "status": "complete",
                "ended_at": ended_at,
                "model_path": outcome.model_path,
                "train_sharpe": outcome.train_sharpe,
                "train_mdd": outcome.train_mdd,
                "train_return": outcome.train_return,
                "train_trades": outcome.train_trades,
                "val_sharpe": outcome.sharpe,
                "val_mdd": outcome.max_drawdown,
                "val_return": outcome.total_return,
                "val_cagr": outcome.total_return,   # proxy until CAGR computed separately
                "val_trades": outcome.val_trades,
                "backtest_sharpe": outcome.sharpe,
                "backtest_mdd": outcome.max_drawdown,
                "backtest_return": outcome.total_return,
                "backtest_trades": outcome.val_trades,
            }
        )
        runs_repo.upsert(complete_run)
        duration_s = round((ended_at - run.started_at).total_seconds(), 1) if run.started_at else None
        log_event(log, "info", "training.complete", run_id=config.run_id, duration_s=duration_s)

        try:
            from rita.core.training_tracker import TrainingTracker
            tracker = TrainingTracker(config.output_dir)
            tracker.record_round(
                training_metrics={
                    "timesteps_trained": config.timesteps,
                    "source": "trained",
                    "seed": 42,
                },
                val_metrics={
                    "sharpe_ratio": outcome.sharpe,
                    "max_drawdown_pct": val_mdd_pct,
                    "portfolio_cagr_pct": round(outcome.total_return * 100, 2),
                    "constraints_met": val_constraints,
                },
                backtest_metrics={
                    "sharpe_ratio": outcome.sharpe,
                    "max_drawdown_pct": val_mdd_pct,
                    "portfolio_total_return_pct": round(outcome.total_return * 100, 2),
                    "portfolio_cagr_pct": round(outcome.total_return * 100, 2),
                    "total_trades": outcome.val_trades,
                    "constraints_met": val_constraints,
                },
                notes=f"run_id={config.run_id[:8]}",
            )
            log.info("training.round_recorded", run_id=config.run_id)
        except Exception:
            log.warning("training.tracker_failed", run_id=config.run_id, exc_info=True)

        for ep in outcome.episode_metrics:
            metrics_repo.upsert(
                TrainingMetric(
                    metric_id=str(uuid.uuid4()),
                    run_id=config.run_id,
                    episode=ep["episode"],
                    reward=ep["reward"],
                    loss=ep["loss"],
                    epsilon=ep["epsilon"],
                    portfolio_value=ep["portfolio_value"],
                    recorded_at=ended_at,
                )
            )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Service class
# ---------------------------------------------------------------------------


class WorkflowService:
    def __init__(self, db: Session) -> None:
        self._runs = TrainingRunsRepository(db)
        self._metrics = TrainingMetricsRepository(db)

    def start_training(self, body: TrainingRunCreate) -> TrainingRun:
        """Create a training run record with status=pending and dispatch."""
        now = datetime.now(timezone.utc)
        run_id = str(uuid.uuid4())
        run = TrainingRun(
            **body.model_dump(),
            run_id=run_id,
            status="pending",
            started_at=None,
            ended_at=None,
            recorded_at=now,
        )
        self._runs.upsert(run)
        from rita.core.data_loader import model_dir
        settings = body.model_dump()
        instrument = settings.get("instrument", "NIFTY")
        log_event(log, "info", "training.submitted", run_id=run_id, model=settings.get("model_version"), instrument=instrument)
        inst_defaults = load_instrument_defaults(instrument)
        config = TrainingConfig(
            run_id=run_id,
            instrument=instrument,
            model_version=settings["model_version"],
            algorithm=settings.get("algorithm", "DoubleDQN"),
            timesteps=settings["timesteps"],
            learning_rate=settings["learning_rate"],
            buffer_size=settings["buffer_size"],
            net_arch=settings["net_arch"],
            exploration_pct=settings["exploration_pct"],
            output_dir=str(model_dir(instrument)),
            n_seeds=inst_defaults.get("n_seeds", 1),
        )
        threading.Thread(target=_run_training_job, args=(config,), daemon=True).start()
        return run

    def get_run(self, run_id: str) -> TrainingRun | None:
        return self._runs.find_by_id(run_id)

    def list_runs(self) -> list[TrainingRun]:
        return self._runs.read_all()

    def list_metrics(self, run_id: str) -> list[TrainingMetric]:
        return [m for m in self._metrics.read_all() if m.run_id == run_id]
