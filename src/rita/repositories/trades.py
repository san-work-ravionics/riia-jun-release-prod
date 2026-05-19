"""Repository for the trades table (closed/executed positions)."""

from sqlalchemy.orm import Session

from rita.models.trades import TradeModel
from rita.repositories.base import SqlRepository
from rita.schemas.trades import Trade


class TradesRepository(SqlRepository[Trade, TradeModel]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, TradeModel, Trade, "trade_id")
