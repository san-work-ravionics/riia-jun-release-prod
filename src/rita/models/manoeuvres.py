"""ORM model for the manoeuvres table (manoeuvre group actions)."""
from sqlalchemy import Column, Date, DateTime, Float, String

from rita.database import Base


class ManoeuvreModel(Base):
    __tablename__ = "manoeuvres"

    manoeuvre_id = Column(String, primary_key=True)
    timestamp = Column(DateTime, nullable=False)
    date = Column(Date, nullable=False)
    month = Column(String, nullable=False)
    action = Column(String, nullable=False)
    lot_key = Column(String, nullable=False)
    from_group = Column(String, nullable=True)
    to_group = Column(String, nullable=True)
    nifty_spot = Column(Float, nullable=True)
    banknifty_spot = Column(Float, nullable=True)
    recorded_at = Column(DateTime, nullable=False)
