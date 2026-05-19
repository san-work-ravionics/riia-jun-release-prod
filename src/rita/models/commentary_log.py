"""ORM model for commentary_logs table."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Float, String

from rita.database import Base


class CommentaryLogModel(Base):
    __tablename__ = "commentary_logs"

    id = Column(String, primary_key=True)
    app = Column(String, nullable=False)
    page = Column(String, nullable=False)
    instrument = Column(String, nullable=True)
    latency_ms = Column(Float, nullable=False)
    status = Column(String, nullable=False)
    commentary_preview = Column(String, nullable=False)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)
