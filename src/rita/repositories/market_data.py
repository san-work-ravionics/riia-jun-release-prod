"""Repository for the market_data_cache table (OHLCV price data).

F44 P2: daily FX rates live here too, as ``underlying = "FX_EURINR"`` / ``"FX_EURUSD"`` rows
(``close`` = units of quote currency per 1 EUR), written only by
``services/data_refresh.refresh_fx`` (the refresh skill run) and read by ``services/fx_service``.
"""

import uuid
from datetime import date, datetime, timezone

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

    def find_latest_on_or_before(self, underlying: str, as_of: date) -> MarketDataCacheModel | None:
        """Most recent cached row for an underlying with ``date <= as_of``, or None."""
        return (
            self._db.query(MarketDataCacheModel)
            .filter(
                MarketDataCacheModel.underlying == underlying.upper(),
                MarketDataCacheModel.date <= as_of,
            )
            .order_by(MarketDataCacheModel.date.desc())
            .first()
        )

    def existing_dates(self, underlying: str) -> set[date]:
        """Every cached date for an underlying."""
        rows = (
            self._db.query(MarketDataCacheModel.date)
            .filter(MarketDataCacheModel.underlying == underlying.upper())
            .all()
        )
        return {r[0] for r in rows}

    def add_daily_rows(self, underlying: str, rows: list[tuple[date, float, float, float, float]]) -> int:
        """Insert ``(date, open, high, low, close)`` rows whose date is not cached yet; commits.

        Insert-only (no merge, no delete).  Returns the number of rows inserted.
        """
        und = underlying.upper()
        have = self.existing_dates(und)
        now = datetime.now(timezone.utc)
        new = []
        for d, o, h, lo, c in rows:
            if d in have:
                continue
            have.add(d)
            new.append(MarketDataCacheModel(
                cache_id=str(uuid.uuid4()), date=d, underlying=und,
                open=o, high=h, low=lo, close=c, shares_traded=None, turnover_cr=None,
                recorded_at=now,
            ))
        if new:
            self._db.add_all(new)
            self._db.commit()
        return len(new)

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

    def find_closes(self, underlying: str, start: date, end: date) -> list[tuple[date, float]]:
        """(date, close) pairs for an underlying with start <= date <= end, oldest-first.

        Read-only; rows with a null close are skipped.
        """
        rows = (
            self._db.query(MarketDataCacheModel.date, MarketDataCacheModel.close)
            .filter(
                MarketDataCacheModel.underlying == underlying.upper(),
                MarketDataCacheModel.date >= start,
                MarketDataCacheModel.date <= end,
                MarketDataCacheModel.close.isnot(None),
            )
            .order_by(MarketDataCacheModel.date.asc())
            .all()
        )
        return [(r[0], float(r[1])) for r in rows]
