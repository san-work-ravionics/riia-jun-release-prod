"""Repositories for training_runs and training_metrics tables."""

from sqlalchemy.orm import Session

from rita.models.training import TrainingMetricModel, TrainingRunModel
from rita.repositories.base import SqlRepository
from rita.schemas.training import TrainingMetric, TrainingRun


class TrainingRunsRepository(SqlRepository[TrainingRun, TrainingRunModel]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, TrainingRunModel, TrainingRun, "run_id")

    def find_complete_by_model_version(self, model_version: str) -> list[TrainingRun]:
        """Completed runs of a model version, newest first (F44 P4: the ASTA training record)."""
        rows = (
            self._db.query(TrainingRunModel)
            .filter(TrainingRunModel.model_version == model_version,
                    TrainingRunModel.status == "complete")
            .order_by(TrainingRunModel.recorded_at.desc())
            .all()
        )
        return [self._to_schema(r) for r in rows]


class TrainingMetricsRepository(SqlRepository[TrainingMetric, TrainingMetricModel]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, TrainingMetricModel, TrainingMetric, "metric_id")
