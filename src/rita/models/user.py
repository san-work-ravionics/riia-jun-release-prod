from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, String

from rita.database import Base


class UserModel(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, index=True)
    last_login_date = Column(DateTime, default=datetime.utcnow)
    
    # RBAC Access Flags
    can_assist_research = Column(Boolean, default=False)
    can_create_portfolio = Column(Boolean, default=True)
    can_review_portfolio = Column(Boolean, default=False)
    can_access_ops = Column(Boolean, default=False)
