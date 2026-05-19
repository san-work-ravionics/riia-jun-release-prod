"""ORM model for the trades table (closed/executed positions)."""
from sqlalchemy import Column, Date, DateTime, Float, String

from rita.database import Base


class TradeModel(Base):
    __tablename__ = "trades"

    trade_id = Column(String, primary_key=True)
    instrument = Column(String, nullable=False)
    underlying = Column(String, nullable=False)
    expiry = Column(String, nullable=False)
    option_type = Column(String, nullable=False)
    strike = Column(Float, nullable=False)
    side = Column(String, nullable=False)
    pnl = Column(Float, nullable=False)
    notes = Column(String, nullable=True)
    closed_date = Column(Date, nullable=True)
    recorded_at = Column(DateTime, nullable=False)
