"""Pydantic schemas for DS instrument model build status endpoint."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class InstrumentBuildStatusItem(BaseModel):
    symbol: str
    name: Optional[str] = None
    last_trained: Optional[str] = None
    build_status: str
    model_version: Optional[str] = None
    error_message: Optional[str] = None
    model_file_exists: bool
    # Phase 2 — per-instrument metrics (all from training_runs table)
    return_pct: Optional[float] = None
    cagr_pct: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    win_rate_pct: Optional[float] = None  # not in training_runs; always None
    sharpe_constraint_met: Optional[bool] = None
    drawdown_constraint_met: Optional[bool] = None
    constraints_met: Optional[bool] = None
    last_run_round: Optional[str] = None
    last_run_timestamp: Optional[str] = None
    last_run_timesteps: Optional[int] = None


class DsInstrumentBuildStatusResponse(BaseModel):
    instruments: list[InstrumentBuildStatusItem]
    total: int
    as_of: str
