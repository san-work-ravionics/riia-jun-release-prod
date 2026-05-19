"""ORM model for the config_overrides table (runtime config and session state)."""
from sqlalchemy import Column, DateTime, String

from rita.database import Base


class ConfigOverrideModel(Base):
    __tablename__ = "config_overrides"

    override_id = Column(String, primary_key=True)
    key = Column(String, nullable=False)
    value = Column(String, nullable=False)
    stage = Column(String, nullable=True, default="active")
    description = Column(String, nullable=True)
    saved_at = Column(DateTime, nullable=False)
    recorded_at = Column(DateTime, nullable=False)
