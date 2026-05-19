"""Pydantic schemas for the alerts table."""
from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, ConfigDict, Field


class AlertBase(BaseModel):
    timestamp: datetime
    query_text: Optional[str] = Field(default=None, max_length=512)
    intent_name: Optional[str] = Field(default=None, max_length=64)
    handler: Optional[str] = Field(default=None, max_length=64)
    confidence: Optional[float] = None
    low_confidence: bool = False
    latency_ms: Optional[float] = Field(default=None, ge=0)
    response_preview: Optional[str] = Field(default=None, max_length=512)
    status: Literal["success", "error", "warning"] = "success"


class AlertCreate(AlertBase):
    pass


class Alert(AlertBase):
    model_config = ConfigDict(from_attributes=True)

    alert_id: str
    recorded_at: datetime
