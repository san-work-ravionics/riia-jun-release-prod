from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from rita.models.api_call_log import ApiCallLogModel


class ApiCallLogRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        path: str,
        method: str,
        status_code: Optional[int],
        duration_ms: Optional[float],
        called_at: datetime,
    ) -> ApiCallLogModel:
        record = ApiCallLogModel(
            path=path,
            method=method,
            status_code=status_code,
            duration_ms=duration_ms,
            called_at=called_at,
        )
        self.db.add(record)
        self.db.commit()
        return record

    def aggregate_by_path_method(
        self,
        limit: int = 200,
        method_filter: Optional[str] = None,
        path_prefix: Optional[str] = None,
    ) -> list[dict]:
        query = self.db.query(ApiCallLogModel)
        if method_filter:
            query = query.filter(ApiCallLogModel.method == method_filter.upper())
        if path_prefix:
            query = query.filter(ApiCallLogModel.path.startswith(path_prefix))
        rows = query.order_by(ApiCallLogModel.called_at.desc()).limit(limit).all()

        grouped: dict[tuple, list] = {}
        for r in rows:
            key = (r.path, r.method)
            grouped.setdefault(key, []).append(r)

        result = []
        for (path, method), records in grouped.items():
            durations = [r.duration_ms for r in records if r.duration_ms is not None]
            error_count = sum(1 for r in records if r.status_code and r.status_code >= 400)
            last_called = max((r.called_at for r in records), default=None)
            sorted_d = sorted(durations)
            n = len(sorted_d)
            p50 = sorted_d[n // 2] if n else None
            p95 = sorted_d[int(n * 0.95)] if n else None
            result.append(
                {
                    "path": path,
                    "method": method,
                    "call_count": len(records),
                    "p50_ms": round(p50, 2) if p50 is not None else None,
                    "p95_ms": round(p95, 2) if p95 is not None else None,
                    "error_count": error_count,
                    "error_rate_pct": round(error_count / len(records) * 100, 2) if records else 0.0,
                    "last_called_at": last_called.isoformat() if last_called else None,
                }
            )
        return sorted(result, key=lambda x: x["call_count"], reverse=True)
