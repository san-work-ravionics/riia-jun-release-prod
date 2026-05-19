"""Pydantic schemas for the paper_positions table (paper/simulated positions)."""
from datetime import date, datetime
from typing import Optional, Literal
from pydantic import BaseModel, ConfigDict, Field


class PaperPositionBase(BaseModel):
    instrument: str = Field(max_length=64)
    underlying: Literal["NIFTY", "BANKNIFTY", "ASML", "NVIDIA"]
    product: Literal["NRML", "MIS", "CNC"] = "NRML"
    option_type: Optional[Literal["CE", "PE"]] = None
    strike: Optional[float] = Field(default=None, ge=0)
    expiry: Optional[str] = Field(default=None, max_length=16)
    quantity: int
    avg_price: float = Field(ge=0)
    last_traded_price: float = Field(ge=0)
    pnl: float
    pct_change: Optional[float] = None
    currency: Literal["INR", "EUR", "USD"] = "INR"
    lot_size: int = Field(default=1, ge=1)
    sl_price: Optional[float] = None
    target_price: Optional[float] = None
    entry_date: Optional[date] = None
    expiry_date: Optional[date] = None


class PaperPositionCreate(PaperPositionBase):
    pass


class PaperPosition(PaperPositionBase):
    model_config = ConfigDict(from_attributes=True)

    position_id: str
    recorded_at: datetime
