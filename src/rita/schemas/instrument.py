"""Pydantic schemas for the instruments table."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class InstrumentCreate(BaseModel):
    instrument_id: str = Field(..., max_length=20)
    name:          str = Field(..., max_length=100)
    exchange:      str = Field(..., max_length=20)
    country_code:  str = Field(..., max_length=5)
    currency:      Optional[str] = Field(None, max_length=10)
    lot_size:      Optional[int] = Field(None, ge=1)
    is_available:  bool = False
    yf_ticker:     Optional[str] = None


class InstrumentAvailabilityUpdate(BaseModel):
    is_available: bool


class Instrument(InstrumentCreate):
    model_config = ConfigDict(from_attributes=True)

    created_at: datetime
