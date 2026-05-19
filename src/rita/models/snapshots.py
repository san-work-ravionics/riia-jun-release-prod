"""ORM model for the snapshots table (manoeuvre position snapshot)."""
from sqlalchemy import Column, Date, DateTime, Float, Integer, String

from rita.database import Base


class SnapshotModel(Base):
    __tablename__ = "snapshots"

    snapshot_id = Column(String, primary_key=True)
    date = Column(Date, nullable=False)
    underlying = Column(String, nullable=False)
    month = Column(String, nullable=False)
    group_id = Column(String, nullable=False)
    group_name = Column(String, nullable=False)
    view = Column(String, nullable=False)
    lot_key = Column(String, nullable=False)
    instrument = Column(String, nullable=False)
    option_type = Column(String, nullable=False)
    side = Column(String, nullable=False)
    lot_size = Column(Integer, nullable=False)
    avg_price = Column(Float, nullable=False)
    pnl_now = Column(Float, nullable=False)
    pnl_sl = Column(Float, nullable=False)
    pnl_target = Column(Float, nullable=False)
    recorded_at = Column(DateTime, nullable=False)
