"""Pydantic schemas for commentary endpoint."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class CommentaryRequest(BaseModel):
    app: str
    page: str
    instrument: str | None = None


class CommentaryResponse(BaseModel):
    app: str
    page: str
    commentary: str
    instruments_analyzed: list[str]
    latency_ms: float


class CommentaryLogCreate(BaseModel):
    id: str
    app: str
    page: str
    instrument: str | None
    latency_ms: float
    status: str
    commentary_preview: str
    timestamp: datetime
