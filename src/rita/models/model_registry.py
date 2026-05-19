"""ORM model for the model_registry table."""
from sqlalchemy import Boolean, Column, Date, DateTime, Float, String

from rita.database import Base


class ModelRegistryModel(Base):
    __tablename__ = "model_registry"

    model_id = Column(String, primary_key=True)
    date = Column(Date, nullable=False)
    version = Column(String, nullable=False)
    category = Column(String, nullable=False)
    change = Column(String, nullable=False)
    notes = Column(String, nullable=True)
    backtest_sharpe = Column(Float, nullable=True)
    backtest_mdd = Column(Float, nullable=True)
    backtest_return = Column(Float, nullable=True)
    model_path = Column(String, nullable=True)
    is_active = Column(Boolean, nullable=False, default=False)
    recorded_at = Column(DateTime, nullable=False)
