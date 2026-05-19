"""Pydantic schemas for the positions table (live open positions from broker)."""
from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, ConfigDict, Field


class PositionBase(BaseModel):
    instrument: str = Field(max_length=64)   # e.g. BANKNIFTY26APR52000CE
    underlying: Literal["NIFTY", "BANKNIFTY", "ASML", "NVIDIA"]
    product: Literal["NRML", "MIS", "CNC"] = "NRML"
    option_type: Optional[Literal["CE", "PE"]] = None
    strike: Optional[float] = Field(default=None, ge=0)
    expiry: Optional[str] = Field(default=None, max_length=16)  # e.g. 26APR
    quantity: int                            # negative = short (can be negative)
    avg_price: float = Field(ge=0)
    last_traded_price: float = Field(ge=0)
    pnl: float
    pct_change: Optional[float] = None


class PositionCreate(PositionBase):
    pass


class Position(PositionBase):
    model_config = ConfigDict(from_attributes=True)

    position_id: str
    recorded_at: datetime
