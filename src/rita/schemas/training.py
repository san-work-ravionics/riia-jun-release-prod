"""Pydantic schemas for training_runs and training_metrics tables."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


# ── Training Runs ─────────────────────────────────────────────────────────────

class TrainingRunBase(BaseModel):
    instrument: str = Field(default="NIFTY", max_length=32)  # e.g. NIFTY, BANKNIFTY
    model_version: str = Field(max_length=64)   # e.g. v1.0, v1.1
    algorithm: str = Field(default="DoubleDQN", max_length=64)
    timesteps: int = Field(ge=0)                # e.g. 200000
    learning_rate: float = Field(ge=0)          # e.g. 1e-4
    buffer_size: int = Field(ge=0)              # e.g. 50000
    net_arch: str = Field(max_length=128)       # e.g. [128, 128]
    exploration_pct: float                      # e.g. 0.1
    notes: Optional[str] = Field(default=None, max_length=512)


class TrainingRunCreate(TrainingRunBase):
    pass


class TrainingRun(TrainingRunBase):
    model_config = ConfigDict(from_attributes=True)

    run_id: str
    status: str = "pending"                 # pending / running / complete / failed
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    train_sharpe: Optional[float] = None
    train_mdd: Optional[float] = None
    train_return: Optional[float] = None
    train_trades: Optional[int] = None
    val_sharpe: Optional[float] = None
    val_mdd: Optional[float] = None
    val_return: Optional[float] = None
    val_cagr: Optional[float] = None
    val_trades: Optional[int] = None
    backtest_sharpe: Optional[float] = None
    backtest_mdd: Optional[float] = None
    backtest_return: Optional[float] = None
    backtest_trades: Optional[int] = None
    model_path: Optional[str] = None        # path to .zip model file
    recorded_at: datetime


# ── Training Metrics (per episode) ───────────────────────────────────────────

class TrainingMetricBase(BaseModel):
    run_id: str
    episode: int
    reward: float
    loss: Optional[float] = None
    epsilon: float                          # exploration rate
    portfolio_value: Optional[float] = None


class TrainingMetricCreate(TrainingMetricBase):
    pass


class TrainingMetric(TrainingMetricBase):
    model_config = ConfigDict(from_attributes=True)

    metric_id: str
    recorded_at: datetime
