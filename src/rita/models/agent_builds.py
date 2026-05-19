"""ORM models for agent_build_runs and agent_build_agents tables."""
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text

from rita.database import Base


class AgentBuildRunModel(Base):
    __tablename__ = "agent_build_runs"

    run_id = Column(String, primary_key=True)
    app = Column(String, nullable=False)
    request = Column(Text, nullable=True)
    skill_file = Column(String, nullable=True)
    overall_status = Column(String, nullable=False)
    total_tokens_estimated = Column(Integer, nullable=True)
    duration_minutes = Column(Float, nullable=True)
    branch = Column(String, nullable=True)
    merge_status = Column(String, nullable=True)
    merge_commit = Column(String, nullable=True)
    recorded_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class AgentBuildAgentModel(Base):
    __tablename__ = "agent_build_agents"

    agent_id = Column(String, primary_key=True)
    run_id = Column(String, ForeignKey("agent_build_runs.run_id"), nullable=False)
    role = Column(String, nullable=False)
    status = Column(String, nullable=False)
    steps_required = Column(Integer, nullable=True)
    steps_completed = Column(Integer, nullable=True)
    adherence_score = Column(Float, nullable=True)
    token_estimate = Column(Integer, nullable=True)
    actual_tokens_total = Column(Integer, nullable=True)
    grounding_checks = Column(JSON, nullable=True)
    failure_modes = Column(JSON, nullable=True)
    recorded_at = Column(DateTime, nullable=False, default=datetime.utcnow)
