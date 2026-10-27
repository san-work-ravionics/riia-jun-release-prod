"""Pydantic contracts for the F44 MCP tools (inputs + outputs not covered by existing schemas).

Tools whose output equals an existing route response reuse that schema
(``OptimalAllocationResponse``, ``PositionValueResponse``, ``HedgePlanOut``).
Rules (ADR-007 §3): money carries ``currency``; rates are fractions; market-data results carry
``as_of``.  **No input model has a ``user_id`` field** — the user comes from the call identity.
Input models forbid unknown fields, so a ``user_id`` argument is rejected as ``invalid_input``.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _LegacyIn(BaseModel):
    # Legacy aliases accepted any extra argument before F44 — keep that.
    model_config = ConfigDict(extra="ignore")


# ── whatineed.* ─────────────────────────────────────────────────────────────────

class WhatINeedPlanIn(_In):
    location: str | None = Field(
        None, description="Plan location: europe | india | us. Default = the preset default location.",
    )


class WhatINeedPlanResult(BaseModel):
    retire_age: int
    need_at_retire: float | None = None
    monthly_at_retire: float | None = None
    portfolio_at_retire: float
    sustainable_until: int | None = None
    portfolio_out_age: int | None = None


class WhatINeedPlanOut(BaseModel):
    saved: bool
    location: str
    currency: str
    updated_at: datetime | None = None
    result: WhatINeedPlanResult


# ── portfolio.* ─────────────────────────────────────────────────────────────────

class NoArgsIn(_In):
    pass


class PortfolioHoldingsIn(_In):
    location: Literal["europe", "india", "us"] | None = Field(
        None, description="Portfolio location: europe | india | us. Omit = the most recently saved portfolio.",
    )


class PortfolioHoldingOut(BaseModel):
    instrument_id: str
    allocation_pct: float
    shares: int | None = None
    cash: float | None = None


class PortfolioHoldingsOut(BaseModel):
    portfolio_id: str
    name: str
    currency: str
    location: str | None = None
    total_value: float | None = None
    holdings: list[PortfolioHoldingOut]
    updated_at: datetime


class OptimalAllocationIn(_In):
    horizon: Literal["short_term", "medium_term", "long_term"] = Field(
        ..., description="Investment horizon for instrument filtering and metric lookback",
    )


# ── fno.* ───────────────────────────────────────────────────────────────────────

class PositionValueIn(_In):
    instrument: str | None = Field(None, pattern=r"^[A-Za-z0-9_-]{1,32}$", description="Instrument id (case-insensitive); omit for all holdings")
    months: int = Field(12, ge=1, le=36)
    ann_vol_pct: float | None = Field(None, gt=0, description="Annualised vol % override for the ±1σ bands")


# ── market.* ────────────────────────────────────────────────────────────────────

# Plain ticker id — never a path (the loader also checks it against the known instrument set).
_INSTRUMENT_PATTERN = r"^[A-Za-z0-9_-]{1,32}$"


class InstrumentIn(_In):
    instrument: str = Field("NIFTY", pattern=_INSTRUMENT_PATTERN,
                            description="Instrument id, e.g. NIFTY, BANKNIFTY, ASML, NVIDIA")


class SignalOut(BaseModel):
    value: str
    score: int


class MarketOverviewOut(BaseModel):
    instrument: str
    as_of: str
    sentiment: str
    total_score: int
    trend: str
    rsi_14: float
    atr_14: float
    atr_percentile: float
    bb_position: str
    ema_50: float
    ema_200: float
    close: float
    signals: dict[str, SignalOut]


class MarketAskIn(_In):
    query: str = Field(..., min_length=1, description="Natural-language investment question")
    instrument: str = Field("NIFTY", pattern=_INSTRUMENT_PATTERN,
                            description="Instrument id, e.g. NIFTY, BANKNIFTY, ASML, NVIDIA")
    portfolio_value: float | None = Field(
        None, gt=0, description="Portfolio size for stress / allocation answers (default 1,000,000)",
    )
    currency: str | None = Field(None, description="Currency of portfolio_value (label only in P1)")
    target_return: float | None = Field(None, description="Target annual return as a fraction, e.g. 0.12")
    horizon_days: int | None = Field(None, gt=0, description="Investment horizon in days")


class MarketAskOut(BaseModel):
    instrument: str
    intent: str
    confidence: float
    low_confidence: bool
    answer: str


class MarketMonitorOut(BaseModel):
    summary: dict[str, Any]
    intents: list[dict[str, Any]]
    recent: list[dict[str, Any]]


# ── legacy aliases (text only) ──────────────────────────────────────────────────

class AskRitaIn(_LegacyIn):
    query: str
    instrument: Literal["NIFTY", "BANKNIFTY", "ASML", "NVIDIA"] = "NIFTY"
    portfolio_inr: float = 1_000_000
    target_return_pct: float | None = None
    time_horizon_days: int | None = None


class LegacyInstrumentIn(_LegacyIn):
    instrument: Literal["NIFTY", "BANKNIFTY", "ASML", "NVIDIA"] = "NIFTY"


class LegacyNoArgsIn(_LegacyIn):
    pass


class McpToolError(BaseModel):
    """Structured part of an error result: ``{"error": {"code", "message"}}``."""

    code: Literal["not_found", "forbidden", "invalid_input", "unavailable"]
    message: str


# ── F44 P3 goal-driven selection (outputs in schemas/goal_selection.py) ────────

_Location = Literal["europe", "india", "us"]


class GoalIn(_In):
    location: _Location | None = Field(
        None, description="Plan location: europe | india | us. Default = the preset default location.",
    )


class SelectForGoalIn(_In):
    location: _Location = Field(..., description="Location whose instruments are selected from")
    target_return: float = Field(..., ge=-0.5, le=2.0,
                                 description="Annual target return as a fraction, e.g. 0.07675")
    as_of: date | None = Field(
        None, description="Data date the answer must be for (must equal the cached data date)",
    )


class RequiredReturnIn(_In):
    location: _Location
    goal_return: float = Field(..., ge=-0.5, le=2.0, description="Annual goal return r (fraction)")
    ytd_return: float = Field(..., gt=-1.0, le=100.0,
                              description="Portfolio return since year_start (fraction)")
    as_of: date = Field(..., description="Close the ytd return is measured at")
    year_start: date = Field(..., description="Jan 1, or the first track date in this year")
    reselections_used: int = Field(0, ge=0, le=100,
                                   description="Re-selections already spent in this target year")


class ModelRunsIn(_In):
    location: _Location


# ── F44 P4 Jarvis tools (outputs in schemas/jarvis.py) ──────────────────────────

class PnlSegmentHoldingIn(_In):
    instrument_id: str = Field(..., pattern=_INSTRUMENT_PATTERN)
    allocation_pct: int = Field(..., ge=0, le=100)
    tolerance: Literal["low", "medium", "high"]


class PnlSegmentIn(_In):
    model_config = ConfigDict(extra="forbid", validate_by_name=True, validate_by_alias=True,
                              serialize_by_alias=True)

    from_: date = Field(..., alias="from")
    to: date | None = None
    holdings: list[PnlSegmentHoldingIn] = Field(..., min_length=1, max_length=50)
    cause: Literal["track", "accept", "preview"] = "track"


class PnlIn(_In):
    location: _Location
    goal_return: float | None = Field(None, ge=-0.5, le=2.0,
                                      description="The user's annual goal r (fraction) for the target path")
    source: Literal["auto", "saved", "model_sleeves"] = "auto"
    year_start: date | None = Field(None, description="The journey's plan_year_start s")
    segments: list[PnlSegmentIn] | None = Field(
        None, max_length=20, description="Held model-sleeve mixes (journey segments) for the sleeve path")
    preview: bool = Field(False, description="Selection not tracked yet: sleeves bought on Jan 1 (never for the guard)")


class SleeveTraceIn(_In):
    location: _Location
    instrument: str = Field(..., pattern=_INSTRUMENT_PATTERN)
    tolerance: Literal["low", "medium", "high"] | None = Field(
        None, description="Journey tolerance; omit = the P3 τ* rule on this one sleeve")
    entry_date: date | None = Field(None, description="Tracking entry (SL peak starts at max(entry, episode start))")
    since: date | None = Field(None, description="Return measured from this date's close")
    detail: bool = False


class SigmaLevelsIn(_In):
    instrument: str = Field(..., pattern=_INSTRUMENT_PATTERN)
    months: int = Field(12, ge=1, le=36)


class AstaTraceIn(_In):
    instrument: str = Field(..., pattern=_INSTRUMENT_PATTERN)
    since: date | None = None
    detail: bool = False
