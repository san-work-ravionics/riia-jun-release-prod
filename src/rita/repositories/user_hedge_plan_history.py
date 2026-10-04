"""Repository for the append-only user_hedge_plan_history table (F40).

ADR-002: no db.commit() inside the repo — HedgePlanService commits once per PUT.
Rows are never updated or deleted.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from rita.models.user_hedge_plan_history import UserHedgePlanHistoryModel as _M


class UserHedgePlanHistoryRepo:
    def __init__(self, db: Session) -> None:
        self._db = db

    def append(self, row: _M) -> None:
        """Add a history row to the session.  Caller commits."""
        self._db.add(row)

    def list_by_key_id(self, key_id: str, limit: int = 50, trigger: str | None = None) -> list[_M]:
        """Newest-first rows for one portfolio key."""
        q = self._db.query(_M).filter(_M.key_id == key_id)
        if trigger:
            q = q.filter(_M.trigger == trigger)
        return q.order_by(_M.saved_at.desc(), _M.history_id.desc()).limit(limit).all()

    def latest_by_key_id(self, key_id: str) -> _M | None:
        rows = self.list_by_key_id(key_id, limit=1)
        return rows[0] if rows else None

    def list_all(
        self,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[_M]:
        """All users, oldest-first (stable export order) with optional saved_at window."""
        q = self._db.query(_M)
        if since is not None:
            q = q.filter(_M.saved_at >= since)
        if until is not None:
            q = q.filter(_M.saved_at <= until)
        return q.order_by(_M.saved_at.asc(), _M.history_id.asc()).offset(offset).limit(limit).all()
