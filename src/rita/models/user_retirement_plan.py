"""ORM model for user_retirement_plans (F43 Phase 1, D10; Phase 2 composite PK).

One row per (user, location): the "What I Need" plan inputs, restored when the page opens.

Fields
------
user_id         PK (part 1) + FK → users.id
location        PK (part 2) — preset key (e.g. "europe", "india", "us")
inputs          JSON — RetirementPlanInputs dump (camelCase, rates as fractions)
schema_version  Integer, 1 for Phase 1; bumped when Phases 3–5 change the inputs shape
created_at      Insert timestamp (server default)
updated_at      Auto-updated timestamp
"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.sql import func

from rita.database import Base


class UserRetirementPlanModel(Base):
    __tablename__ = "user_retirement_plans"

    user_id = Column(String, ForeignKey("users.id"), primary_key=True)
    location = Column(String, nullable=False, default="europe", server_default="europe", primary_key=True)
    inputs = Column(JSON, nullable=False)
    schema_version = Column(Integer, nullable=False, default=1, server_default="1")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
