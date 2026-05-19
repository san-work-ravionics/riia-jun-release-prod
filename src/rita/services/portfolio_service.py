"""PortfolioService — portfolio row persistence and retrieval.

ADR-001: Called by Experience Layer and Workflow routers only.
ADR-002: All data access via PortfolioRepository.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from rita.repositories.portfolio import PortfolioRepository
from rita.schemas.portfolio import Portfolio, PortfolioCreate


class PortfolioService:
    def __init__(self, db: Session) -> None:
        self._repo = PortfolioRepository(db)

    def record(self, body: PortfolioCreate) -> Portfolio:
        """Persist a new portfolio row."""
        now = datetime.now(timezone.utc)
        row = Portfolio(
            **body.model_dump(),
            portfolio_id=str(uuid.uuid4()),
            recorded_at=now,
        )
        return self._repo.upsert(row)

    def list_all(self) -> list[Portfolio]:
        """Return all portfolio rows."""
        return self._repo.read_all()

    def get_by_date(self, target_date: date) -> list[Portfolio]:
        """Return portfolio rows for the given date."""
        return [p for p in self._repo.read_all() if p.date == target_date]

    def get_latest(self) -> list[Portfolio]:
        """Return portfolio rows for the most recent date in the store.

        Returns [] if the store is empty.
        """
        rows = self._repo.read_all()
        if not rows:
            return []
        latest_date = max(r.date for r in rows)
        return [r for r in rows if r.date == latest_date]
