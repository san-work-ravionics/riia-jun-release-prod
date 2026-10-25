"""ORM model for the mcp_calls table — one row per MCP tool call (F44 P1: + transport/caller/user_id)."""
from sqlalchemy import Column, DateTime, Float, String

from rita.database import Base


class MCPCallModel(Base):
    __tablename__ = "mcp_calls"

    call_id      = Column(String,  primary_key=True)
    timestamp    = Column(DateTime, nullable=False)
    tool_name    = Column(String,  nullable=False)
    status       = Column(String,  nullable=False, default="ok")
    duration_ms  = Column(Float,   nullable=True)
    args_summary = Column(String,  nullable=True)
    result_summary = Column(String, nullable=True)
    recorded_at  = Column(DateTime, nullable=False)
    # F44 P1 (ADR-007 §7) — all nullable; rows written before P1 have NULL
    transport    = Column(String,  nullable=True)               # memory | http | stdio | sse
    caller       = Column(String,  nullable=True)               # jarvis | module:<name> | external | system
    user_id      = Column(String,  nullable=True, index=True)   # no FK (stdio / anonymous calls)
