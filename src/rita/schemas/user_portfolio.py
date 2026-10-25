"""Pydantic schemas for User Portfolio Store.

F44 P2 (multi-currency): a portfolio has a ``location`` (europe | india | us, null = legacy
cross-geography) and a ``currency`` derived from it server-side.  ``total_value`` and
``holdings[].cash`` are in that currency.  ``total_value_eur`` / ``cash_eur`` are the legacy
EUR fields (accepted on input, returned for one release).
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

Location = Literal["europe", "india", "us"]


class HoldingItem(BaseModel):
    instrument_id: str
    allocation_pct: float
    shares: int | None = None       # whole-number share count
    cash: float | None = None       # leftover cash after buying whole shares, portfolio currency
    cash_eur: float | None = None   # legacy (pre-P2) leftover cash in EUR — readers accept it

    @field_validator("allocation_pct")
    @classmethod
    def allocation_must_be_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("allocation_pct must be greater than 0")
        return v


class UserPortfolioCreate(BaseModel):
    name: str | None = None
    holdings: list[HoldingItem]
    location: Location | None = None   # currency is derived from it server-side
    total_value: float | None = None   # in the location currency (EUR when location is null)
    total_value_eur: float | None = None  # legacy clients


class UserPortfolioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    portfolio_id: str
    key_id: str
    name: str
    holdings: list[HoldingItem]
    currency: str = "EUR"
    location: str | None = None
    total_value: float | None = None
    total_value_eur: float | None = None
    created_at: datetime
    updated_at: datetime
    is_active: bool

    @field_validator("currency", mode="before")
    @classmethod
    def _currency_default(cls, v):
        return v or "EUR"

    @model_validator(mode="after")
    def _legacy_fallbacks(self) -> "UserPortfolioOut":
        # Legacy EUR rows: total_value = total_value_eur, holdings cash = cash_eur.
        if self.total_value is None and self.currency == "EUR":
            self.total_value = self.total_value_eur
        if self.currency == "EUR":
            for h in self.holdings:
                if h.cash is None and h.cash_eur is not None:
                    h.cash = h.cash_eur
        return self
