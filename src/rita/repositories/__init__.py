"""Repository layer — one class per database table.

ADR-002: All data access is mediated through these classes.
No other code may access the database directly.
CsvRepository is retained for backwards-compat with existing QA tests;
it will be removed in Day 18.
"""

from rita.repositories.alerts import AlertsRepository
from rita.repositories.audit import AuditLogRepository
from rita.repositories.backtest import BacktestResultsRepository, BacktestRunsRepository
from rita.repositories.base import (
    BaseRepository,
    CsvRepository,
    RepositoryValidationError,
    SqlRepository,
)
from rita.repositories.config_overrides import ConfigOverridesRepository
from rita.repositories.manoeuvres import ManoeuvresRepository
from rita.repositories.market_data import MarketDataCacheRepository
from rita.repositories.model_registry import ModelRegistryRepository
from rita.repositories.orders import OrdersRepository
from rita.repositories.portfolio import PortfolioRepository
from rita.repositories.positions import PositionsRepository
from rita.repositories.risk import RiskTimelineRepository
from rita.repositories.snapshots import SnapshotsRepository
from rita.repositories.trades import TradesRepository
from rita.repositories.training import TrainingMetricsRepository, TrainingRunsRepository

__all__ = [
    "BaseRepository",
    "CsvRepository",
    "SqlRepository",
    "RepositoryValidationError",
    "PositionsRepository",
    "OrdersRepository",
    "SnapshotsRepository",
    "TradesRepository",
    "PortfolioRepository",
    "ManoeuvresRepository",
    "BacktestRunsRepository",
    "BacktestResultsRepository",
    "TrainingRunsRepository",
    "TrainingMetricsRepository",
    "ModelRegistryRepository",
    "AlertsRepository",
    "AuditLogRepository",
    "MarketDataCacheRepository",
    "ConfigOverridesRepository",
    "RiskTimelineRepository",
]
