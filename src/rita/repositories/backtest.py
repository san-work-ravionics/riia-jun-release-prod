"""Repositories for backtest_runs and backtest_results tables."""

from sqlalchemy.orm import Session

from rita.models.backtest import BacktestResultModel, BacktestRunModel
from rita.repositories.base import SqlRepository
from rita.schemas.backtest import BacktestResult, BacktestRun


class BacktestRunsRepository(SqlRepository[BacktestRun, BacktestRunModel]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, BacktestRunModel, BacktestRun, "run_id")


class BacktestResultsRepository(SqlRepository[BacktestResult, BacktestResultModel]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, BacktestResultModel, BacktestResult, "result_id")
