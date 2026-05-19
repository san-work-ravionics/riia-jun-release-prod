"""ORM model for the paper_positions table (simulated / paper trading positions)."""
from sqlalchemy import Column, Date, DateTime, Float, Integer, String

from rita.database import Base


class PaperPositionModel(Base):
    __tablename__ = "paper_positions"

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
    currency = Column(String, nullable=False, default="INR")
    lot_size = Column(Integer, nullable=False, default=1)
    sl_price = Column(Float, nullable=True)
    target_price = Column(Float, nullable=True)
    entry_date = Column(Date, nullable=True)      # date position was opened
    expiry_date = Column(Date, nullable=True)     # actual calendar expiry date (for DTE)
    recorded_at = Column(DateTime, nullable=False)
