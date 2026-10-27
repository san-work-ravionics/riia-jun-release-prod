"""ORM models for the F44 P4 Jarvis tables (Spec_DB § F44, ADR-007 §8, ADR-008).

- ``user_journeys``   — one row per Jarvis journey; the only table an MCP tool writes
  (``journey.save``).  One active row per (user, location): the service transaction plus the
  partial unique index ``ux_user_journeys_one_active``.  ``version`` is the compare-and-set
  counter (rev 1 A5).
- ``jarvis_sessions`` — one chat session per (user, location) while active.
- ``jarvis_messages`` — append-only chat messages.

Personal data: goals, amounts and message text — never logged beyond counts / ids.
``user_id`` is a plain indexed String with no FK (the dev user ``rita-dev`` has no users row).
"""
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import Boolean, Column, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.sql import func

from rita.database import Base

SCHEMA_VERSION = 1


def utcnow() -> datetime:
    """Microsecond UTC timestamp (SQLite ``func.now()`` has 1-second resolution)."""
    return datetime.now(timezone.utc)


class UserJourneyModel(Base):
    __tablename__ = "user_journeys"

    journey_id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False, index=True)
    location = Column(String, nullable=False)
    currency = Column(String(3), nullable=False)
    state = Column(String, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    back_to_plan_reason = Column(String, nullable=True)
    plan_updated_at = Column(DateTime(timezone=True), nullable=True)
    goal_return = Column(Float, nullable=True)
    horizon_years = Column(Float, nullable=True)
    goal_value = Column(Float, nullable=True)
    target_return = Column(Float, nullable=True)
    reselect_count = Column(Integer, nullable=False, default=0, server_default="0")
    reselect_year = Column(Integer, nullable=True)
    selection = Column(sa.JSON, nullable=True)
    proposal = Column(sa.JSON, nullable=True)
    tracking = Column(sa.JSON, nullable=True)
    reselections = Column(sa.JSON, nullable=False, default=list)
    segments = Column(sa.JSON, nullable=False, default=list)
    plan_year_start = Column(Date, nullable=True)
    previous_journey_id = Column(String, nullable=True)
    version = Column(Integer, nullable=False, default=1, server_default="1")
    portfolio_id = Column(String, nullable=True)
    schema_version = Column(Integer, nullable=False, default=SCHEMA_VERSION,
                            server_default=str(SCHEMA_VERSION))
    app_version = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow,
                        server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow,
                        server_default=func.now())

    __table_args__ = (
        Index("ix_user_journeys_user_loc_active", "user_id", "location", "is_active"),
        Index("ux_user_journeys_one_active", "user_id", "location", unique=True,
              sqlite_where=sa.text("is_active = 1"), postgresql_where=sa.text("is_active")),
    )


class JarvisSessionModel(Base):
    __tablename__ = "jarvis_sessions"

    session_id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False, index=True)
    location = Column(String, nullable=True)
    journey_id = Column(String, ForeignKey("user_journeys.journey_id"), nullable=True)
    provider = Column(String, nullable=False, default="minilm", server_default="minilm")
    message_count = Column(Integer, nullable=False, default=0, server_default="0")
    claude_tokens_in = Column(Integer, nullable=False, default=0, server_default="0")
    claude_tokens_out = Column(Integer, nullable=False, default=0, server_default="0")
    started_at = Column(DateTime(timezone=True), nullable=False, default=utcnow,
                        server_default=func.now())
    last_activity_at = Column(DateTime(timezone=True), nullable=False, default=utcnow,
                              server_default=func.now())
    status = Column(String, nullable=False, default="open", server_default="open")

    __table_args__ = (Index("ix_jarvis_sessions_user_started", "user_id", "started_at"),)


class JarvisMessageModel(Base):
    __tablename__ = "jarvis_messages"

    message_id = Column(String, primary_key=True)
    session_id = Column(String, ForeignKey("jarvis_sessions.session_id"), nullable=False)
    role = Column(String, nullable=False)
    text = Column(Text, nullable=True)
    intent = Column(String, nullable=True)
    confidence = Column(Float, nullable=True)
    slots = Column(sa.JSON, nullable=True)
    template_id = Column(String, nullable=True)
    provider = Column(String, nullable=False, default="minilm", server_default="minilm")
    tool_calls = Column(sa.JSON, nullable=True)
    tokens_in = Column(Integer, nullable=True)
    tokens_out = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow,
                        server_default=func.now())

    __table_args__ = (Index("ix_jarvis_messages_session_created", "session_id", "created_at"),)
