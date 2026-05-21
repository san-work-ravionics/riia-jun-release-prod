"""Pydantic schemas for the data refresh endpoint (Feature 16)."""
from typing import List, Optional

from pydantic import BaseModel


class InstrumentRefreshResult(BaseModel):
    instrument: str
    gap_days: int
    raw_rows_added: int
    db_rows_inserted: int
    status: str          # "ok" | "current" | "error"
    error: Optional[str] = None


class RefreshAllResponse(BaseModel):
    refreshed: int
    already_current: int
    results: List[InstrumentRefreshResult]
