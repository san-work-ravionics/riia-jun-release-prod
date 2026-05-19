"""ORM model for the alerts table."""
from sqlalchemy import Boolean, Column, DateTime, Float, String

from rita.database import Base


class AlertModel(Base):
    __tablename__ = "alerts"

    alert_id = Column(String, primary_key=True)
    timestamp = Column(DateTime, nullable=False)
    query_text = Column(String, nullable=True)
    intent_name = Column(String, nullable=True)
    handler = Column(String, nullable=True)
    confidence = Column(Float, nullable=True)
    low_confidence = Column(Boolean, nullable=False, default=False)
    latency_ms = Column(Float, nullable=True)
    response_preview = Column(String, nullable=True)
    status = Column(String, nullable=False, default="success")
    recorded_at = Column(DateTime, nullable=False)
