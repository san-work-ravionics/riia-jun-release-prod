"""Repository for user_portfolios table."""
from sqlalchemy.orm import Session

from rita.models.user_portfolio import UserPortfolioModel


class UserPortfolioRepo:
    def __init__(self, db: Session) -> None:
        self._db = db

    def find_active_by_key_id(self, key_id: str) -> UserPortfolioModel | None:
        return (
            self._db.query(UserPortfolioModel)
            .filter(
                UserPortfolioModel.key_id == key_id,
                UserPortfolioModel.is_active.is_(True),
            )
            .first()
        )

    def deactivate_all_for_key(self, key_id: str) -> None:
        """Set is_active=False for all portfolios under key_id. Caller commits."""
        self._db.query(UserPortfolioModel).filter(
            UserPortfolioModel.key_id == key_id,
        ).update({"is_active": False}, synchronize_session="fetch")

    def insert(self, row: UserPortfolioModel) -> None:
        """Add a new portfolio row. Caller commits."""
        self._db.add(row)
