"""Repository for the model_registry table."""

from sqlalchemy.orm import Session

from rita.models.model_registry import ModelRegistryModel
from rita.repositories.base import SqlRepository
from rita.schemas.model_registry import ModelRegistry


class ModelRegistryRepository(SqlRepository[ModelRegistry, ModelRegistryModel]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, ModelRegistryModel, ModelRegistry, "model_id")
