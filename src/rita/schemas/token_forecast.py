"""Pydantic schema for the token-forecast endpoint response."""

from pydantic import BaseModel


class TokenForecastResponse(BaseModel):
    complexity: str
    complexity_score: float
    feature_type: str
    per_role: dict[str, int]
    total_forecast: int
    confidence: str
    basis_runs: int
