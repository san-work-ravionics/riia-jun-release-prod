from typing import Optional

from pydantic import BaseModel


class ApiMetricsRow(BaseModel):
    path: str
    method: str
    call_count: int
    p50_ms: Optional[float] = None
    p95_ms: Optional[float] = None
    error_count: int
    error_rate_pct: float
    last_called_at: Optional[str] = None


class ApiMetricsResponse(BaseModel):
    items: list[ApiMetricsRow]
