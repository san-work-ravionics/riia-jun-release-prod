"""Repository for the positions table (live open positions from broker)."""

from sqlalchemy.orm import Session

from rita.models.positions import PositionModel
from rita.repositories.base import SqlRepository
from rita.schemas.positions import Position


class PositionsRepository(SqlRepository[Position, PositionModel]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, PositionModel, Position, "position_id")
