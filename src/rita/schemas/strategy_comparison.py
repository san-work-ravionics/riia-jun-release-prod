"""Pydantic schemas for the Strategy Comparison experience endpoint.

GET /api/v1/experience/rita/strategy-comparison
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class StrategyResult(BaseModel):
    """Equity curve and label for one trading strategy."""

    name: str = Field(..., description="Human-readable strategy name")
    equity: list[float] = Field(default_factory=list, description="Portfolio value over time")
    color: str = Field(..., description="CSS hex color for chart rendering")


class StrategySummaryRow(BaseModel):
    """Per-strategy aggregate performance metrics."""

    name: str
    total_return_pct: float = Field(0.0, description="Total return as a percentage")
    sharpe: float = Field(0.0, description="Annualised Sharpe ratio")
    max_drawdown_pct: float = Field(0.0, description="Maximum drawdown as a percentage (positive = loss)")
    n_trades: int = Field(0, description="Number of round-trip trades completed")
    win_rate_pct: float = Field(0.0, description="Percentage of trades that were profitable")
    final_value: float = Field(0.0, description="Portfolio value at end of period")


class StrategyComparisonResponse(BaseModel):
    """Full response for the Strategy Comparison card."""

    instrument: str
    year: int
    dates: list[str] = Field(default_factory=list, description="ISO date strings for x-axis")
    strategies: list[StrategyResult] = Field(default_factory=list, description="Always 5 entries")
    summary: list[StrategySummaryRow] = Field(default_factory=list, description="Tabular metrics per strategy")
    error: str | None = Field(None, description="Non-null when data is unavailable")
