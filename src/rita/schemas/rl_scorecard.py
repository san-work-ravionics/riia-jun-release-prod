"""Pydantic schemas for the RL diagnostic scorecard (Feature 32, Phase 3.6).

Read-only Experience-tier response contract for
GET /api/v1/experience/rita/agent-performance/scorecards.
Mirrors the dict shape produced by ``rita.core.rl_scorecard.compute_scorecard()``
+ ``rita.core.rl_diagnostics.generate_insights()``.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ScorecardInsight(BaseModel):
    """One rule-based diagnostic insight for a single scorecard parameter."""

    parameter: str
    label: str
    severity: str  # fail | warn | info | pass
    message: str

    model_config = {"from_attributes": True}


class InstrumentScorecard(BaseModel):
    """The 10-parameter RL diagnostic scorecard for one instrument + run."""

    instrument:     str
    run_id:         str
    config_source:  str  # "default" | "instrument"
    regime_window:  int
    generated_at:   str
    functional:     dict[str, Any]  # F1-F5
    technical:      dict[str, Any]  # T1-T5
    insights:       list[ScorecardInsight] = []
    overall_status: str = "unknown"  # fail | warn | pass — worst insight severity

    model_config = {"from_attributes": True}


class RLScorecardResponse(BaseModel):
    """Response for GET /api/v1/experience/rita/agent-performance/scorecards."""

    scorecards: list[InstrumentScorecard]

    model_config = {"from_attributes": True}
