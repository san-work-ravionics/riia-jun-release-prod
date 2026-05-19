"""Repository for the commentary_logs table."""
from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from rita.models.commentary_log import CommentaryLogModel
from rita.schemas.commentary import CommentaryLogCreate


class CommentaryLogRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def create(self, log: CommentaryLogCreate) -> CommentaryLogModel:
        record = CommentaryLogModel(
            id=log.id,
            app=log.app,
            page=log.page,
            instrument=log.instrument,
            latency_ms=log.latency_ms,
            status=log.status,
            commentary_preview=log.commentary_preview,
            timestamp=log.timestamp,
        )
        self._db.add(record)
        self._db.commit()
        self._db.refresh(record)
        return record

    def get_summary(self) -> dict:
        """Return commentary KPIs: count, avg latency, error count."""
        total = self._db.query(func.count(CommentaryLogModel.id)).scalar() or 0
        avg_latency = (
            self._db.query(func.avg(CommentaryLogModel.latency_ms)).scalar() or 0.0
        )
        error_count = (
            self._db.query(func.count(CommentaryLogModel.id))
            .filter(CommentaryLogModel.status == "error")
            .scalar()
            or 0
        )
        return {
            "commentary_count": int(total),
            "commentary_avg_latency_ms": round(float(avg_latency), 1),
            "commentary_error_count": int(error_count),
        }
