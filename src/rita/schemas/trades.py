"""Pydantic schemas for the trades table (closed/executed positions)."""
from datetime import date, datetime
from typing import Optional, Literal
from pydantic import BaseModel, ConfigDict, Field


class TradeBase(BaseModel):
    instrument: str = Field(max_length=64)
    underlying: Literal["NIFTY", "BANKNIFTY"]
    expiry: str = Field(max_length=16)       # e.g. 24-Apr-26
    option_type: Literal["CE", "PE"]
    strike: float = Field(ge=0)
    side: Literal["Long", "Short"]
    pnl: float
    notes: Optional[str] = Field(default=None, max_length=512)
    closed_date: Optional[date] = None


class TradeCreate(TradeBase):
    pass


class Trade(TradeBase):
    model_config = ConfigDict(from_attributes=True)

    trade_id: str
    recorded_at: datetime
