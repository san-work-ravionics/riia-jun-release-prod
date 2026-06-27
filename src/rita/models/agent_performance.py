"""ORM model for the agent_performance table (Feature 32).

Records one row per resolved investment-workflow agent intent from the chat
classifier, used to surface per-agent KPI tracking for the 7 trading-decision
agents. This is distinct from agent_builds (the /enhance dev pipeline).
"""
from sqlalchemy import Column, DateTime, Index, String
from sqlalchemy.sql import func

from rita.database import Base


class AgentPerformance(Base):
    __tablename__ = "agent_performance"

    perf_id         = Column(String, primary_key=True)
    agent_name      = Column(String, nullable=False)
    intent          = Column(String, nullable=False)
    recommendation  = Column(String, nullable=True)
    outcome_status  = Column(String, nullable=True)
    training_run_id = Column(String, nullable=True)
    created_at      = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_agent_performance_agent_created", "agent_name", "created_at"),
    )
