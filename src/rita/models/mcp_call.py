"""ORM model for the mcp_calls table."""
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
