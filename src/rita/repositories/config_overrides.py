"""Repository for the config_overrides table (runtime config and session state)."""

from sqlalchemy.orm import Session

from rita.models.config_overrides import ConfigOverrideModel
from rita.repositories.base import SqlRepository
from rita.schemas.config_overrides import ConfigOverride


class ConfigOverridesRepository(SqlRepository[ConfigOverride, ConfigOverrideModel]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, ConfigOverrideModel, ConfigOverride, "override_id")
