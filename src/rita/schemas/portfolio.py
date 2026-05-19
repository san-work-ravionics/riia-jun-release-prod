"""Pydantic schemas for the portfolio table (daily performance summary)."""
from datetime import date, datetime
from typing import Optional, Literal
from pydantic import BaseModel, ConfigDict


class PortfolioBase(BaseModel):
    date: date
    underlying: Optional[Literal["NIFTY", "BANKNIFTY", "ASML", "NVIDIA"]] = None
    month: Optional[str] = None
    group_id: Optional[str] = None
    group_name: Optional[str] = None
    view: Optional[Literal["bull", "bear", "neutral"]] = None
    pnl_now: float
    sl_pnl: Optional[float] = None
    target_pnl: Optional[float] = None
    lot_count: int = 0
    nifty_spot: Optional[float] = None
    banknifty_spot: Optional[float] = None
    dte: Optional[int] = None                # days to expiry
    pct_from_sl: Optional[float] = None
    pct_from_target: Optional[float] = None


class PortfolioCreate(PortfolioBase):
    pass


class Portfolio(PortfolioBase):
    model_config = ConfigDict(from_attributes=True)

    portfolio_id: str
    recorded_at: datetime
