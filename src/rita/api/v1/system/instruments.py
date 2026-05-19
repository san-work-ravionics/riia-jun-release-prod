"""System CRUD router for the instruments table.

ADR-001 Tier 1: pure CRUD, single repository, zero business logic.
URLs preserved from observability.py (Option A migration).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from rita.database import get_db
from rita.repositories.instrument import InstrumentRepository
from rita.schemas.instrument import Instrument

router = APIRouter(prefix="/api/v1", tags=["system:instruments"])


class _InstrumentBody(BaseModel):
    instrument_id: str
    name: str
    exchange: str
    country_code: str
    currency: Optional[str] = None
    lot_size: Optional[int] = None
    is_available: bool = False


@router.get("/instruments", summary="List all instruments")
def list_instruments(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    repo = InstrumentRepository(db)
    return [
        {
            "id": i.instrument_id,
            "name": i.name,
            "exchange": i.exchange,
            "country_code": i.country_code,
            "currency": i.currency,
            "lot_size": i.lot_size,
            "data_ready": i.is_available,
        }
        for i in repo.read_all()
    ]


@router.post("/instruments", summary="Add a new instrument", status_code=201)
def add_instrument(body: _InstrumentBody, db: Session = Depends(get_db)) -> dict[str, Any]:
    repo = InstrumentRepository(db)
    record = Instrument(
        instrument_id=body.instrument_id.upper(),
        name=body.name,
        exchange=body.exchange,
        country_code=body.country_code,
        lot_size=body.lot_size,
        is_available=body.is_available,
        created_at=datetime.now(timezone.utc),
    )
    repo.upsert(record)
    return {"status": "created", "instrument_id": record.instrument_id}


@router.patch("/instruments/{instrument_id}/availability", summary="Toggle instrument availability")
def set_availability(
    instrument_id: str,
    is_available: bool,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    repo = InstrumentRepository(db)
    instrument = repo.find_by_id(instrument_id.upper())
    if instrument is None:
        raise HTTPException(status_code=404, detail=f"Instrument '{instrument_id}' not found")
    repo.upsert(instrument.model_copy(update={"is_available": is_available}))
    return {"instrument_id": instrument_id.upper(), "is_available": is_available}
