"""Pydantic schemas for the market_data_cache table (OHLCV price data)."""
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class MarketDataCacheBase(BaseModel):
    date: date
    underlying: str
    open: float
    high: float
    low: float
    close: float
    shares_traded: Optional[int] = None
    turnover_cr: Optional[float] = None     # turnover in ₹ Crore


class MarketDataCacheCreate(MarketDataCacheBase):
    pass


class MarketDataCache(MarketDataCacheBase):
    model_config = ConfigDict(from_attributes=True)

    cache_id: str
    recorded_at: datetime
