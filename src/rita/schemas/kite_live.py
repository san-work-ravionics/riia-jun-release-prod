"""Pydantic schemas for the kite-live Experience-tier endpoint (F39 Phase 2 addendum).

GET /api/v1/experience/fno/kite-live — best-effort live Kite overlay (quote/lot-size/
margin), sourced from `fno-margin-fetch` (local-dev-only Zerodha/Kite middleware), with
a silent fallback when Kite data is unavailable or the middleware is unreachable.

`quote`, `margin` and `lot_size` are each independently nullable so partial data is
representable (e.g. lot size resolves via Kite but the quote call times out).
`quote` is populated by the Exposure-step call (Phase 2); `margin` is populated by the
What-if-step call (Phase 3) — both fields exist now so Phase 3 needs no schema change.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel


class KiteLiveQuote(BaseModel):
    ltp: Optional[float] = None
    bid: Optional[float] = None
    ask: Optional[float] = None


class KiteLiveMargin(BaseModel):
    required: Optional[float] = None
    span: Optional[float] = None
    exposure: Optional[float] = None


class KiteLiveResponse(BaseModel):
    instrument_id: str
    available: bool
    source: Literal["kite", "fallback"]
    lot_size: Optional[int] = None
    quote: Optional[KiteLiveQuote] = None
    margin: Optional[KiteLiveMargin] = None
    fetched_at: Optional[datetime] = None
