"""Repositories for the F44 P4 Jarvis tables (ADR-002; project.md §8 — every constructor takes
``db: Session``).  None of them commits: ``JourneyService`` / the Jarvis chat service own the
transaction."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session

from rita.models.jarvis import JarvisMessageModel, JarvisSessionModel, UserJourneyModel


class UserJourneyRepo:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_active(self, user_id: str, location: str) -> UserJourneyModel | None:
        return (
            self._db.query(UserJourneyModel)
            .filter(UserJourneyModel.user_id == user_id, UserJourneyModel.location == location,
                    UserJourneyModel.is_active.is_(True))
            .first()
        )

    def latest_any(self, user_id: str, location: str) -> UserJourneyModel | None:
        """Most recent journey for (user, location), active or closed (B1 carry-over)."""
        return (
            self._db.query(UserJourneyModel)
            .filter(UserJourneyModel.user_id == user_id, UserJourneyModel.location == location)
            .order_by(UserJourneyModel.created_at.desc(), UserJourneyModel.journey_id.desc())
            .first()
        )

    def get(self, journey_id: str) -> UserJourneyModel | None:
        return self._db.get(UserJourneyModel, journey_id)

    def insert(self, row: UserJourneyModel) -> None:
        self._db.add(row)

    def close(self, journey_id: str, expected_version: int, now: datetime) -> int:
        """Deactivate a journey (soft-replace) with compare-and-set; returns rows changed."""
        return self.cas_update(journey_id, expected_version,
                               {"is_active": False, "state": "closed", "updated_at": now})

    def cas_update(self, journey_id: str, expected_version: int, values: dict[str, Any]) -> int:
        """``UPDATE … SET …, version = version + 1 WHERE journey_id = :id AND version = :expected``.
        Returns the number of rows changed (0 = another writer won)."""
        stmt = (
            update(UserJourneyModel)
            .where(UserJourneyModel.journey_id == journey_id,
                   UserJourneyModel.version == expected_version)
            .values(**values, version=expected_version + 1)
            .execution_options(synchronize_session=False)
        )
        return int(self._db.execute(stmt).rowcount or 0)


class JarvisSessionRepo:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get(self, session_id: str) -> JarvisSessionModel | None:
        return self._db.get(JarvisSessionModel, session_id)

    def latest_open(self, user_id: str, location: str) -> JarvisSessionModel | None:
        return (
            self._db.query(JarvisSessionModel)
            .filter(JarvisSessionModel.user_id == user_id, JarvisSessionModel.location == location,
                    JarvisSessionModel.status == "open")
            .order_by(JarvisSessionModel.last_activity_at.desc(), JarvisSessionModel.started_at.desc())
            .first()
        )

    def insert(self, row: JarvisSessionModel) -> None:
        self._db.add(row)


class JarvisMessageRepo:
    def __init__(self, db: Session) -> None:
        self._db = db

    def append(self, row: JarvisMessageModel) -> None:
        self._db.add(row)

    def recent(self, session_id: str, limit: int) -> list[JarvisMessageModel]:
        """The last ``limit`` messages of a session, oldest first."""
        rows = (
            self._db.query(JarvisMessageModel)
            .filter(JarvisMessageModel.session_id == session_id)
            .order_by(JarvisMessageModel.created_at.desc(), JarvisMessageModel.message_id.desc())
            .limit(limit)
            .all()
        )
        return list(reversed(rows))
