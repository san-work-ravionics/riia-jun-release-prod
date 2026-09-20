"""Repository for the nse_option_bhav table (NSE F&O Bhav copy data)."""
from __future__ import annotations

import threading
import time

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from rita.models.nse_option_bhav import NseOptionBhavModel

log = structlog.get_logger()

# Module-level cache for option price lookups (static reference data)
_cache_lock = threading.Lock()
_price_cache: dict[tuple[str, int, str], dict] | None = None
_cache_count: int = 0


def _build_cache(db: Session) -> dict[tuple[str, int, str], dict]:
    """Load all bhav data into a nearest-expiry lookup dict."""
    t0 = time.time()
    m = NseOptionBhavModel
    stmt = select(m.date, m.strike, m.option_type, m.expiry,
                  m.open, m.high, m.low, m.close, m.oi)

    raw: dict[tuple, list] = {}
    for r in db.execute(stmt):
        key = (str(r[0]), r[1], r[2])
        entry = {
            "open": r[4], "high": r[5], "low": r[6], "close": r[7],
            "expiry": str(r[3]), "oi": r[8],
        }
        if key not in raw:
            raw[key] = []
        raw[key].append(entry)

    lookup: dict[tuple, dict] = {}
    for key, contracts in raw.items():
        trade_date = key[0]
        nearest = min(
            contracts,
            key=lambda c: c["expiry"] if c["expiry"] >= trade_date else "9999",
        )
        lookup[key] = nearest

    elapsed = time.time() - t0
    log.info("bhav_cache_built", entries=len(lookup), seconds=round(elapsed, 1))
    return lookup


def invalidate_cache() -> None:
    """Clear the in-memory cache (call after import/delete)."""
    global _price_cache, _cache_count
    with _cache_lock:
        _price_cache = None
        _cache_count = 0


class NseOptionBhavRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_option_prices(self) -> dict[tuple[str, int, str], dict]:
        """Return cached lookup dict, building it on first call."""
        global _price_cache, _cache_count
        with _cache_lock:
            if _price_cache is None:
                _price_cache = _build_cache(self._db)
                _cache_count = len(_price_cache)
            return _price_cache

    def count(self) -> int:
        return self._db.query(func.count(NseOptionBhavModel.id)).scalar() or 0

    def date_range(self) -> tuple[str | None, str | None]:
        row = self._db.query(
            func.min(NseOptionBhavModel.date),
            func.max(NseOptionBhavModel.date),
        ).one()
        mn, mx = row
        return (str(mn) if mn else None, str(mx) if mx else None)

    def bulk_insert(self, records: list[dict], batch_size: int = 5000) -> int:
        """Insert records in batches. Returns total inserted."""
        total = 0
        for i in range(0, len(records), batch_size):
            batch = records[i : i + batch_size]
            self._db.bulk_insert_mappings(NseOptionBhavModel, batch)
            self._db.commit()
            total += len(batch)
        invalidate_cache()
        return total

    def delete_all(self) -> int:
        count = self._db.query(NseOptionBhavModel).delete()
        self._db.commit()
        invalidate_cache()
        return count
