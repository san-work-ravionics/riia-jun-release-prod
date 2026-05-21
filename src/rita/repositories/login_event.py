import uuid
import datetime
from collections import defaultdict
from sqlalchemy.orm import Session
from sqlalchemy import func
from rita.models.login_event import LoginEventModel
from rita.models.user import UserModel


class LoginEventRepository:
    def __init__(self, db: Session):
        self.db = db

    def insert_event(self, user_id: str, logged_at: datetime.datetime) -> None:
        event = LoginEventModel(id=str(uuid.uuid4()), user_id=user_id, logged_at=logged_at)
        self.db.add(event)
        # caller commits

    def count_unique_users_since(self, since_dt: datetime.datetime) -> int:
        return self.db.query(func.count(func.distinct(LoginEventModel.user_id))).filter(
            LoginEventModel.logged_at >= since_dt
        ).scalar() or 0

    def count_logins_since(self, since_dt: datetime.datetime) -> int:
        return self.db.query(func.count(LoginEventModel.id)).filter(
            LoginEventModel.logged_at >= since_dt
        ).scalar() or 0

    def count_total_users(self) -> int:
        return self.db.query(func.count(UserModel.id)).scalar() or 0

    def get_daily_breakdown(self, days: int = 30) -> list:
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=days)
        events = self.db.query(LoginEventModel).filter(
            LoginEventModel.logged_at >= cutoff
        ).all()
        new_reg_rows = self.db.query(UserModel.first_login_date).filter(
            UserModel.first_login_date >= cutoff
        ).all()

        # Build date series (newest first)
        today = datetime.date.today()
        date_series = [(today - datetime.timedelta(days=i)).isoformat() for i in range(days)]

        logins_by_date: dict[str, list] = defaultdict(list)
        for e in events:
            logins_by_date[e.logged_at.date().isoformat()].append(e.user_id)

        new_regs_by_date: dict[str, int] = defaultdict(int)
        for row in new_reg_rows:
            if row.first_login_date:
                new_regs_by_date[row.first_login_date.date().isoformat()] += 1

        result = []
        for date_str in date_series:
            user_ids = logins_by_date.get(date_str, [])
            result.append({
                "date": date_str,
                "unique_users": len(set(user_ids)),
                "total_logins": len(user_ids),
                "new_registrations": new_regs_by_date.get(date_str, 0),
            })
        return result
