"""ORM model for the positions table (live open positions from broker)."""
from sqlalchemy import Column, DateTime, Float, Integer, String

from rita.database import Base


class PositionModel(Base):
    __tablename__ = "positions"

    position_id = Column(String, primary_key=True)
    instrument = Column(String, nullable=False)
    underlying = Column(String, nullable=False)
    product = Column(String, nullable=False, default="NRML")
    option_type = Column(String, nullable=True)
    strike = Column(Float, nullable=True)
    expiry = Column(String, nullable=True)
    quantity = Column(Integer, nullable=False)
    avg_price = Column(Float, nullable=False)
    last_traded_price = Column(Float, nullable=False)
    pnl = Column(Float, nullable=False)
    pct_change = Column(Float, nullable=True)
    recorded_at = Column(DateTime, nullable=False)
