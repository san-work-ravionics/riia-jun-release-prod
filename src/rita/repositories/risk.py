"""Repository for the risk_timeline table (risk metrics time series)."""

from sqlalchemy.orm import Session

from rita.models.risk import RiskTimelineModel
from rita.repositories.base import SqlRepository
from rita.schemas.risk import RiskTimeline


class RiskTimelineRepository(SqlRepository[RiskTimeline, RiskTimelineModel]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, RiskTimelineModel, RiskTimeline, "risk_id")
