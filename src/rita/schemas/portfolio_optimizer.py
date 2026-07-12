"""Pydantic schemas for the Guided Basket Optimal Allocation feature (F34 Phase 1).

Response models for GET /api/v1/experience/rita/optimal-allocation.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class AllocationItem(BaseModel):
    """Single instrument allocation in the optimized portfolio."""

    instrument_name: str
    ticker: str
    allocation_pct: int = Field(ge=0, le=100)
    sharpe: float
    mdd_pct: float
    metric_source: str  # "model" | "proxy"


class OptimalAllocationResponse(BaseModel):
    """Top-level response for the optimal allocation endpoint."""

    horizon: str
    instrument_count: int
    solver_status: str  # "OPTIMAL" | "FEASIBLE" | "INFEASIBLE" | "SINGLE_INSTRUMENT" | "NO_INSTRUMENTS" | "ERROR"
    estimated_sharpe: float
    estimated_mdd_pct: float
    allocations: list[AllocationItem]
