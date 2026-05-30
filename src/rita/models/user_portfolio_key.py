"""ORM model for user_portfolio_keys table."""
from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.sql import func

from rita.database import Base


class UserPortfolioKeyModel(Base):
    __tablename__ = "user_portfolio_keys"

    key_id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=func.now())
