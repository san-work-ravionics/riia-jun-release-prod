"""ORM model for the portfolio table (daily performance summary)."""
from sqlalchemy import Column, Date, DateTime, Float, Integer, String

from rita.database import Base


class PortfolioModel(Base):
    __tablename__ = "portfolio"

    portfolio_id = Column(String, primary_key=True)
    date = Column(Date, nullable=False)
    underlying = Column(String, nullable=True)
    month = Column(String, nullable=True)
    group_id = Column(String, nullable=True)
    group_name = Column(String, nullable=True)
    view = Column(String, nullable=True)
    pnl_now = Column(Float, nullable=False)
    sl_pnl = Column(Float, nullable=True)
    target_pnl = Column(Float, nullable=True)
    lot_count = Column(Integer, nullable=False, default=0)
    nifty_spot = Column(Float, nullable=True)
    banknifty_spot = Column(Float, nullable=True)
    dte = Column(Integer, nullable=True)
    pct_from_sl = Column(Float, nullable=True)
    pct_from_target = Column(Float, nullable=True)
    recorded_at = Column(DateTime, nullable=False)
