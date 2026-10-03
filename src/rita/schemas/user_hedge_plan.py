"""Pydantic schemas for the hedge-plan Experience-tier endpoints (F29 Phase 1).

HedgePlanCreate — PUT request body
HedgePlanOut    — GET / PUT response body
"""
from __future__ import annotations

from datetime import datetime
from typing import List

from pydantic import BaseModel, field_validator


_STEPS = ("exposure", "recommendation", "whatif", "save")


class HedgePlanCreate(BaseModel):
    """Request body for PUT /api/v1/experience/fno/hedge-plan."""

    hedged_ids: List[str]
    coverage: int
    scenario_tab: str
    duration: str | None = None  # accepted but always overwritten with "1y"
    last_step: str | None = None  # "exposure" | "recommendation" | "whatif" | "save"

    @field_validator("last_step")
    @classmethod
    def last_step_known(cls, v: str | None) -> str | None:
        """Unknown step names fall back to "exposure" (never rejected — autosave must not 422)."""
        if v is None:
            return None
        return v if v in _STEPS else "exposure"

    @field_validator("coverage")
    @classmethod
    def coverage_range(cls, v: int) -> int:
        if not 0 <= v <= 100:
            raise ValueError("coverage must be between 0 and 100")
        return v


class HedgePlanOut(BaseModel):
    """Response body for GET and PUT /api/v1/experience/fno/hedge-plan."""

    key_id: str
    hedged_ids: List[str]
    coverage: int
    scenario_tab: str
    duration: str
    last_step: str | None = None
    updated_at: datetime

    model_config = {"from_attributes": True}
