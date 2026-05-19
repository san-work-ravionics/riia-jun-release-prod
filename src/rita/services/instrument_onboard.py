"""Service layer for instrument onboarding — yfinance data fetch and normalization.

Provides four functions:
  search_tickers()     — search Yahoo Finance for equity listings
  fetch_raw_data()     — download OHLCV from yfinance and write raw CSV
  process_to_input()   — normalize raw CSV to standard OHLCV format
  seed_market_cache()  — bulk insert 2025+ rows into market_data_cache
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import structlog
from fastapi import HTTPException
from sqlalchemy.orm import Session

from rita.config import get_settings
from rita.core.data_loader import load_ohlcv_csv

log = structlog.get_logger()

_COUNTRY_NAME_TO_ISO2: dict[str, str] = {
    "united states": "US",
    "united states of america": "US",
    "usa": "US",
    "india": "IN",
    "netherlands": "NL",
    "germany": "DE",
    "france": "FR",
    "united kingdom": "GB",
    "belgium": "BE",
    "switzerland": "CH",
    "sweden": "SE",
    "spain": "ES",
    "italy": "IT",
    "austria": "AT",
    "finland": "FI",
    "denmark": "DK",
    "ireland": "IE",
    "poland": "PL",
    "portugal": "PT",
}


_EXCHANGE_TO_COUNTRY: dict[str, str] = {
    "NYQ": "US", "NYSE": "US", "NMS": "US", "NASDAQ": "US",
    "PCX": "US", "AMEX": "US", "BTS": "US", "NGM": "US",
    "NSE": "IN", "BSE": "IN",
    "AMS": "NL", "FRA": "DE", "PAR": "FR", "LSE": "GB",
}


def _normalize_country_code(raw: str, exchange: str = "") -> str:
    """Convert full country names from yfinance to ISO-2 codes.

    Falls back to exchange-based inference when yfinance returns no country.
    """
    if raw and raw.strip():
        if len(raw.strip()) == 2:
            return raw.strip().upper()
        return _COUNTRY_NAME_TO_ISO2.get(raw.strip().lower(), raw)
    return _EXCHANGE_TO_COUNTRY.get((exchange or "").strip().upper(), "")


def search_tickers(query: str, max_results: int = 10) -> list[dict[str, Any]]:
    """Search Yahoo Finance for equity listings matching *query*.

    Returns a list of dicts with keys: ticker, name, exchange, currency,
    country, quote_type. Filters to quoteType == "EQUITY" only.
    Raises HTTPException(502) if Yahoo Finance is unreachable.
    """
    try:
        import yfinance as yf
        results = yf.Search(query).quotes
    except (ConnectionError, TimeoutError, OSError) as exc:
        log.warning("instrument_onboard.search_unreachable", query=query, error=str(exc))
        raise HTTPException(
            status_code=502,
            detail="Yahoo Finance is currently unreachable.",
        ) from exc
    except Exception as exc:
        log.warning("instrument_onboard.search_error", query=query, error=str(exc))
        raise HTTPException(
            status_code=502,
            detail="Yahoo Finance is currently unreachable.",
        ) from exc

    equities = [r for r in results if r.get("quoteType", "").upper() == "EQUITY"]
    out: list[dict[str, Any]] = []
    for r in equities[:max_results]:
        out.append({
            "ticker":     r.get("symbol", ""),
            "name":       r.get("longname") or r.get("shortname", ""),
            "exchange":   r.get("exchange", ""),
            "currency":   r.get("currency", ""),
            "country":    _normalize_country_code(r.get("country", ""), r.get("exchange", "")),
            "quote_type": "EQUITY",
        })

    log.info("instrument_onboard.search_complete", query=query, results=len(out))
    return out


def fetch_raw_data(ticker: str) -> tuple[Path, int]:
    """Download OHLCV data from yfinance and write raw CSV.

    Creates data/raw/{TICKER}/ if absent.
    Saves to data/raw/{TICKER}/{ticker_lower}_daily.csv.
    Raises ValueError if fewer than 100 rows returned.
    Returns (raw_path, row_count).
    Raises HTTPException(502) if yfinance is unreachable.
    """
    try:
        import yfinance as yf
        df: pd.DataFrame = yf.download(
            ticker,
            start="2009-09-01",
            interval="1d",
            auto_adjust=True,
            progress=False,
        )
    except (ConnectionError, TimeoutError, OSError) as exc:
        log.warning("instrument_onboard.fetch_unreachable", ticker=ticker, error=str(exc))
        raise HTTPException(
            status_code=502,
            detail="Yahoo Finance is currently unreachable.",
        ) from exc
    except Exception as exc:
        log.warning("instrument_onboard.fetch_error", ticker=ticker, error=str(exc))
        raise HTTPException(
            status_code=502,
            detail="Yahoo Finance is currently unreachable.",
        ) from exc

    if df is None or len(df) < 100:
        raise ValueError(
            f"Ticker '{ticker}' returned fewer than 100 rows from Yahoo Finance "
            f"(got {len(df) if df is not None else 0}). "
            "Verify the ticker symbol is correct."
        )

    # Flatten multi-level columns if yfinance returns them
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]

    cfg = get_settings()
    raw_dir = Path(cfg.data.raw_dir) / ticker.upper()
    raw_dir.mkdir(parents=True, exist_ok=True)

    raw_path = raw_dir / f"{ticker.lower()}_daily.csv"
    df.to_csv(raw_path)

    log.info(
        "instrument_onboard.raw_saved",
        ticker=ticker,
        rows=len(df),
        path=str(raw_path),
    )
    return raw_path, len(df)


def process_to_input(ticker: str, raw_path: Path) -> Path:
    """Normalize raw CSV to standard OHLCV format and write input CSV.

    Normalizes columns to Open/High/Low/Close/Volume, drops tz from index,
    filters year >= 2010, sorts ascending.
    Creates data/input/{TICKER}/ if absent.
    Saves to data/input/{TICKER}/{ticker_lower}_daily.csv.
    Returns input_path.
    """
    df = load_ohlcv_csv(str(raw_path))

    # Drop timezone from DatetimeIndex if tz-aware
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)

    # Filter to year >= 2010
    df = df[df.index.year >= 2010]

    # Sort ascending
    df = df.sort_index()

    cfg = get_settings()
    input_dir = Path(cfg.data.input_dir) / ticker.upper()
    input_dir.mkdir(parents=True, exist_ok=True)

    input_path = input_dir / f"{ticker.lower()}_daily.csv"
    df.to_csv(input_path)

    log.info(
        "instrument_onboard.input_saved",
        ticker=ticker,
        rows=len(df),
        path=str(input_path),
    )
    return input_path


def seed_market_cache(db: Session, ticker: str, currency: str) -> int:
    """Seed market_data_cache with 2025+ rows for *ticker*.

    Reads data/input/{TICKER}/{ticker_lower}_daily.csv via load_ohlcv_csv().
    Filters to year >= 2025.
    Skips entirely if any record with underlying == ticker already exists.
    Bulk inserts via db.add_all() + db.commit().
    Returns count inserted (0 if skipped).
    """
    from rita.models.market_data import MarketDataCacheModel
    from rita.repositories.market_data import MarketDataCacheRepository

    # Check if already seeded
    existing = {r.underlying for r in MarketDataCacheRepository(db).read_all()}
    if ticker.upper() in existing:
        log.info("instrument_onboard.cache_skip", ticker=ticker, reason="already_seeded")
        return 0

    cfg = get_settings()
    input_path = Path(cfg.data.input_dir) / ticker.upper() / f"{ticker.lower()}_daily.csv"
    df = load_ohlcv_csv(str(input_path))

    # Filter to 2025+
    df = df[df.index.year >= 2025]
    if df.empty:
        log.info("instrument_onboard.cache_skip", ticker=ticker, reason="no_2025_rows")
        return 0

    now = datetime.now(timezone.utc)
    records = [
        MarketDataCacheModel(
            cache_id=str(uuid.uuid4()),
            date=ts.date(),
            underlying=ticker.upper(),
            open=float(row["Open"]) if "Open" in row else 0.0,
            high=float(row["High"]) if "High" in row else 0.0,
            low=float(row["Low"]) if "Low" in row else 0.0,
            close=float(row["Close"]),
            shares_traded=int(row["Volume"]) if "Volume" in row and pd.notna(row["Volume"]) else None,
            turnover_cr=None,
            recorded_at=now,
        )
        for ts, row in df.iterrows()
    ]

    db.add_all(records)
    db.commit()

    log.info("instrument_onboard.cache_seeded", ticker=ticker, rows=len(records))
    return len(records)
