"""ORM model for user_retirement_plan_history (F43 Phase 1b).

Append-only archive: one row per saved "What I Need" plan (each PUT of the plan).
Rows are never updated or deleted by the application.  The full result is not
stored — it is recalculated from ``inputs`` on request; the key figures shown to
the user at save time are kept as columns so later screens can list and compare
them without recalculating.

Fields
------
history_id         PK, uuid4 string
user_id            FK → users.id — the signed-in user (real Google users in production;
                   SQLite does not enforce the FK, so the synthetic dev user ``rita-dev`` works)
saved_at           Server timestamp of the save (UTC)
inputs             JSON — RetirementPlanInputs dump (camelCase, rates as fractions)
location           Preset key (e.g. "europe")
retire_age         Retirement age in the plan
plan_until         Plan-until age
need_at_retire     Monthly need at retirement (EUR)
monthly_at_retire  Monthly available at retirement (EUR)
corpus_at_retire   Invested corpus value at retirement (EUR)
sustainable_until  First age the money pot falls short (null = beyond plan-until)
corpus_out_age     Age the invested corpus is used up (null = never, up to 120)
schema_version     Inputs schema version (1)
app_version        Application version at save time
"""
from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, JSON, String

from rita.database import Base


class UserRetirementPlanHistoryModel(Base):
    __tablename__ = "user_retirement_plan_history"

    history_id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    saved_at = Column(DateTime(timezone=True), nullable=False)
    inputs = Column(JSON, nullable=False)
    location = Column(String, nullable=False, default="europe")
    retire_age = Column(Integer, nullable=False)
    plan_until = Column(Integer, nullable=False)
    need_at_retire = Column(Float, nullable=False)
    monthly_at_retire = Column(Float, nullable=False)
    corpus_at_retire = Column(Float, nullable=False)
    sustainable_until = Column(Integer, nullable=True)
    corpus_out_age = Column(Integer, nullable=True)
    schema_version = Column(Integer, nullable=False, default=1)
    app_version = Column(String, nullable=False, default="")

    __table_args__ = (
        Index("ix_user_retirement_plan_history_user_saved", "user_id", "saved_at"),
    )
