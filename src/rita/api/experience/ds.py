"""Experience router for DS dashboard aggregated initial-load payload.

ADR-001 Tier 3: aggregated experience endpoint — instruments list,
last 10 training runs, training split dates. No DB writes.
URL: GET /api/experience/ds/
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from rita.config import get_settings
from rita.database import get_db
from rita.logging_config import log_event
from rita.schemas.ds_instrument_status import (
    DsInstrumentBuildStatusResponse,
    InstrumentBuildStatusItem,
)

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
            if i.is_available
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


@router.get(
    "/instrument-build-status",
    response_model=DsInstrumentBuildStatusResponse,
    summary="All instruments with model build status and model file existence",
)
def get_instrument_build_status(db: Session = Depends(get_db)) -> DsInstrumentBuildStatusResponse:
    """Return build status for every tracked instrument.

    Read-only. No db.commit().
    Model file existence is checked via get_settings().model.path — never hardcoded.
    """
    from rita.repositories.instrument import InstrumentRepository
    from rita.repositories.training import TrainingRunsRepository

    settings = get_settings()
    model_base = Path(settings.model.path)

    # Latest training run per instrument symbol
    runs_by_symbol: dict[str, Any] = {}
    try:
        latest_runs = TrainingRunsRepository(db).get_latest_per_instrument()
        for run in latest_runs:
            runs_by_symbol[run.instrument.upper()] = run
    except Exception:
        log.warning("experience.ds.instrument_build_status.runs_error", exc_info=True)

    # All instruments (all, not just is_available)
    try:
        all_instruments = InstrumentRepository(db).read_all()
    except Exception:
        log.warning("experience.ds.instrument_build_status.instruments_error", exc_info=True)
        all_instruments = []

    items: list[InstrumentBuildStatusItem] = []
    for inst in all_instruments:
        symbol = inst.instrument_id.upper()
        run = runs_by_symbol.get(symbol)

        # Determine build_status
        if run is None:
            build_status = "never_trained"
            last_trained = None
            model_version = None
            error_message = None
        elif run.status == "complete":
            build_status = "success"
            last_trained = run.recorded_at.isoformat() if run.recorded_at else None
            model_version = run.model_version
            error_message = None
        elif run.status == "failed":
            build_status = "failed"
            last_trained = run.recorded_at.isoformat() if run.recorded_at else None
            model_version = run.model_version
            error_message = run.notes
        else:
            build_status = run.status  # pending / running — surface as-is
            last_trained = run.recorded_at.isoformat() if run.recorded_at else None
            model_version = run.model_version
            error_message = None

        # Check for model ZIP file
        model_file_exists = False
        try:
            model_dir = model_base / symbol
            model_file_exists = any(model_dir.glob("*.zip"))
        except OSError:
            log.warning(
                "experience.ds.instrument_build_status.glob_error",
                symbol=symbol,
                model_dir=str(model_base / symbol),
            )

        items.append(
            InstrumentBuildStatusItem(
                symbol=symbol,
                name=inst.name,
                last_trained=last_trained,
                build_status=build_status,
                model_version=model_version,
                error_message=error_message,
                model_file_exists=model_file_exists,
            )
        )

    return DsInstrumentBuildStatusResponse(
        instruments=items,
        total=len(items),
        as_of=datetime.now(timezone.utc).isoformat(),
    )
