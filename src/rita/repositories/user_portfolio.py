"""Repository for user_portfolios table.

F44 P2 (D1): one active portfolio per (key_id, location); ``location`` NULL is the legacy
cross-geography portfolio and counts as its own bucket.
"""
from sqlalchemy.orm import Session

from rita.models.user_portfolio import UserPortfolioModel


class UserPortfolioRepo:
    def __init__(self, db: Session) -> None:
        self._db = db

    def find_active_by_key_id(self, key_id: str) -> UserPortfolioModel | None:
        """The most recently saved active portfolio of any location (legacy single-portfolio read)."""
        return (
            self._db.query(UserPortfolioModel)
            .filter(
                UserPortfolioModel.key_id == key_id,
                UserPortfolioModel.is_active.is_(True),
            )
            .order_by(UserPortfolioModel.updated_at.desc(), UserPortfolioModel.created_at.desc())
            .first()
        )

    def find_active_by_key_and_location(self, key_id: str, location: str | None) -> UserPortfolioModel | None:
        """The active portfolio for (key_id, location); ``location=None`` → the legacy row."""
        loc_filter = (
            UserPortfolioModel.location.is_(None) if location is None
            else UserPortfolioModel.location == location
        )
        return (
            self._db.query(UserPortfolioModel)
            .filter(
                UserPortfolioModel.key_id == key_id,
                UserPortfolioModel.is_active.is_(True),
                loc_filter,
            )
            .order_by(UserPortfolioModel.updated_at.desc(), UserPortfolioModel.created_at.desc())
            .first()
        )

    def deactivate_for_key_and_location(self, key_id: str, location: str | None) -> None:
        """Set is_active=False for the (key_id, location) portfolios only (D1). Caller commits."""
        loc_filter = (
            UserPortfolioModel.location.is_(None) if location is None
            else UserPortfolioModel.location == location
        )
        self._db.query(UserPortfolioModel).filter(
            UserPortfolioModel.key_id == key_id, loc_filter,
        ).update({"is_active": False}, synchronize_session="fetch")

    def insert(self, row: UserPortfolioModel) -> None:
        """Add a new portfolio row. Caller commits."""
        self._db.add(row)
