"""Pydantic schemas for the portfolio-analytics endpoint (F30 Phase 1)."""
from __future__ import annotations

from pydantic import BaseModel


class PortfolioMetaSchema(BaseModel):
    name: str
    total_value_eur: float
    updated_at: str


class MarketEntrySchema(BaseModel):
    close: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    prevClose: float | None = None
    chgFromOpen: float | None = None
    chgFromPrev: float | None = None
    date: str
    shares: str
    turnover: float | None = None
    currency: str | None = None


class PositionItemSchema(BaseModel):
    und: str
    full: str
    exp: str
    type: str
    side: str
    qty: int
    allocation_pct: float
    position_eur: float
    avg: float
    ltp: float
    chg: float
    pnl: float
    currency: str | None = None
    ann_vol_pct: float
    region: str | None = None


class GreekItemSchema(BaseModel):
    und: str
    exp: str
    hedge_type: str
    delta: float
    gamma: float
    theta: float
    vega: float
    allocation_pct: float
    ann_vol_pct: float
    sigma_eur: float
    net_theta_eur_day: float
    put_cost_eur: float | None = None
    call_income_eur: float | None = None


class NetGreeksSchema(BaseModel):
    delta: float
    theta: float
    vega: float


class ScenarioLevelSchema(BaseModel):
    target: float
    sl: float


class PayoffCurveSchema(BaseModel):
    labels: list[float]
    data: list[float]


class PayoffSchema(BaseModel):
    portfolio: PayoffCurveSchema
    hedged: PayoffCurveSchema


class StressEventSchema(BaseModel):
    label: str
    move_pct: int
    portfolio_pnl_eur: int
    hedged_pnl_eur: int


class HedgeQualityPositionSchema(BaseModel):
    instrument: str
    hqs: int
    hqs_tier: str
    hedged: bool
    strategy: str | None = None
    coverage_pct: int | None = None
    note: str | None = None


class HedgeQualitySchema(BaseModel):
    positions: list[HedgeQualityPositionSchema]


class PortfolioAnalyticsResponse(BaseModel):
    mode: str
    portfolio_meta: PortfolioMetaSchema
    market: dict[str, MarketEntrySchema]
    positions: list[PositionItemSchema]
    greeks: list[GreekItemSchema]
    net_greeks: NetGreeksSchema
    net_delta: dict[str, float]
    scenario_levels: dict[str, ScenarioLevelSchema]
    payoff: PayoffSchema
    stress: list[StressEventSchema]
    hedge_quality: HedgeQualitySchema
    closed_positions: list
    realized_pnl: float
    margin: dict
