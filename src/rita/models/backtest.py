"""ORM models for the backtest_runs and backtest_results tables."""
from sqlalchemy import Column, Date, DateTime, Float, Integer, String

from rita.database import Base


class BacktestRunModel(Base):
    __tablename__ = "backtest_runs"

    run_id = Column(String, primary_key=True)
    instrument = Column(String, nullable=False, default="NIFTY")
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    model_version = Column(String, nullable=False)
    strategy_params = Column(String, nullable=True)   # JSON string
    triggered_by = Column(String, nullable=True)
    status = Column(String, nullable=False, default="pending")
    total_trades = Column(Integer, nullable=True)
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    recorded_at = Column(DateTime, nullable=False)


class BacktestResultModel(Base):
    __tablename__ = "backtest_results"

    result_id = Column(String, primary_key=True)
    run_id = Column(String, nullable=False)
    date = Column(Date, nullable=False)
    portfolio_value = Column(Float, nullable=False)
    benchmark_value = Column(Float, nullable=False)
    allocation = Column(Float, nullable=True)
    close_price = Column(Float, nullable=True)
    total_return = Column(Float, nullable=True)
    sharpe_ratio = Column(Float, nullable=True)
    max_drawdown = Column(Float, nullable=True)
    recorded_at = Column(DateTime, nullable=False)
