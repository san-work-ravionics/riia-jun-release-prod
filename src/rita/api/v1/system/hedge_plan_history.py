"""System router — hedge-plan history export (F40).

GET /api/v1/system/hedge-plan-history

Role-gated (can_access_ops) export of the append-only user_hedge_plan_history table
for hedge-performance analysis.  Reads ONE table through its repository.  Not called
by dashboard JS.  CSV flattening lives in services/hedge_history_export.py.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from rita.auth import RequireRole
from rita.database import get_db
from rita.repositories.user_hedge_plan_history import UserHedgePlanHistoryRepo
from rita.schemas.user_hedge_plan import HedgePlanHistoryAdminList, HedgePlanHistoryAdminOut
from rita.services.hedge_history_export import to_csv

router = APIRouter(prefix="/api/v1/system", tags=["system:hedge-plan-history"])


def _parse_dt(value: str | None, name: str) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{name} must be an ISO date or datetime")
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@router.get("/hedge-plan-history", dependencies=[Depends(RequireRole("can_access_ops"))])
def export_hedge_plan_history(
    since: str | None = Query(None),
    until: str | None = Query(None),
    format: Literal["json", "csv"] = Query("json"),
    limit: int = Query(1000, ge=1, le=10000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    rows = UserHedgePlanHistoryRepo(db).list_all(
        since=_parse_dt(since, "since"), until=_parse_dt(until, "until"),
        limit=limit, offset=offset,
    )
    if format == "csv":
        return Response(content=to_csv(rows), media_type="text/csv")
    items = [HedgePlanHistoryAdminOut.model_validate(r) for r in rows]
    return HedgePlanHistoryAdminList(
        items=items, count=len(items), limit=limit, offset=offset, since=since, until=until,
    )
