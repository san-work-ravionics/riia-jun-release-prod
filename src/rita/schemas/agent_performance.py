"""Pydantic schemas for agent performance (Feature 32).

Row schema mirrors the agent_performance ORM model; AgentKpi +
AgentPerformanceSummaryResponse are the Phase 2 read-only API contract.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class AgentPerformanceSchema(BaseModel):
    """Row schema — mirrors AgentPerformance ORM nullability."""

    perf_id:         str
    agent_name:      str
    intent:          str
    recommendation:  str | None = None
    outcome_status:  str | None = None
    training_run_id: str | None = None
    created_at:      datetime | None = None

    model_config = {"from_attributes": True}


class AgentKpi(BaseModel):
    """Per-agent KPI summary for the dashboard."""

    agent_name:           str
    gap_status:           str
    invocation_count_30d: int = Field(ge=0)
    outcome_match_rate:   float | None = None
    trend_vs_prior_30d:   float | None = None

    model_config = {"from_attributes": True}


class AgentPerformanceSummaryResponse(BaseModel):
    """Response for GET /api/v1/experience/rita/agent-performance — always 7 agents."""

    agents: list[AgentKpi]

    model_config = {"from_attributes": True}
