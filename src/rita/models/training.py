"""ORM models for the training_runs and training_metrics tables."""
from sqlalchemy import Column, DateTime, Float, Integer, String  # noqa: F401

from rita.database import Base


class TrainingRunModel(Base):
    __tablename__ = "training_runs"

    run_id = Column(String, primary_key=True)
    instrument = Column(String, nullable=False, default="NIFTY")
    model_version = Column(String, nullable=False)
    algorithm = Column(String, nullable=False, default="DoubleDQN")
    timesteps = Column(Integer, nullable=False)
    learning_rate = Column(Float, nullable=False)
    buffer_size = Column(Integer, nullable=False)
    net_arch = Column(String, nullable=False)
    exploration_pct = Column(Float, nullable=False)
    notes = Column(String, nullable=True)
    status = Column(String, nullable=False, default="pending")
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    train_sharpe = Column(Float, nullable=True)
    train_mdd = Column(Float, nullable=True)
    train_return = Column(Float, nullable=True)
    train_trades = Column(Integer, nullable=True)
    val_sharpe = Column(Float, nullable=True)
    val_mdd = Column(Float, nullable=True)
    val_return = Column(Float, nullable=True)
    val_cagr = Column(Float, nullable=True)
    val_trades = Column(Integer, nullable=True)
    backtest_sharpe = Column(Float, nullable=True)
    backtest_mdd = Column(Float, nullable=True)
    backtest_return = Column(Float, nullable=True)
    backtest_trades = Column(Integer, nullable=True)
    model_path = Column(String, nullable=True)
    recorded_at = Column(DateTime, nullable=False)


class TrainingMetricModel(Base):
    __tablename__ = "training_metrics"

    metric_id = Column(String, primary_key=True)
    run_id = Column(String, nullable=False)
    episode = Column(Integer, nullable=False)
    reward = Column(Float, nullable=False)
    loss = Column(Float, nullable=True)
    epsilon = Column(Float, nullable=False)
    portfolio_value = Column(Float, nullable=True)
    recorded_at = Column(DateTime, nullable=False)
