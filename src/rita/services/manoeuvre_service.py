"""ManoeuvreService — FnO manoeuvre persistence and retrieval.

ADR-001: Called by Experience Layer and Workflow routers only.
ADR-002: All data access via ManoeuvresRepository.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from rita.repositories.manoeuvres import ManoeuvresRepository
from rita.schemas.manoeuvres import Manoeuvre, ManoeuvreCreate


class ManoeuvreService:
    def __init__(self, db: Session) -> None:
        self._repo = ManoeuvresRepository(db)

    def record(self, body: ManoeuvreCreate) -> Manoeuvre:
        """Persist a new manoeuvre record. Generates manoeuvre_id and recorded_at."""
        now = datetime.now(timezone.utc)
        manoeuvre = Manoeuvre(
            **body.model_dump(),
            manoeuvre_id=str(uuid.uuid4()),
            recorded_at=now,
        )
        return self._repo.upsert(manoeuvre)

    def list_all(self) -> list[Manoeuvre]:
        """Return all manoeuvre records."""
        return self._repo.read_all()

    def list_recent(self, n: int = 50) -> list[Manoeuvre]:
        """Return the n most recent manoeuvres by timestamp descending."""
        all_records = self._repo.read_all()
        return sorted(all_records, key=lambda m: m.timestamp, reverse=True)[:n]

    def list_by_date(self, target_date: date) -> list[Manoeuvre]:
        """Return all manoeuvres for a given date."""
        return [m for m in self._repo.read_all() if m.date == target_date]
