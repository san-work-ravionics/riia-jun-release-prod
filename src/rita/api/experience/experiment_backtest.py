"""Experience Layer — FnO Experiment Backtest.

ADR-001: Tier 3 (Experience Layer). Read-only, no side effects.
Reads nifty_experiment_daily.csv, runs BSM strangle backtest, returns JSON.
No Zerodha/Kite dependency — CSV is pre-fetched from Kite historical API.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Query

from rita.config import Settings, get_settings
from rita.core.experiment_backtest import run_backtest
from rita.schemas.experiment_backtest import ExperimentBacktestPayload

router = APIRouter(
    prefix="/api/experience/fno",
    tags=["experience:fno-experiment"],
)


@router.get("/experiment-backtest", response_model=ExperimentBacktestPayload)
def get_experiment_backtest(
    target_pct: float = Query(default=15.0, ge=1.0, le=100.0),
    sl_pct: float = Query(default=5.0, ge=0.5, le=50.0),
    settings: Settings = Depends(get_settings),
) -> ExperimentBacktestPayload:
    csv_path = Path(settings.data.input_dir) / "NIFTY" / "nifty_experiment_daily.csv"
    lot_size = settings.instruments.nifty.lot_size

    result = run_backtest(
        csv_path=csv_path,
        lot_size=lot_size,
        target_pct=target_pct,
        sl_pct=sl_pct,
    )

    return ExperimentBacktestPayload(
        summary=result["summary"],
        entries=result["entries"],
    )
