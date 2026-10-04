"""Repository for the market_data_cache table (OHLCV price data)."""

from sqlalchemy.orm import Session

from rita.models.market_data import MarketDataCacheModel
from rita.repositories.base import SqlRepository
from rita.schemas.market_data import MarketDataCache


class MarketDataCacheRepository(SqlRepository[MarketDataCache, MarketDataCacheModel]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, MarketDataCacheModel, MarketDataCache, "cache_id")

    def find_latest(self, underlying: str) -> MarketDataCacheModel | None:
        """Most recent cached OHLCV row for an underlying (upper-cased), or None."""
        return (
            self._db.query(MarketDataCacheModel)
            .filter(MarketDataCacheModel.underlying == underlying.upper())
            .order_by(MarketDataCacheModel.date.desc())
            .first()
        )

    def find_recent_closes(self, underlying: str, n: int) -> list[float]:
        """Last ``n`` closes for an underlying, oldest-first."""
        rows = (
            self._db.query(MarketDataCacheModel.close)
            .filter(MarketDataCacheModel.underlying == underlying.upper())
            .order_by(MarketDataCacheModel.date.desc())
            .limit(n)
            .all()
        )
        return [r[0] for r in reversed(rows)]
