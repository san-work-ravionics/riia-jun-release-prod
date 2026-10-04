"""Pydantic contracts for GET /api/v1/experience/fno/position-value (F40 Phase 3).

Consumer: dashboard/js/fno/hedge-position-value.js (Exposure step candle card).
Position value = stored shares x close, in the instrument's own currency (no FX).
"""
from __future__ import annotations

from pydantic import BaseModel, Field

# Exact user-facing strings (tested; keep in sync with Spec_RITA_App.md).
MSG_CASH = "Cash has no price history"
MSG_NO_HOLDING = "No equity holding for {id} (option exposure only). Position value needs shares held."
MSG_NO_SHARES = "No share count stored for {id}. Position value needs shares held."
MSG_NO_CURRENCY = "Currency not configured for {id}"
MSG_NO_PRICE_DATA = "No price data available for {id}"
MSG_INSUFFICIENT = "Not enough price history for {id} (needs at least 2 months of data)"


class PositionValueCandle(BaseModel):
    month: str  # YYYY-MM
    open: float
    high: float
    low: float
    close: float


class PositionValueDaily(BaseModel):
    date: str  # YYYY-MM-DD
    value: float


class PositionValueBands(BaseModel):
    anchor_value: float
    anchor_date: str
    plus_1sigma_value: float
    minus_1sigma_value: float
    plus_1sigma_pct: float
    minus_1sigma_pct: float


class PositionValueItem(BaseModel):
    instrument_id: str
    status: str  # ok|cash|no_holding|no_shares|no_currency|no_price_data|insufficient_data
    message: str = ""
    currency: str | None = None
    currency_symbol: str = ""
    shares: int | None = None
    months: int = 12
    last_close: float | None = None
    last_value: float | None = None
    ann_vol_pct: float | None = None
    vol_source: str | None = None  # override | computed
    monthly_sigma_pct: float | None = None
    bands: PositionValueBands | None = None
    candles: list[PositionValueCandle] = Field(default_factory=list)
    daily: list[PositionValueDaily] = Field(default_factory=list)


class PositionValueResponse(BaseModel):
    as_of: str | None = None
    items: list[PositionValueItem] = Field(default_factory=list)
