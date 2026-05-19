"""Pydantic schemas for the model_registry table."""
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class ModelRegistryBase(BaseModel):
    date: date
    version: str                            # e.g. v1.0
    category: str                           # e.g. Hyperparameter, Architecture
    change: str                             # description of change
    notes: Optional[str] = None
    backtest_sharpe: Optional[float] = None
    backtest_mdd: Optional[float] = None
    backtest_return: Optional[float] = None
    model_path: Optional[str] = None        # relative path to .zip


class ModelRegistryCreate(ModelRegistryBase):
    pass


class ModelRegistry(ModelRegistryBase):
    model_config = ConfigDict(from_attributes=True)

    model_id: str
    is_active: bool = False
    recorded_at: datetime
