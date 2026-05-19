"""Repository for the portfolio table (daily performance summary)."""

from sqlalchemy.orm import Session

from rita.models.portfolio import PortfolioModel
from rita.repositories.base import SqlRepository
from rita.schemas.portfolio import Portfolio


class PortfolioRepository(SqlRepository[Portfolio, PortfolioModel]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, PortfolioModel, Portfolio, "portfolio_id")
