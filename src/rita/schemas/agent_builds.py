"""Pydantic schemas for the Agent Build pipeline run API."""
from typing import Optional

from pydantic import BaseModel


class AgentOut(BaseModel):
    role: str
    status: str
    token_estimate: Optional[int] = None
    adherence_score: Optional[float] = None
    steps_required: Optional[int] = None
    steps_completed: Optional[int] = None
    grounding_checks: Optional[dict] = None
    failure_modes: Optional[list[str]] = None
    actual_tokens: Optional[dict] = None


class AgentBuildRunOut(BaseModel):
    run_id: str
    app: str
    request: Optional[str] = None
    overall_status: str
    duration_minutes: Optional[float] = None
    branch: Optional[str] = None
    agents: list[AgentOut]
    token_forecast: Optional[dict] = None
    total_tokens_estimated: Optional[int] = None
    hitl_events: Optional[list] = None
    human_score_csat: Optional[float] = None


class RoleMetrics(BaseModel):
    run_count: int
    avg_adherence_score: Optional[float] = None
    first_pass_rate: Optional[float] = None
    avg_token_cost: Optional[float] = None


class GroundingPoint(BaseModel):
    run_id: str
    app: str
    grounding_score: float
    checks_passed: int
    checks_total: int


class FailureEntry(BaseModel):
    total: int
    by_role: dict[str, int]


class SkillVersion(BaseModel):
    skill_file: str
    last_updated: Optional[str] = None
    recent_commits: list[dict]
    improvement_applied: Optional[str] = None
    before_first_pass_rate: Optional[float] = None
    after_first_pass_rate: Optional[float] = None


class AgentBuildMetrics(BaseModel):
    total_runs: int
    per_role: dict[str, RoleMetrics]
    grounding_trend: list[GroundingPoint]
    failure_modes: dict[str, FailureEntry]
    skill_version_history: list[SkillVersion]
    task_completion: Optional[dict] = None
    quality: Optional[dict] = None
    token_forecasting: Optional[dict] = None
    efficiency: Optional[dict] = None
    reliability: Optional[dict] = None
    hitl: Optional[dict] = None
    agentic: Optional[dict] = None


class AgentBuildsResponse(BaseModel):
    runs: list[AgentBuildRunOut]
    metrics: AgentBuildMetrics
