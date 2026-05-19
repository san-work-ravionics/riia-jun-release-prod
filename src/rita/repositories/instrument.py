"""Repository for the instruments table."""
from sqlalchemy.orm import Session

from rita.models.instrument import InstrumentModel
from rita.repositories.base import SqlRepository
from rita.schemas.instrument import Instrument


class InstrumentRepository(SqlRepository[Instrument, InstrumentModel]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, InstrumentModel, Instrument, "instrument_id")
