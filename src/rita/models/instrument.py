"""ORM model for the instruments table."""
from sqlalchemy import Boolean, Column, DateTime, Integer, String

from rita.database import Base


class InstrumentModel(Base):
    __tablename__ = "instruments"

    instrument_id = Column(String, primary_key=True)   # e.g. "NIFTY", "NVDA"
    name          = Column(String, nullable=False)      # e.g. "Nifty 50"
    exchange      = Column(String, nullable=False)      # e.g. "NSE", "NASDAQ"
    country_code  = Column(String, nullable=False)      # e.g. "IN", "US"
    currency      = Column(String(10), nullable=True)   # e.g. "INR", "USD", "EUR"
    lot_size      = Column(Integer, nullable=True)      # FnO only; null for equities
    is_available  = Column(Boolean, nullable=False, default=False)
    created_at    = Column(DateTime, nullable=False)
