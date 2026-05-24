"""Pydantic schemas for the functional-kpis Experience endpoint."""
from pydantic import BaseModel


class FunctionalKPIsSeries(BaseModel):
    training_success_rate_pct: list[float]
    chat_low_confidence_pct: list[float]
    experience_error_pct: list[float]
    error_rate_pct: list[float]
    p95_latency_ms: list[float]


class FunctionalKPIsResponse(BaseModel):
    generated_at: str
    buckets: list[str]
    series: FunctionalKPIsSeries
