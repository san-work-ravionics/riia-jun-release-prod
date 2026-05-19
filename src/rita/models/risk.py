"""ORM model for the risk_timeline table (daily risk metrics)."""
from sqlalchemy import Column, Date, DateTime, Float, String

from rita.database import Base


class RiskTimelineModel(Base):
    __tablename__ = "risk_timeline"

    risk_id = Column(String, primary_key=True)
    date = Column(Date, nullable=False)
    phase = Column(String, nullable=False)
    allocation = Column(Float, nullable=False)
    portfolio_value_norm = Column(Float, nullable=False)
    portfolio_value_inr = Column(Float, nullable=False)
    rolling_vol_20d = Column(Float, nullable=True)
    market_var_95 = Column(Float, nullable=True)
    portfolio_var_95 = Column(Float, nullable=True)
    portfolio_cvar_95 = Column(Float, nullable=True)
    current_drawdown_pct = Column(Float, nullable=False, default=0.0)
    drawdown_budget_pct = Column(Float, nullable=False, default=0.0)
    position_risk_pct = Column(Float, nullable=True)
    trend_score = Column(Float, nullable=True)
    regime = Column(String, nullable=True)
    model_confidence = Column(Float, nullable=True)
    inr_at_risk = Column(Float, nullable=True)
    recorded_at = Column(DateTime, nullable=False)
