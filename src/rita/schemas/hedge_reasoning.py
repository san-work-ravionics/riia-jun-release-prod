"""Pydantic schemas for the Hedge Reasoning endpoint (Feature 31 Phase 1).

Defines the 6-step deterministic reasoning chain response shape.
Each step carries agent name, title, narrative text, structured data, and verdict.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ReasoningStep(BaseModel):
    """A single step in the hedge reasoning chain."""

    agent: str = Field(..., description="Agent name (e.g. REGIME_ANALYST)")
    title: str = Field(..., description="Human-readable step title")
    narrative: str = Field(..., description="Typewriter-rendered explanation text")
    data: dict[str, Any] = Field(default_factory=dict, description="Structured step payload")
    verdict: str = Field(..., description="Short verdict badge text")


class PayoffCurves(BaseModel):
    """33-point payoff comparison grid."""

    price_range: list[float]
    unhedged: list[float]
    call_sell: list[float]
    put_buy: list[float]


class HedgeReasoningResponse(BaseModel):
    """Full 6-step hedge reasoning chain response."""

    instrument: str
    timestamp: datetime
    steps: list[ReasoningStep]
    recommendation: str = Field(
        ..., description="Primary recommendation: call_sell | put_buy | no_hedge"
    )
    confidence: str = Field(..., description="high | moderate | low")
    payoff_curves: PayoffCurves
    spot_price: float
    data_source: str = Field(default="black_scholes")
