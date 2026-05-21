from sqlalchemy import Column, DateTime, String, ForeignKey
from rita.database import Base


class LoginEventModel(Base):
    __tablename__ = "login_events"
    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    logged_at = Column(DateTime, nullable=False)
