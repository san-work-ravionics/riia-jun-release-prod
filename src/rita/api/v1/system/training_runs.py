"""System router for training-run and backtest-run reads.

ADR-001 Tier 1: single-repo reads with light formatting. No business logic.
URLs preserved from observability.py (Option A migration).
"""
from __future__ import annotations

from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from rita.database import get_db
from rita.logging_config import log_event
from rita.repositories.training import TrainingMetricsRepository, TrainingRunsRepository
from rita.repositories.backtest import BacktestRunsRepository

log = structlog.get_logger()

router = APIRouter(prefix="/api/v1", tags=["system:training-runs"])


@router.get("/training-history", summary="Training run history")
def training_history(
    instrument: str = "NIFTY",
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """All training runs for an instrument, newest-first, with phase KPIs as percentages."""
    repo = TrainingRunsRepository(db)
    runs = sorted(
        [r for r in repo.read_all() if (r.instrument or "NIFTY") == instrument],
        key=lambda r: r.recorded_at,
    )

    def _pct(v: Any) -> Optional[float]:
        return round(v * 100, 2) if v is not None else None

    def _f(v: Any) -> Optional[float]:
        return round(v, 4) if v is not None else None

    result = []
    for i, r in enumerate(runs):
        bt_sharpe = _f(r.backtest_sharpe)
        bt_mdd    = _pct(r.backtest_mdd)
        bt_ret    = _pct(r.backtest_return)
        bt_constraints = (
            bool(bt_sharpe >= 1.0 and abs(bt_mdd) < 10)
            if bt_sharpe is not None and bt_mdd is not None else None
        )
        result.append({
            "round":    i + 1,
            "run_id":   r.run_id,
            "instrument": r.instrument or "NIFTY",
            "timestamp":  r.recorded_at.isoformat(),
            "model_version": r.model_version,
            "algorithm": r.algorithm,
            "status":    r.status,
            "timesteps": r.timesteps,
            "source": "trained",
            "train_sharpe":     _f(r.train_sharpe),
            "train_mdd_pct":    _pct(r.train_mdd),
            "train_return_pct": _pct(r.train_return),
            "train_trades":     r.train_trades,
            "val_sharpe":       _f(r.val_sharpe),
            "val_mdd_pct":      _pct(r.val_mdd),
            "val_return_pct":   _pct(r.val_return),
            "val_cagr_pct":     _pct(r.val_cagr),
            "val_trades":       r.val_trades,
            "backtest_sharpe":          bt_sharpe,
            "backtest_mdd_pct":         bt_mdd,
            "backtest_return_pct":      bt_ret,
            "backtest_cagr_pct":        bt_ret,
            "backtest_trades":          r.backtest_trades,
            "backtest_constraints_met": bt_constraints,
            "notes": "",
        })
    result.reverse()
    return result


@router.get("/training-split", summary="Actual train/val/backtest date ranges for an instrument")
def training_split(
    instrument: str = "NIFTY",
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Return the date ranges used for train, validation, and backtest phases."""
    from rita.core.data_understanding import find_instrument_csv
    from rita.core.technical_analyzer import calculate_indicators
    from rita.core.data_loader import load_ohlcv_csv

    result: dict[str, Any] = {
        "train_start": None, "train_end": None,
        "val_start": None,   "val_end": None,
        "backtest_start": None, "backtest_end": None,
    }

    try:
        csv_path = find_instrument_csv(instrument)
        df = load_ohlcv_csv(str(csv_path))
        df = calculate_indicators(df)
        split_idx = int(len(df) * 0.8)
        train_df = df.iloc[:split_idx]
        val_df   = df.iloc[split_idx:]
        result["train_start"] = str(train_df.index[0].date())
        result["train_end"]   = str(train_df.index[-1].date())
        result["val_start"]   = str(val_df.index[0].date())
        result["val_end"]     = str(val_df.index[-1].date())
    except Exception:
        log_event(log, "error", "training_run.error", exc_info=True)

    try:
        runs_repo = BacktestRunsRepository(db)
        completed = [
            r for r in runs_repo.read_all()
            if r.status in ("complete", "completed") and (r.instrument or "NIFTY") == instrument
        ]
        if completed:
            latest = max(completed, key=lambda r: r.ended_at or r.recorded_at)
            result["backtest_start"] = str(latest.start_date)
            result["backtest_end"]   = str(latest.end_date)
    except Exception:
        log_event(log, "error", "training_run.error", exc_info=True)

    return result


@router.get("/training-metrics", summary="Per-episode loss and reward for the latest training run of an instrument")
def training_metrics(
    instrument: str = "NIFTY",
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Return episode metrics (loss, reward, timestep) for the most recent completed training run."""
    runs_repo = TrainingRunsRepository(db)
    completed = sorted(
        [r for r in runs_repo.read_all() if (r.instrument or "NIFTY") == instrument and r.status == "complete"],
        key=lambda r: r.recorded_at,
        reverse=True,
    )
    if not completed:
        # fall back to any status so dev/test runs are still visible
        completed = sorted(
            [r for r in runs_repo.read_all() if (r.instrument or "NIFTY") == instrument],
            key=lambda r: r.recorded_at,
            reverse=True,
        )
    if not completed:
        return []

    run_id = completed[0].run_id
    metrics = sorted(
        TrainingMetricsRepository(db).read_all(),
        key=lambda m: m.episode,
    )
    return [
        {
            "episode":  m.episode,
            "timestep": m.episode * 1000,
            "loss":     round(m.loss, 6)   if m.loss   is not None else None,
            "reward":   round(m.reward, 4) if m.reward is not None else None,
        }
        for m in metrics
        if m.run_id == run_id
    ]


@router.get("/backtest-status/{run_id}", summary="Poll backtest run status")
def backtest_status(run_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Return the status of a backtest run. Used by scenarios.js polling."""
    run = BacktestRunsRepository(db).find_by_id(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id!r} not found")
    return {"run_id": run_id, "status": run.status}
