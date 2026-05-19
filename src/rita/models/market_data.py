"""ORM model for the market_data_cache table (OHLCV price data)."""
from sqlalchemy import Column, Date, DateTime, Float, Integer, String

from rita.database import Base


class MarketDataCacheModel(Base):
    __tablename__ = "market_data_cache"

    cache_id = Column(String, primary_key=True)
    date = Column(Date, nullable=False)
    underlying = Column(String, nullable=False)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    shares_traded = Column(Integer, nullable=True)
    turnover_cr = Column(Float, nullable=True)
    recorded_at = Column(DateTime, nullable=False)
