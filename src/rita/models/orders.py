"""ORM model for the orders table (broker order log)."""
from sqlalchemy import Column, DateTime, Float, Integer, String

from rita.database import Base


class OrderModel(Base):
    __tablename__ = "orders"

    order_id = Column(String, primary_key=True)
    instrument = Column(String, nullable=False)
    underlying = Column(String, nullable=False)
    product = Column(String, nullable=False, default="NRML")
    order_type = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    quantity_filled = Column(Integer, nullable=False)
    avg_price = Column(Float, nullable=False)
    status = Column(String, nullable=False)
    placed_at = Column(DateTime, nullable=False)
    recorded_at = Column(DateTime, nullable=False)
