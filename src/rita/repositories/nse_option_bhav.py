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

_SEED_PATHS = [
    Path("/app/data/input/NIFTY/nse_option_bhav.db.gz"),
    Path(os.environ.get("RITA_INPUT_DIR", "data/input")) / "NIFTY" / "nse_option_bhav.db.gz",
]


def _ensure_decompressed_db() -> str | None:
    """Decompress .db.gz to a temp file once; return its path or None."""
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
        log.info("bhav.decompress_done", seconds=round(time.time() - t0, 1))
        return tmp.name
    except Exception:
        tmp.close()
        os.unlink(tmp.name)
        raise


def _build_cache_streaming(db_path: str) -> dict[tuple[str, int, str], dict]:
    """Build nearest-expiry lookup from a SQLite DB using SQL aggregation.

    Uses a single SQL query with GROUP BY + MIN to pick the nearest expiry
    per (date, strike, option_type) — no intermediate Python dicts needed.
    Peak memory: only the final reduced lookup (~200-300K entries, ~60MB).
    """
    t0 = time.time()
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cur = conn.execute(
            "SELECT b.date, b.strike, b.option_type, b.open, b.high, "
            "       b.low, b.close, b.expiry, b.oi "
            "FROM nse_option_bhav b "
            "INNER JOIN ("
            "  SELECT date, strike, option_type, "
            "         MIN(CASE WHEN expiry >= date THEN expiry ELSE '9999-12-31' END) AS nearest "
            "  FROM nse_option_bhav "
            "  GROUP BY date, strike, option_type"
            ") g ON b.date = g.date AND b.strike = g.strike "
            "   AND b.option_type = g.option_type AND b.expiry = g.nearest"
        )
        lookup: dict[tuple, dict] = {}
        for row in cur:
            key = (str(row[0]), row[1], row[2])
            lookup[key] = {
                "open": row[3], "high": row[4], "low": row[5],
                "close": row[6], "expiry": str(row[7]), "oi": row[8],
            }
    finally:
        conn.close()

    elapsed = time.time() - t0
    log.info("bhav_cache_built", source="streaming", entries=len(lookup),
             seconds=round(elapsed, 1))
    return lookup


def _build_cache(db: Session) -> dict[tuple[str, int, str], dict]:
    """Load bhav data into a nearest-expiry lookup dict."""
    count = db.query(func.count(NseOptionBhavModel.id)).scalar() or 0
    if count == 0:
        return {}

    # Get the main DB file path for raw sqlite3 streaming query
    bind = db.get_bind()
    db_url = str(bind.url)
    if "sqlite" in db_url:
        db_path = db_url.replace("sqlite:///", "").replace("sqlite://", "")
        if db_path and os.path.exists(db_path):
            return _build_cache_streaming(db_path)

    # Fallback: SQLAlchemy streaming (for non-file-path SQLite or other DBs)
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
    log.info("bhav_cache_built", source="main_db", entries=len(lookup),
             seconds=round(elapsed, 1))
    return lookup


def invalidate_cache() -> None:
    """Clear the in-memory cache (call after import/delete)."""
    global _price_cache
    with _cache_lock:
        _price_cache = None


def seed_from_compressed_db(main_db_path: str) -> dict:
    """Seed nse_option_bhav table from the compressed .db.gz seed file.

    Uses SQLite ATTACH for a direct DB-to-DB copy — zero Python memory
    for the row data. Safe to run on a 1GB t3.micro.
    """
    seed_path = _ensure_decompressed_db()
    if seed_path is None:
        return {"error": "Seed file not found", "searched": [str(p) for p in _SEED_PATHS]}

    t0 = time.time()
    try:
        conn = sqlite3.connect(main_db_path)
        conn.execute("ATTACH DATABASE ? AS seed", (seed_path,))

        existing = conn.execute("SELECT COUNT(*) FROM nse_option_bhav").fetchone()[0]
        if existing > 0:
            conn.execute("DELETE FROM nse_option_bhav")
            log.info("bhav_seed.cleared_existing", rows=existing)

        conn.execute(
            "INSERT INTO nse_option_bhav "
            "(date, strike, option_type, expiry, open, high, low, close, settle_price, oi) "
            "SELECT date, strike, option_type, expiry, open, high, low, close, "
            "COALESCE(settle_price, 0), COALESCE(oi, 0) "
            "FROM seed.nse_option_bhav"
        )
        conn.commit()

        count = conn.execute("SELECT COUNT(*) FROM nse_option_bhav").fetchone()[0]
        conn.execute("DETACH seed")
        conn.close()

        elapsed = round(time.time() - t0, 1)
        log.info("bhav_seed.complete", rows=count, seconds=elapsed)
        invalidate_cache()
        return {"seeded": count, "seconds": elapsed}
    except Exception as exc:
        log.error("bhav_seed.failed", error=str(exc))
        return {"error": str(exc)}
    finally:
        os.unlink(seed_path)


class NseOptionBhavRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_option_prices(self) -> dict[tuple[str, int, str], dict]:
        """Return cached lookup dict, building it on first call."""
        global _price_cache
        with _cache_lock:
            if _price_cache is None:
                _price_cache = _build_cache(self._db)
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
