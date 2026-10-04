"""Pydantic schemas for the hedge-plan endpoints (F29 Phase 1, extended in F40 Phase 2).

HedgePlanCreate         — PUT request body
HedgePlanOut            — GET / PUT response body
HedgeContext*           — optional client-supplied per-instrument cost/strike context
HedgePlanHistoryOut     — one archived save (history GET)
HedgePlanHistoryAdminOut— HedgePlanHistoryOut + user_id/key_id (system export)
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, List

from pydantic import BaseModel, field_validator


_STEPS = ("exposure", "recommendation", "whatif", "save")
_STRATEGIES = ("put_buy", "call_sell")
_TRIGGERS = ("explicit", "autosave")
_SOURCES = ("workflow", "overview")
_COST_SOURCES = ("kite", "kite_csv", "estimated")
MAX_CONTEXT_INSTRUMENTS = 50


class HedgeContextInstrument(BaseModel):
    """Client-supplied per-instrument strike/cost context (advisory, never trusted for market fields)."""

    model_config = {"extra": "ignore"}

    instrument_id: str
    strike_pct: float | None = None
    strike_label: str | None = None
    premium_pct: float | None = None  # monthly
    cost_source: str | None = None
    hedge_type: str | None = None
    risk_score: float | None = None
    protected_pct: float | None = None

    @field_validator("cost_source")
    @classmethod
    def cost_source_known(cls, v: str | None) -> str | None:
        return v if v in _COST_SOURCES else None


class HedgeContext(BaseModel):
    model_config = {"extra": "ignore"}

    instruments: List[HedgeContextInstrument] = []
    margin: dict[str, Any] | None = None


class HedgePlanCreate(BaseModel):
    """Request body for PUT /api/v1/experience/fno/hedge-plan."""

    hedged_ids: List[str]
    coverage: int
    scenario_tab: str
    duration: str | None = None  # accepted but always overwritten with "1y"
    last_step: str | None = None  # null/unknown = preserve; first insert "exposure"
    selections: dict[str, Any] | None = None  # {instrument_id: "put_buy"|"call_sell"}; null = preserve
    trigger: str = "autosave"  # "explicit" | "autosave"
    source: str = "workflow"  # "workflow" | "overview"
    context: dict[str, Any] | None = None  # parsed leniently by HedgePlanService (never 422)

    @field_validator("last_step")
    @classmethod
    def last_step_known(cls, v: str | None) -> str | None:
        """Unknown step names are treated as omitted (preserve) — autosave must not 422."""
        if v is None:
            return None
        return v if v in _STEPS else None

    @field_validator("trigger", mode="before")
    @classmethod
    def trigger_known(cls, v: Any) -> str:
        return v if v in _TRIGGERS else "autosave"

    @field_validator("source", mode="before")
    @classmethod
    def source_known(cls, v: Any) -> str:
        return v if v in _SOURCES else "workflow"

    @field_validator("selections", mode="before")
    @classmethod
    def selections_clean(cls, v: Any) -> dict[str, str] | None:
        """Drop entries whose value is not a known strategy; never reject."""
        if not isinstance(v, dict):
            return None
        return {str(k): s for k, s in v.items() if s in _STRATEGIES}

    @field_validator("coverage")
    @classmethod
    def coverage_range(cls, v: int) -> int:
        if not 0 <= v <= 100:
            raise ValueError("coverage must be between 0 and 100")
        return v


class HedgePlanOut(BaseModel):
    """Response body for GET and PUT /api/v1/experience/fno/hedge-plan."""

    key_id: str
    hedged_ids: List[str]
    coverage: int
    scenario_tab: str
    duration: str
    last_step: str | None = None
    selections: dict[str, str] | None = None
    updated_at: datetime

    model_config = {"from_attributes": True}


class HistoryInstrument(BaseModel):
    """One instrument inside a history row: server market block + client context block."""

    model_config = {"extra": "ignore"}

    # server block
    instrument_id: str
    hedged: bool = False
    strategy: str | None = None
    shares: int | None = None
    allocation_pct: float = 0.0
    currency: str | None = None
    spot: float | None = None
    spot_date: str | None = None
    position_value: float | None = None
    ann_vol_pct: float | None = None
    # client block
    strike_pct: float | None = None
    strike_label: str | None = None
    premium_pct: float | None = None
    cost_source: str | None = None
    hedge_type: str | None = None
    risk_score: float | None = None
    protected_pct: float | None = None


class HistoryPortfolio(BaseModel):
    total_value_eur: float | None = None
    cash_eur: float | None = None
    n_holdings: int = 0


class HedgePlanHistoryOut(BaseModel):
    history_id: str
    saved_at: datetime
    trigger: str
    source: str
    last_step: str | None = None
    scenario_tab: str
    coverage: int
    duration: str
    hedged_ids: List[str]
    selections: dict[str, str] | None = None
    instruments: List[HistoryInstrument]
    portfolio: HistoryPortfolio
    margin: dict[str, Any] | None = None
    schema_version: int
    app_version: str

    model_config = {"from_attributes": True}


class HedgePlanHistoryAdminOut(HedgePlanHistoryOut):
    user_id: str
    key_id: str


class HedgePlanHistoryList(BaseModel):
    items: List[HedgePlanHistoryOut]
    count: int
    limit: int


class HedgePlanHistoryAdminList(BaseModel):
    items: List[HedgePlanHistoryAdminOut]
    count: int
    limit: int
    offset: int
    since: str | None = None
    until: str | None = None
