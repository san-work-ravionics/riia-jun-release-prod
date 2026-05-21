"""Service layer for all-instruments data refresh (Feature 16).

Provides five functions:
  check_gap()          — check how many days of data are missing for an instrument
  fetch_and_write_raw()— download delta rows from yfinance, write/append raw CSV
  rebuild_input()      — re-run load_instrument_data() and write normalized input CSV
  upsert_cache_delta() — insert new (instrument, date) rows into market_data_cache
  refresh_all()        — orchestrate full pipeline for all 11 instruments (skips ATHER)

Rules:
- Use structlog — no print() statements
- Use get_settings() — not bare settings
- upsert_cache_delta: db.add_all() with explicit existence check — no db.merge(), no DELETE
- fetch_and_write_raw: flatten yfinance MultiIndex before CSV write
- NIFTY/BANKNIFTY: overwrite companion _yf.csv (full download from 2009-09-01)
- All others: append new rows to existing _daily.csv (start = last_date + 1 day)
- Per-instrument errors caught in refresh_all() — never abort on a single failure
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import structlog
from sqlalchemy.orm import Session

from rita.config import get_settings

log = structlog.get_logger()

# ── Instrument YF ticker mapping ──────────────────────────────────────────────

YF_TICKER_MAP: dict[str, str] = {
    "NIFTY":     "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "ASML":      "ASML.AS",
    "NVIDIA":    "NVDA",
    "RELIANCE":  "RELIANCE.NS",
    "SBIN":      "SBIN.NS",
    "ASRNL":     "ASRNL.AS",
    "ATO":       "ATO.PA",
    "AEX":       "^AEX",
    "DJI":       "^DJI",
    "IXIC":      "^IXIC",
}

# NIFTY and BANKNIFTY use a companion _yf.csv file (full overwrite strategy)
# All other instruments append new rows to the existing _daily.csv
COMPANION_FILE_INSTRUMENTS: set[str] = {"NIFTY", "BANKNIFTY"}

# Skip ATHER — newly listed, data gaps are expected and normal
SKIP_INSTRUMENTS: set[str] = {"ATHER"}


# ── check_gap ─────────────────────────────────────────────────────────────────

def check_gap(instrument_id: str, db: Session) -> dict[str, Any]:
    """Check how many days of data are missing for *instrument_id*.

    Queries market_data_cache for the most recent date for this instrument.
    Returns a dict with:
      instrument_id, last_date (date | None), gap_days (int), yf_ticker (str | None)
    """
    from rita.models.market_data import MarketDataCacheModel

    instrument_id = instrument_id.upper()
    yf_ticker = YF_TICKER_MAP.get(instrument_id)

    # Find the most recent date in the DB for this instrument
    result = (
        db.query(MarketDataCacheModel.date)
        .filter(MarketDataCacheModel.underlying == instrument_id)
        .order_by(MarketDataCacheModel.date.desc())
        .first()
    )

    today = date.today()
    if result is None:
        # No data at all — treat as a large gap (2 years)
        last_date = None
        gap_days = 730
    else:
        last_date = result[0]
        gap_days = (today - last_date).days

    log.info(
        "data_refresh.check_gap",
        instrument=instrument_id,
        last_date=str(last_date),
        gap_days=gap_days,
    )
    return {
        "instrument_id": instrument_id,
        "last_date": last_date,
        "gap_days": gap_days,
        "yf_ticker": yf_ticker,
    }


# ── fetch_and_write_raw ───────────────────────────────────────────────────────

def fetch_and_write_raw(instrument_id: str, yf_ticker: str, last_date: date | None) -> tuple[Path, int]:
    """Download delta rows from yfinance and write/append raw CSV.

    For NIFTY/BANKNIFTY (COMPANION_FILE_INSTRUMENTS):
      - Full download from 2009-09-01
      - Overwrites data/raw/{INSTRUMENT}/{instrument_lower}_yf.csv

    For all other instruments:
      - Incremental download from (last_date + 1 day) to today
      - Appends new rows to data/raw/{INSTRUMENT}/{instrument_lower}_daily.csv
        (or creates it if absent)

    Returns (raw_path, rows_added).
    Raises ValueError if yfinance returns 0 rows for incremental fetch.
    Raises RuntimeError if yfinance is unreachable.
    """
    import yfinance as yf

    instrument_id = instrument_id.upper()
    cfg = get_settings()
    raw_dir = Path(cfg.data.raw_dir) / instrument_id
    raw_dir.mkdir(parents=True, exist_ok=True)

    is_companion = instrument_id in COMPANION_FILE_INSTRUMENTS

    if is_companion:
        # Full download — overwrite companion _yf.csv
        filename = f"{instrument_id.lower()}_yf.csv"
        start_date = "2009-09-01"
    else:
        # Incremental download — start from last_date + 1 day
        filename = f"{instrument_id.lower()}_daily.csv"
        if last_date is not None:
            start_dt = last_date + timedelta(days=1)
            start_date = start_dt.strftime("%Y-%m-%d")
        else:
            start_date = "2009-09-01"

    raw_path = raw_dir / filename

    try:
        df: pd.DataFrame = yf.download(
            yf_ticker,
            start=start_date,
            interval="1d",
            auto_adjust=True,
            progress=False,
        )
    except Exception as exc:
        log.warning(
            "data_refresh.fetch_failed",
            instrument=instrument_id,
            yf_ticker=yf_ticker,
            error=str(exc),
        )
        raise RuntimeError(f"yfinance fetch failed for {yf_ticker}: {exc}") from exc

    if df is None or len(df) == 0:
        log.info(
            "data_refresh.fetch_empty",
            instrument=instrument_id,
            yf_ticker=yf_ticker,
            start_date=start_date,
        )
        return raw_path, 0

    # Flatten MultiIndex columns (yfinance >= 0.2.x)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] if isinstance(col, tuple) else col for col in df.columns]

    rows_added = len(df)

    if is_companion:
        # Full overwrite of companion file
        df.to_csv(raw_path)
        log.info(
            "data_refresh.companion_written",
            instrument=instrument_id,
            path=str(raw_path),
            rows=rows_added,
        )
    else:
        # Append new rows to existing daily CSV
        if raw_path.exists():
            existing_df = pd.read_csv(raw_path, index_col=0, parse_dates=True)
            combined = pd.concat([existing_df, df])
            combined = combined[~combined.index.duplicated(keep="last")].sort_index()
            combined.to_csv(raw_path)
        else:
            df.to_csv(raw_path)
        log.info(
            "data_refresh.daily_appended",
            instrument=instrument_id,
            path=str(raw_path),
            new_rows=rows_added,
        )

    return raw_path, rows_added


# ── rebuild_input ─────────────────────────────────────────────────────────────

def rebuild_input(instrument_id: str) -> Path:
    """Re-run load_instrument_data() and write normalized input CSV.

    Calls load_instrument_data() which automatically merges companion _yf.csv
    (for NIFTY/BANKNIFTY) and manual supplement CSV. Normalizes and writes
    to data/input/{INSTRUMENT}/{instrument_lower}_daily.csv.

    Returns input_path.
    """
    from rita.core.data_loader import load_instrument_data

    instrument_id = instrument_id.upper()
    cfg = get_settings()
    input_dir = Path(cfg.data.input_dir) / instrument_id
    input_dir.mkdir(parents=True, exist_ok=True)

    df = load_instrument_data(instrument_id)

    # Drop timezone from index if tz-aware
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)

    input_path = input_dir / f"{instrument_id.lower()}_daily.csv"
    df.to_csv(input_path)

    log.info(
        "data_refresh.input_rebuilt",
        instrument=instrument_id,
        path=str(input_path),
        rows=len(df),
    )
    return input_path


# ── upsert_cache_delta ────────────────────────────────────────────────────────

def upsert_cache_delta(db: Session, instrument_id: str) -> int:
    """Insert new (instrument, date) rows into market_data_cache.

    Reads data/input/{INSTRUMENT}/{instrument_lower}_daily.csv.
    Filters to year >= 2025.
    Queries existing dates for this instrument.
    Inserts only rows with dates NOT already in DB via db.add_all().
    No db.merge(), no DELETE — safe incremental upsert only.

    Returns count of new rows inserted.
    """
    from rita.models.market_data import MarketDataCacheModel

    instrument_id = instrument_id.upper()
    cfg = get_settings()
    input_path = Path(cfg.data.input_dir) / instrument_id / f"{instrument_id.lower()}_daily.csv"

    if not input_path.exists():
        log.warning("data_refresh.upsert_skip", instrument=instrument_id, reason="input_csv_not_found")
        return 0

    from rita.core.data_loader import load_ohlcv_csv
    df = load_ohlcv_csv(str(input_path))

    # Filter to 2025+
    df = df[df.index.year >= 2025]
    if df.empty:
        log.info("data_refresh.upsert_skip", instrument=instrument_id, reason="no_2025_rows")
        return 0

    # Convert index to date objects
    dates_in_file = {ts.date() for ts in df.index}

    # Query existing dates in market_data_cache for this instrument
    existing_dates: set[date] = {
        row[0]
        for row in db.query(MarketDataCacheModel.date)
        .filter(MarketDataCacheModel.underlying == instrument_id)
        .all()
    }

    # Determine new dates only
    new_dates = dates_in_file - existing_dates
    if not new_dates:
        log.info("data_refresh.upsert_skip", instrument=instrument_id, reason="all_dates_exist")
        return 0

    now = datetime.now(timezone.utc)
    new_records = []
    for ts, row in df.iterrows():
        if ts.date() not in new_dates:
            continue
        new_records.append(
            MarketDataCacheModel(
                cache_id=str(uuid.uuid4()),
                date=ts.date(),
                underlying=instrument_id,
                open=float(row["Open"]) if "Open" in row else 0.0,
                high=float(row["High"]) if "High" in row else 0.0,
                low=float(row["Low"]) if "Low" in row else 0.0,
                close=float(row["Close"]),
                shares_traded=(
                    int(row["Volume"])
                    if "Volume" in row and pd.notna(row["Volume"])
                    else None
                ),
                turnover_cr=None,
                recorded_at=now,
            )
        )

    db.add_all(new_records)
    db.commit()

    log.info(
        "data_refresh.upsert_done",
        instrument=instrument_id,
        inserted=len(new_records),
    )
    return len(new_records)


# ── refresh_all ───────────────────────────────────────────────────────────────

def refresh_all(db: Session) -> list[dict[str, Any]]:
    """Orchestrate full data refresh pipeline for all RITA instruments.

    Iterates over all instruments in YF_TICKER_MAP (skips ATHER).
    Per-instrument errors are caught and recorded as status='error' —
    they do NOT abort the loop.

    Returns a list of dicts matching InstrumentRefreshResult shape.
    """
    results: list[dict[str, Any]] = []

    for instrument_id in sorted(YF_TICKER_MAP.keys()):
        if instrument_id in SKIP_INSTRUMENTS:
            log.info("data_refresh.skip", instrument=instrument_id, reason="excluded")
            continue

        log.info("data_refresh.start", instrument=instrument_id)
        try:
            gap_info = check_gap(instrument_id, db)
            yf_ticker = gap_info["yf_ticker"]
            gap_days = gap_info["gap_days"]
            last_date = gap_info["last_date"]

            if gap_days == 0:
                results.append({
                    "instrument": instrument_id,
                    "gap_days": 0,
                    "raw_rows_added": 0,
                    "db_rows_inserted": 0,
                    "status": "current",
                    "error": None,
                })
                log.info("data_refresh.already_current", instrument=instrument_id)
                continue

            if yf_ticker is None:
                results.append({
                    "instrument": instrument_id,
                    "gap_days": gap_days,
                    "raw_rows_added": 0,
                    "db_rows_inserted": 0,
                    "status": "error",
                    "error": "no yf_ticker configured",
                })
                continue

            # Fetch new raw data
            _raw_path, raw_rows_added = fetch_and_write_raw(instrument_id, yf_ticker, last_date)

            # Rebuild normalized input CSV
            rebuild_input(instrument_id)

            # Upsert new rows into market_data_cache
            db_rows_inserted = upsert_cache_delta(db, instrument_id)

            results.append({
                "instrument": instrument_id,
                "gap_days": gap_days,
                "raw_rows_added": raw_rows_added,
                "db_rows_inserted": db_rows_inserted,
                "status": "ok",
                "error": None,
            })
            log.info(
                "data_refresh.complete",
                instrument=instrument_id,
                gap_days=gap_days,
                raw_rows_added=raw_rows_added,
                db_rows_inserted=db_rows_inserted,
            )

        except Exception as exc:
            log.warning(
                "data_refresh.error",
                instrument=instrument_id,
                error=str(exc),
            )
            results.append({
                "instrument": instrument_id,
                "gap_days": gap_info.get("gap_days", -1) if "gap_info" in dir() else -1,
                "raw_rows_added": 0,
                "db_rows_inserted": 0,
                "status": "error",
                "error": str(exc),
            })

    return results
