"""Repositories for backtest_runs and backtest_results tables."""

from sqlalchemy.orm import Session

from rita.models.backtest import BacktestResultModel, BacktestRunModel
from rita.repositories.base import SqlRepository
from rita.schemas.backtest import BacktestResult, BacktestRun


class BacktestRunsRepository(SqlRepository[BacktestRun, BacktestRunModel]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, BacktestRunModel, BacktestRun, "run_id")

    def latest_for_model_version(self, model_version: str) -> BacktestRun | None:
        """Most recent pipeline backtest of a model version (F44 P4: shown next to ASTA)."""
        row = (
            self._db.query(BacktestRunModel)
            .filter(BacktestRunModel.model_version == model_version)
            .order_by(BacktestRunModel.recorded_at.desc())
            .first()
        )
        return self._to_schema(row) if row is not None else None


class BacktestResultsRepository(SqlRepository[BacktestResult, BacktestResultModel]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, BacktestResultModel, BacktestResult, "result_id")
