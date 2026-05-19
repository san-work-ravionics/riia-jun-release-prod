"""Repository for the alerts table."""

from sqlalchemy.orm import Session

from rita.models.alerts import AlertModel
from rita.repositories.base import SqlRepository
from rita.schemas.alerts import Alert


class AlertsRepository(SqlRepository[Alert, AlertModel]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, AlertModel, Alert, "alert_id")
