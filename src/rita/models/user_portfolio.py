"""ORM model for user_portfolios table.

F44 P2: a portfolio belongs to one location (``europe`` / ``india`` / ``us``, NULL = legacy
cross-geography portfolio) and is held in that location's ``currency``.  ``total_value`` and
``holdings[].cash`` are in that currency.  ``total_value_eur`` is deprecated (kept and written
for one release).  One active portfolio per (key_id, location) (D1).
"""
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
    total_value_eur = Column(Float, nullable=True)  # deprecated (F44 P2) — kept one release
    currency = Column(String, nullable=False, default="EUR", server_default="EUR")
    location = Column(String, nullable=True)        # europe | india | us; NULL = legacy
    total_value = Column(Float, nullable=True)      # in ``currency``
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now())
    is_active = Column(Boolean, default=True)
