"""ORM model for the audit_log table (API and agent action log)."""
from sqlalchemy import Column, DateTime, Float, Integer, String

from rita.database import Base


class AuditLogModel(Base):
    __tablename__ = "audit_log"

    log_id = Column(String, primary_key=True)
    timestamp = Column(DateTime, nullable=False)
    source = Column(String, nullable=False)
    method = Column(String, nullable=True)
    path = Column(String, nullable=True)
    status_code = Column(Integer, nullable=True)
    duration_ms = Column(Float, nullable=True)
    args_summary = Column(String, nullable=True)
    result_summary = Column(String, nullable=True)
    recorded_at = Column(DateTime, nullable=False)
