"""Repository for the market_data_cache table (OHLCV price data)."""

from sqlalchemy.orm import Session

from rita.models.market_data import MarketDataCacheModel
from rita.repositories.base import SqlRepository
from rita.schemas.market_data import MarketDataCache


class MarketDataCacheRepository(SqlRepository[MarketDataCache, MarketDataCacheModel]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, MarketDataCacheModel, MarketDataCache, "cache_id")
