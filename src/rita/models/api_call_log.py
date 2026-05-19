import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String

from rita.database import Base


class ApiCallLogModel(Base):
    __tablename__ = "api_call_log"

    call_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    path = Column(String, nullable=False)
    method = Column(String, nullable=False)
    status_code = Column(Integer, nullable=True)
    duration_ms = Column(Float, nullable=True)
    called_at = Column(DateTime, nullable=False)
    recorded_at = Column(DateTime, nullable=False, default=datetime.utcnow)
