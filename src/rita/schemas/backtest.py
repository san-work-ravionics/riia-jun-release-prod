"""Pydantic schemas for backtest_runs and backtest_results tables."""
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


# ── Backtest Runs ─────────────────────────────────────────────────────────────

class BacktestRunBase(BaseModel):
    instrument: str = Field(default="NIFTY", max_length=32)
    start_date: date
    end_date: date
    model_version: str = Field(max_length=64)
    strategy_params: Optional[str] = Field(default=None, max_length=512)  # JSON string of params
    triggered_by: Optional[str] = Field(default=None, max_length=64)      # agent or user


class BacktestRunCreate(BacktestRunBase):
    pass


class BacktestRun(BacktestRunBase):
    model_config = ConfigDict(from_attributes=True)

    run_id: str
    status: str = "pending"                 # pending / running / complete / failed
    total_trades: Optional[int] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    recorded_at: datetime


# ── Backtest Results (daily) ──────────────────────────────────────────────────

class BacktestResultBase(BaseModel):
    run_id: str
    date: date
    portfolio_value: float                  # normalised (1.0 = start)
    benchmark_value: float                  # normalised buy-and-hold
    allocation: Optional[float] = None      # 0.0–1.0
    close_price: Optional[float] = None     # Nifty close


class BacktestResultCreate(BacktestResultBase):
    pass


class BacktestResult(BacktestResultBase):
    model_config = ConfigDict(from_attributes=True)

    result_id: str
    # Summary metrics (populated when run completes)
    total_return: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    max_drawdown: Optional[float] = None
    recorded_at: datetime
