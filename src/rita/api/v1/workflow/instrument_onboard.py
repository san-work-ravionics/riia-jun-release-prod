"""Workflow router for instrument onboarding.

ADR-001 Tier 2: stateful orchestration — fetch data from yfinance,
normalize, persist to DB, and seed market cache.

Endpoints:
  GET  /api/v1/instrument/search   — search Yahoo Finance for equity listings
  POST /api/v1/instrument/onboard  — onboard a new instrument end-to-end

No JWT required (same pattern as workflow/pipeline.py).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from rita.database import get_db
from rita.repositories.instrument import InstrumentRepository
from rita.schemas.instrument import Instrument
from rita.services.instrument_onboard import (
    fetch_raw_data,
    process_to_input,
    search_tickers,
    seed_market_cache,
)

log = structlog.get_logger()

router = APIRouter(prefix="/api/v1", tags=["workflow:instrument_onboard"])


# ── Request / response schemas ─────────────────────────────────────────────────

class _OnboardBody(BaseModel):
    ticker: str
    name: str
    exchange: str
    currency: str
    country_code: str
    lot_size: Optional[int] = None


# ── GET /api/v1/instrument/search ─────────────────────────────────────────────

@router.get("/instrument/search", summary="Search Yahoo Finance for equity listings")
def instrument_search(q: str, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """Return up to 10 equity matches from Yahoo Finance for the query string *q*.

    Requires q to be at least 2 characters. Returns ticker, name, exchange,
    currency, country, and quote_type for each result.
    """
    if len(q.strip()) < 2:
        raise HTTPException(
            status_code=400,
            detail="Query parameter 'q' must be at least 2 characters.",
        )
    # HTTPException(502) propagates from service if yfinance is unreachable
    return search_tickers(q)


# ── POST /api/v1/instrument/onboard ───────────────────────────────────────────

@router.post("/instrument/onboard", summary="Onboard a new instrument from Yahoo Finance")
def instrument_onboard(
    body: _OnboardBody,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Full onboarding pipeline for a new instrument.

    Pipeline (in order):
      1. Duplicate check → 409 if ticker already in instruments table
      2. fetch_raw_data()       → download OHLCV from yfinance; 400 if < 100 rows
      3. process_to_input()     → normalize and write input CSV
      4. InstrumentRepository.upsert → register in DB with is_available=True
      5. seed_market_cache()    → bulk insert 2025+ rows into market_data_cache

    Returns status, ticker, rows_fetched, rows_seeded, raw_path, input_path.
    Errors: 409 duplicate; 400 bad ticker or < 100 rows; 502 yfinance failure.
    """
    ticker = body.ticker.upper()
    repo = InstrumentRepository(db)

    # 1. Duplicate check
    existing = repo.find_by_id(ticker)
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Instrument '{ticker}' already exists in the database.",
        )

    # 2. Fetch raw data (raises HTTPException 502 on network failure, ValueError on < 100 rows)
    try:
        raw_path, rows_fetched = fetch_raw_data(ticker)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # 3. Normalize to input format
    input_path = process_to_input(ticker, raw_path)

    # 4. Upsert instrument record
    record = Instrument(
        instrument_id=ticker,
        name=body.name,
        exchange=body.exchange,
        country_code=body.country_code,
        currency=body.currency,
        lot_size=body.lot_size,
        is_available=True,
        created_at=datetime.now(timezone.utc),
    )
    repo.upsert(record)
    log.info("instrument_onboard.registered", ticker=ticker, exchange=body.exchange)

    # 5. Seed market cache (2025+ rows)
    rows_seeded = seed_market_cache(db, ticker, body.currency)

    return {
        "status": "ok",
        "ticker": ticker,
        "rows_fetched": rows_fetched,
        "rows_seeded": rows_seeded,
        "raw_path": str(raw_path),
        "input_path": str(input_path),
    }
