"""Repository for user_hedge_plans table.

All methods follow ADR-002 repository pattern: no db.commit() inside the repo.
Callers (routers) are responsible for committing.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from rita.models.user_hedge_plan import UserHedgePlanModel


class UserHedgePlanRepo:
    def __init__(self, db: Session) -> None:
        self._db = db

    def find_by_key_id(self, key_id: str) -> UserHedgePlanModel | None:
        """Return the hedge plan for a given key_id, or None if not found."""
        return (
            self._db.query(UserHedgePlanModel)
            .filter(UserHedgePlanModel.key_id == key_id)
            .first()
        )

    def upsert(self, plan: UserHedgePlanModel) -> None:
        """Insert or update a hedge plan row.  Caller commits."""
        existing = self.find_by_key_id(plan.key_id)
        if existing is not None:
            existing.hedged_ids = plan.hedged_ids
            existing.coverage = plan.coverage
            existing.scenario_tab = plan.scenario_tab
            existing.duration = plan.duration
            existing.updated_at = plan.updated_at
        else:
            self._db.add(plan)
        # caller commits
