"""Repository for the append-only user_retirement_plan_history table (F43 Phase 1b).

ADR-002: no db.commit() inside the repo — RetirementPlanService commits once per save.
Rows are never updated or deleted.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from rita.models.user_retirement_plan_history import UserRetirementPlanHistoryModel as _M


class UserRetirementPlanHistoryRepo:
    def __init__(self, db: Session) -> None:
        self._db = db

    def append(self, row: _M) -> None:
        """Add a history row to the session.  Caller commits."""
        self._db.add(row)

    def list_by_user_id(self, user_id: str, limit: int = 50) -> list[_M]:
        """Newest-first rows for one user."""
        return (
            self._db.query(_M)
            .filter(_M.user_id == user_id)
            .order_by(_M.saved_at.desc(), _M.history_id.desc())
            .limit(limit)
            .all()
        )

    def find_for_user(self, user_id: str, history_id: str) -> _M | None:
        """One row, only if it belongs to the user."""
        return (
            self._db.query(_M)
            .filter(_M.history_id == history_id, _M.user_id == user_id)
            .first()
        )
