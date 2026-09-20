"""ORM model for the nse_option_bhav table (NSE F&O Bhav copy data)."""
from sqlalchemy import Column, Date, Float, Index, Integer, String

from rita.database import Base


class NseOptionBhavModel(Base):
    __tablename__ = "nse_option_bhav"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False)
    strike = Column(Integer, nullable=False)
    option_type = Column(String(2), nullable=False)
    expiry = Column(Date, nullable=False)
    open = Column(Float, nullable=False, default=0.0)
    high = Column(Float, nullable=False, default=0.0)
    low = Column(Float, nullable=False, default=0.0)
    close = Column(Float, nullable=False, default=0.0)
    settle_price = Column(Float, nullable=False, default=0.0)
    oi = Column(Integer, nullable=False, default=0)

    __table_args__ = (
        Index("ix_bhav_lookup", "date", "strike", "option_type"),
        Index("ix_bhav_date", "date"),
    )
