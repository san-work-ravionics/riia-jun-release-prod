"""Repository for user_portfolio_keys table."""
import uuid

from sqlalchemy.orm import Session

from rita.models.user_portfolio_key import UserPortfolioKeyModel


class UserPortfolioKeyRepo:
    def __init__(self, db: Session) -> None:
        self._db = db

    def find_by_user_id(self, user_id: str) -> UserPortfolioKeyModel | None:
        return (
            self._db.query(UserPortfolioKeyModel)
            .filter(UserPortfolioKeyModel.user_id == user_id)
            .first()
        )

    def find_or_create(self, user_id: str) -> UserPortfolioKeyModel:
        row = self.find_by_user_id(user_id)
        if row is not None:
            return row
        row = UserPortfolioKeyModel(
            key_id=str(uuid.uuid4()),
            user_id=user_id,
        )
        self._db.add(row)
        self._db.flush()  # populate key_id without committing
        return row
