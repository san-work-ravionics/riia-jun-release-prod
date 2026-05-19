"""Pydantic schemas for the config_overrides table (runtime config and session state)."""
from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, ConfigDict, Field


class ConfigOverrideBase(BaseModel):
    key: str = Field(max_length=64)         # e.g. simulation_period, target_return_pct
    value: str = Field(max_length=512)      # stored as string/JSON
    stage: Optional[Literal["original", "revised", "active"]] = "active"
    description: Optional[str] = Field(default=None, max_length=512)


class ConfigOverrideCreate(ConfigOverrideBase):
    pass


class ConfigOverride(ConfigOverrideBase):
    model_config = ConfigDict(from_attributes=True)

    override_id: str
    saved_at: datetime
    recorded_at: datetime
