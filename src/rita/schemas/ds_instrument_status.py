"""Pydantic schemas for DS instrument model build status endpoint."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class InstrumentBuildStatusItem(BaseModel):
    symbol: str
    name: Optional[str] = None
    last_trained: Optional[str] = None
    build_status: str
    model_version: Optional[str] = None
    error_message: Optional[str] = None
    model_file_exists: bool


class DsInstrumentBuildStatusResponse(BaseModel):
    instruments: list[InstrumentBuildStatusItem]
    total: int
    as_of: str
