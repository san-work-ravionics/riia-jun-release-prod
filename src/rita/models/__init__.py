"""RITA SQLAlchemy ORM models — imports all model classes to register with Base.metadata."""
from .positions import PositionModel
from .paper_positions import PaperPositionModel
from .orders import OrderModel
from .snapshots import SnapshotModel
from .trades import TradeModel
from .portfolio import PortfolioModel
from .manoeuvres import ManoeuvreModel
from .backtest import BacktestRunModel, BacktestResultModel
from .training import TrainingRunModel, TrainingMetricModel
from .model_registry import ModelRegistryModel
from .alerts import AlertModel
from .audit import AuditLogModel
from .market_data import MarketDataCacheModel
from .config_overrides import ConfigOverrideModel
from .risk import RiskTimelineModel
from .instrument import InstrumentModel
from .user import UserModel
from .mcp_call import MCPCallModel
from .agent_builds import AgentBuildRunModel, AgentBuildAgentModel
from .commentary_log import CommentaryLogModel
from .api_call_log import ApiCallLogModel
from .login_event import LoginEventModel
from .user_portfolio_key import UserPortfolioKeyModel
from .user_portfolio import UserPortfolioModel
from .user_hedge_plan import UserHedgePlanModel

__all__ = [
    "PositionModel",
    "PaperPositionModel",
    "OrderModel",
    "SnapshotModel",
    "TradeModel",
    "PortfolioModel",
    "ManoeuvreModel",
    "BacktestRunModel",
    "BacktestResultModel",
    "TrainingRunModel",
    "TrainingMetricModel",
    "ModelRegistryModel",
    "AlertModel",
    "AuditLogModel",
    "MarketDataCacheModel",
    "ConfigOverrideModel",
    "RiskTimelineModel",
    "InstrumentModel",
    "UserModel",
    "MCPCallModel",
    "AgentBuildRunModel",
    "AgentBuildAgentModel",
    "CommentaryLogModel",
    "ApiCallLogModel",
    "LoginEventModel",
    "UserPortfolioKeyModel",
    "UserPortfolioModel",
    "UserHedgePlanModel",
]
