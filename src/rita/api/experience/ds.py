"""Experience router for DS dashboard aggregated initial-load payload.

ADR-001 Tier 3: aggregated experience endpoint — instruments list,
last 10 training runs, training split dates. No DB writes.
URL: GET /api/experience/ds/
"""
from __future__ import annotations

import time
from typing import Any

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from rita.database import get_db
from rita.logging_config import log_event

log = structlog.get_logger()

router = APIRouter(prefix="/api/experience/ds", tags=["experience:ds"])


@router.get("/", summary="DS dashboard aggregated payload")
def ds_payload(instrument: str = "NIFTY", db: Session = Depends(get_db)) -> dict[str, Any]:
    from rita.repositories.instrument import InstrumentRepository
    from rita.repositories.training import TrainingRunsRepository
    from rita.repositories.backtest import BacktestRunsRepository
    from rita.core.data_understanding import find_instrument_csv
    from rita.core.data_loader import load_ohlcv_csv
    from rita.core.technical_analyzer import calculate_indicators

    _start = time.monotonic()
    sources: dict[str, Any] = {}

    # ── instruments ──────────────────────────────────────────────────────────
    t0 = time.monotonic()
    try:
        instruments_raw = InstrumentRepository(db).read_all()
        instruments = [
            {"id": i.instrument_id, "name": i.name, "exchange": i.exchange,
             "data_ready": i.is_available}
            for i in instruments_raw
        ]
        sources["instruments"] = {
            "status": "ok" if instruments else "empty",
            "record_count": len(instruments),
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as exc:
        instruments = []
        sources["instruments"] = {
            "status": "error",
            "record_count": 0,
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "error": str(exc),
        }

    # ── training history ──────────────────────────────────────────────────────
    t0 = time.monotonic()
    try:
        runs = sorted(TrainingRunsRepository(db).read_all(), key=lambda r: r.recorded_at, reverse=True)
        history = [
            {"run_id": r.run_id, "status": r.status, "instrument": r.instrument or "NIFTY",
             "model_version": r.model_version, "recorded_at": r.recorded_at.isoformat(),
             "backtest_sharpe": r.backtest_sharpe}
            for r in runs[:10]
        ]
        sources["training_runs"] = {
            "status": "ok" if history else "empty",
            "record_count": len(history),
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as exc:
        history = []
        sources["training_runs"] = {
            "status": "error",
            "record_count": 0,
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "error": str(exc),
        }

    # ── split dates — CSV ─────────────────────────────────────────────────────
    split = {"train_start": None, "train_end": None, "val_start": None, "val_end": None,
             "backtest_start": None, "backtest_end": None}

    t0 = time.monotonic()
    try:
        csv_path = find_instrument_csv(instrument)
        df = calculate_indicators(load_ohlcv_csv(str(csv_path)))
        idx = int(len(df) * 0.8)
        split.update({
            "train_start": str(df.index[0].date()),
            "train_end": str(df.index[idx - 1].date()),
            "val_start": str(df.index[idx].date()),
            "val_end": str(df.index[-1].date()),
        })
        sources["csv_splits"] = {
            "status": "ok",
            "record_count": len(df),
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as exc:
        log_event(log, "error", "experience.ds.source_error", source="csv_splits", exc_info=True)
        sources["csv_splits"] = {
            "status": "error",
            "record_count": 0,
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "error": str(exc),
        }

    # ── split dates — backtest ────────────────────────────────────────────────
    t0 = time.monotonic()
    try:
        bts = [
            r for r in BacktestRunsRepository(db).read_all()
            if r.status in ("complete", "completed") and (r.instrument or "NIFTY") == instrument
        ]
        if bts:
            latest = max(bts, key=lambda r: r.ended_at or r.recorded_at)
            split.update({"backtest_start": str(latest.start_date), "backtest_end": str(latest.end_date)})
        sources["backtest_splits"] = {
            "status": "ok" if bts else "empty",
            "record_count": len(bts),
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as exc:
        log_event(log, "error", "experience.ds.source_error", source="backtest_splits", exc_info=True)
        sources["backtest_splits"] = {
            "status": "error",
            "record_count": 0,
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "error": str(exc),
        }

    # ── overall status + provenance log ──────────────────────────────────────
    statuses = [s["status"] for s in sources.values()]
    if all(s == "ok" for s in statuses):
        overall = "ok"
    elif any(s == "ok" for s in statuses):
        overall = "partial"
    else:
        overall = "error"

    response = {"instruments": instruments, "training_context": {"history": history, "split": split}}

    log_event(
        log, "info", "experience.compose",
        handler="ds_payload",
        duration_ms=int((time.monotonic() - _start) * 1000),
        overall_status=overall,
        response_keys=list(response.keys()),
        sources=sources,
    )

    return response
