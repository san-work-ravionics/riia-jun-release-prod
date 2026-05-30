"""Service layer for User Portfolio Store."""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from rita.models.user_portfolio import UserPortfolioModel
from rita.repositories.user_portfolio import UserPortfolioRepo
from rita.repositories.user_portfolio_key import UserPortfolioKeyRepo
from rita.schemas.user_portfolio import HoldingItem, UserPortfolioOut


class UserPortfolioService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def save(
        self,
        user_id: str,
        holdings: list[HoldingItem],
        name: str | None = None,
    ) -> UserPortfolioOut:
        """Persist a new portfolio snapshot for the user (soft-replaces the active one)."""
        if not holdings:
            raise ValueError("holdings must not be empty")
        if round(sum(h.allocation_pct for h in holdings), 6) != 100.0:
            raise ValueError("allocation_pct must sum to 100")

        resolved_name = name.strip() if name else "My Portfolio"

        key = UserPortfolioKeyRepo(self._db).find_or_create(user_id)
        UserPortfolioRepo(self._db).deactivate_all_for_key(key.key_id)

        new_row = UserPortfolioModel(
            portfolio_id=str(uuid.uuid4()),
            key_id=key.key_id,
            name=resolved_name,
            holdings=[h.model_dump() for h in holdings],
            is_active=True,
        )
        UserPortfolioRepo(self._db).insert(new_row)

        self._db.commit()
        self._db.refresh(new_row)
        return UserPortfolioOut.model_validate(new_row)

    def get(self, user_id: str) -> UserPortfolioOut | None:
        """Return the active portfolio for the user, or None if none exists."""
        key = UserPortfolioKeyRepo(self._db).find_by_user_id(user_id)
        if key is None:
            return None
        row = UserPortfolioRepo(self._db).find_active_by_key_id(key.key_id)
        if row is None:
            return None
        return UserPortfolioOut.model_validate(row)
