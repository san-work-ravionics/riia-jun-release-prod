"""Pydantic contracts for FX rates (F44 P2) — the ``/experience/rita/fx`` route and the
``market.fx_rate`` MCP tool share them."""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Currency = Literal["EUR", "INR", "USD"]


class FxRateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base: Currency = Field("EUR", description="Base currency: EUR | INR | USD")
    quote: Currency = Field(..., description="Quote currency: EUR | INR | USD")
    as_of: date | None = Field(None, description="Latest rate on or before this date (default: latest)")


class FxRateOut(BaseModel):
    base: str
    quote: str
    rate: float            # units of quote per 1 base
    as_of: date | None     # date of the cached rate (None only when base == quote)
    source: str
