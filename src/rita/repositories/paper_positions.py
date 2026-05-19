"""Repository for the paper_positions table (simulated trading positions)."""

from sqlalchemy.orm import Session

from rita.models.paper_positions import PaperPositionModel
from rita.repositories.base import SqlRepository
from rita.schemas.paper_positions import PaperPosition


class PaperPositionsRepository(SqlRepository[PaperPosition, PaperPositionModel]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, PaperPositionModel, PaperPosition, "position_id")
