"""ORM model for user_portfolios table."""
import sqlalchemy as sa
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, String
from sqlalchemy.sql import func

from rita.database import Base


class UserPortfolioModel(Base):
    __tablename__ = "user_portfolios"

    portfolio_id = Column(String, primary_key=True)
    key_id = Column(String, ForeignKey("user_portfolio_keys.key_id"), nullable=False)
    name = Column(String, nullable=True)
    holdings = Column(sa.JSON, nullable=False)
    total_value_eur = Column(Float, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now())
    is_active = Column(Boolean, default=True)
