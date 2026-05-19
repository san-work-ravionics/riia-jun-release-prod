"""Pydantic schemas for the audit_log table (API and agent action log)."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class AuditLogBase(BaseModel):
    timestamp: datetime
    source: str = Field(max_length=64)      # api / agent / mcp
    method: Optional[str] = Field(default=None, max_length=16)   # GET, POST, etc.
    path: Optional[str] = Field(default=None, max_length=512)    # API path or tool name
    status_code: Optional[int] = None
    duration_ms: Optional[float] = Field(default=None, ge=0)
    args_summary: Optional[str] = Field(default=None, max_length=512)
    result_summary: Optional[str] = Field(default=None, max_length=512)


class AuditLogCreate(AuditLogBase):
    pass


class AuditLog(AuditLogBase):
    model_config = ConfigDict(from_attributes=True)

    log_id: str
    recorded_at: datetime
