"""Repository for the manoeuvres table (manoeuvre group actions)."""

from sqlalchemy.orm import Session

from rita.models.manoeuvres import ManoeuvreModel
from rita.repositories.base import SqlRepository
from rita.schemas.manoeuvres import Manoeuvre


class ManoeuvresRepository(SqlRepository[Manoeuvre, ManoeuvreModel]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, ManoeuvreModel, Manoeuvre, "manoeuvre_id")
