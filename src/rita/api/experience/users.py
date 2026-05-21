import datetime
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from rita.database import get_db
from rita.schemas.user_traffic import UserTrafficResponse, UserTrafficSummary, DailyTrafficRow
from rita.repositories.login_event import LoginEventRepository

router = APIRouter(prefix="/api/v1/experience/users", tags=["experience:users"])


@router.get("/traffic", response_model=UserTrafficResponse)
def get_user_traffic(
    db: Session = Depends(get_db),
) -> UserTrafficResponse:
    """Return aggregated login KPIs and 30-day daily breakdown — no PII."""
    repo = LoginEventRepository(db)
    now = datetime.datetime.utcnow()
    today_start = datetime.datetime(now.year, now.month, now.day)
    week_start = now - datetime.timedelta(days=7)
    month_start = now - datetime.timedelta(days=30)

    summary = UserTrafficSummary(
        total_users=repo.count_total_users(),
        active_today=repo.count_unique_users_since(today_start),
        active_this_week=repo.count_unique_users_since(week_start),
        active_this_month=repo.count_unique_users_since(month_start),
        total_logins_all_time=repo.count_logins_since(datetime.datetime.min),
    )
    daily_rows = repo.get_daily_breakdown(days=30)
    daily = [DailyTrafficRow(**row) for row in daily_rows]
    return UserTrafficResponse(summary=summary, daily=daily)
