"""Repositories for training_runs and training_metrics tables."""

from sqlalchemy.orm import Session

from rita.models.training import TrainingMetricModel, TrainingRunModel
from rita.repositories.base import SqlRepository
from rita.schemas.training import TrainingMetric, TrainingRun


class TrainingRunsRepository(SqlRepository[TrainingRun, TrainingRunModel]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, TrainingRunModel, TrainingRun, "run_id")


class TrainingMetricsRepository(SqlRepository[TrainingMetric, TrainingMetricModel]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, TrainingMetricModel, TrainingMetric, "metric_id")
