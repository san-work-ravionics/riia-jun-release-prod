"""ORM model for user_hedge_plans table.

One row per user (keyed by portfolio key_id).  Stores the user's selected hedge
configuration so it can be restored across sessions.

Fields
------
key_id       PK + FK → user_portfolio_keys.key_id
hedged_ids   JSON list of instrument_id strings selected for hedging
coverage     Integer 0–100, the coverage slider value
scenario_tab The active scenario tab key (e.g. 'pp', 'ps')
duration     Always "1y" — stored for completeness; updated via PUT only
updated_at   Auto-updated timestamp
"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.sql import func

from rita.database import Base


class UserHedgePlanModel(Base):
    __tablename__ = "user_hedge_plans"

    key_id = Column(String, ForeignKey("user_portfolio_keys.key_id"), primary_key=True)
    hedged_ids = Column(JSON, nullable=False, default=list)
    coverage = Column(Integer, nullable=False, default=50)
    scenario_tab = Column(String, nullable=False, default="pp")
    duration = Column(String, nullable=False, default="1y")
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
