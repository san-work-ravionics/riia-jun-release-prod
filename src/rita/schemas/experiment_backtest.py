"""Pydantic schemas for the FnO Experiment Backtest endpoint."""
from pydantic import BaseModel


class ExperimentEntry(BaseModel):
    date: str
    nifty_open: float
    nifty_close: float
    call_strike: float
    put_strike: float
    call_premium: float
    put_premium: float
    call_lots: int
    put_lots: int
    lot_size: int
    iv_pct: float
    entry_cost: float
    exit_value: float
    call_pnl: float
    put_pnl: float
    winner: str
    trigger_spot: float
    day_pnl: float
    day_pnl_pct: float
    cum_pnl: float
    exit_type: str
    price_source: str


class ExperimentSummary(BaseModel):
    period: str
    total_trades: int
    wins: int
    losses: int
    win_rate_pct: float
    total_pnl: float
    avg_pnl: float
    target_hits: int
    sl_hits: int
    time_exits: int
    target_pct: float
    sl_pct: float
    best_day: float
    worst_day: float
    real_price_days: int
    bsm_price_days: int


class ExperimentBacktestPayload(BaseModel):
    summary: ExperimentSummary
    entries: list[ExperimentEntry]
