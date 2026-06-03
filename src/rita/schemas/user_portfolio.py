"""Pydantic schemas for User Portfolio Store."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


class HoldingItem(BaseModel):
    instrument_id: str
    allocation_pct: float

    @field_validator("allocation_pct")
    @classmethod
    def allocation_must_be_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("allocation_pct must be greater than 0")
        return v


class UserPortfolioCreate(BaseModel):
    name: str | None = None
    holdings: list[HoldingItem]
    total_value_eur: float | None = None


class UserPortfolioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    portfolio_id: str
    key_id: str
    name: str
    holdings: list[HoldingItem]
    total_value_eur: float | None = None
    created_at: datetime
    updated_at: datetime
    is_active: bool
