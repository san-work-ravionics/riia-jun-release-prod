"""Pydantic schemas for the manoeuvres table (manoeuvre group actions)."""
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class ManoeuvreBase(BaseModel):
    timestamp: datetime
    date: date
    month: str = Field(max_length=16)
    action: str = Field(max_length=64)       # e.g. remove, add, roll, adjust
    lot_key: str = Field(max_length=64)      # e.g. NIFTY26APR22700PE_L1
    from_group: Optional[str] = Field(default=None, max_length=64)
    to_group: Optional[str] = Field(default=None, max_length=64)
    nifty_spot: Optional[float] = Field(default=None, ge=0)
    banknifty_spot: Optional[float] = Field(default=None, ge=0)


class ManoeuvreCreate(ManoeuvreBase):
    pass


class Manoeuvre(ManoeuvreBase):
    model_config = ConfigDict(from_attributes=True)

    manoeuvre_id: str
    recorded_at: datetime
