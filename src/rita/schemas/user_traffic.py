from pydantic import BaseModel


class UserTrafficSummary(BaseModel):
    total_users: int
    active_today: int
    active_this_week: int
    active_this_month: int
    total_logins_all_time: int


class DailyTrafficRow(BaseModel):
    date: str
    unique_users: int
    total_logins: int
    new_registrations: int


class UserTrafficResponse(BaseModel):
    summary: UserTrafficSummary
    daily: list[DailyTrafficRow]
