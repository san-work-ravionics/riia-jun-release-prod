"""Pydantic schemas for the Technical Analysis Experience endpoint."""
from __future__ import annotations

from typing import List

from pydantic import BaseModel


class SignalSummaryItem(BaseModel):
    label: str
    value: str
    state: str  # "bullish" | "bearish" | "neutral" | "normal" | "up" | "down"


class TechnicalCommentaryResponse(BaseModel):
    instrument: str
    commentary: str
    signal_summary: List[SignalSummaryItem]
