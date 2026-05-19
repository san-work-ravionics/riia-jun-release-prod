"""Pydantic schemas for the risk_timeline table (daily risk metrics)."""
from datetime import date, datetime
from typing import Optional, Literal
from pydantic import BaseModel, ConfigDict


class RiskTimelineBase(BaseModel):
    date: date
    phase: Literal["Train", "Test", "Live"]
    allocation: float                       # 0.0–1.0
    portfolio_value_norm: float             # normalised (1.0 = start)
    portfolio_value_inr: float
    rolling_vol_20d: Optional[float] = None
    market_var_95: Optional[float] = None
    portfolio_var_95: Optional[float] = None
    portfolio_cvar_95: Optional[float] = None
    current_drawdown_pct: float = 0.0
    drawdown_budget_pct: float = 0.0
    position_risk_pct: Optional[float] = None
    trend_score: Optional[float] = None
    regime: Optional[str] = None           # Sideways, Bull, Bear
    model_confidence: Optional[float] = None
    inr_at_risk: Optional[float] = None


class RiskTimelineCreate(RiskTimelineBase):
    pass


class RiskTimeline(RiskTimelineBase):
    model_config = ConfigDict(from_attributes=True)

    risk_id: str
    recorded_at: datetime
