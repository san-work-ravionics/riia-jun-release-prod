"""Repository for the nse_option_bhav table (NSE F&O Bhav copy data)."""
from __future__ import annotations

import gzip
import os
import shutil
import sqlite3
import tempfile
import threading
import time
from pathlib import Path

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from rita.models.nse_option_bhav import NseOptionBhavModel

log = structlog.get_logger()

_cache_lock = threading.Lock()
_price_cache: dict[tuple[str, int, str], dict] | None = None
_cache_count: int = 0

_SEED_PATHS = [
    Path("/app/data/input/NIFTY/nse_option_bhav.db.gz"),
    Path(os.environ.get("RITA_INPUT_DIR", "data/input")) / "NIFTY" / "nse_option_bhav.db.gz",
]

_decompressed_db: str | None = None


def _ensure_decompressed_db() -> str | None:
    """Decompress .db.gz to a temp file once; return its path or None."""
    global _decompressed_db
    if _decompressed_db and os.path.exists(_decompressed_db):
        return _decompressed_db

    gz = next((p for p in _SEED_PATHS if p.exists()), None)
    if gz is None:
        return None

    log.info("bhav.decompress_start", source=str(gz))
    t0 = time.time()
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    try:
        with gzip.open(gz, "rb") as f_in:
            shutil.copyfileobj(f_in, tmp, length=1 << 20)
        tmp.close()
        _decompressed_db = tmp.name
        log.info("bhav.decompress_done", seconds=round(time.time() - t0, 1))
        return _decompressed_db
    except Exception:
        tmp.close()
        os.unlink(tmp.name)
        raise


def _build_cache_from_seed_db(db_path: str) -> dict[tuple[str, int, str], dict]:
    """Read bhav data directly from the seed SQLite file."""
    t0 = time.time()
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cur = conn.execute(
            "SELECT date, strike, option_type, expiry, open, high, low, close, oi "
            "FROM nse_option_bhav"
        )
        raw: dict[tuple, list] = {}
        for row in cur:
            key = (str(row[0]), row[1], row[2])
            entry = {
                "open": row[4], "high": row[5], "low": row[6], "close": row[7],
                "expiry": str(row[3]), "oi": row[8],
            }
            raw.setdefault(key, []).append(entry)
    finally:
        conn.close()

    lookup: dict[tuple, dict] = {}
    for key, contracts in raw.items():
        trade_date = key[0]
        nearest = min(
            contracts,
            key=lambda c: c["expiry"] if c["expiry"] >= trade_date else "9999",
        )
        lookup[key] = nearest

    elapsed = time.time() - t0
    log.info("bhav_cache_built", source="seed_db", entries=len(lookup), seconds=round(elapsed, 1))
    return lookup


def _build_cache(db: Session) -> dict[tuple[str, int, str], dict]:
    """Load all bhav data into a nearest-expiry lookup dict."""
    count = db.query(func.count(NseOptionBhavModel.id)).scalar() or 0
    if count == 0:
        seed_path = _ensure_decompressed_db()
        if seed_path:
            return _build_cache_from_seed_db(seed_path)
        return {}

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
        raw.setdefault(key, []).append(entry)

    lookup: dict[tuple, dict] = {}
    for key, contracts in raw.items():
        trade_date = key[0]
        nearest = min(
            contracts,
            key=lambda c: c["expiry"] if c["expiry"] >= trade_date else "9999",
        )
        lookup[key] = nearest

    elapsed = time.time() - t0
    log.info("bhav_cache_built", source="main_db", entries=len(lookup), seconds=round(elapsed, 1))
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
