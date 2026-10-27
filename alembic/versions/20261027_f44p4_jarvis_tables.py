"""F44 Phase 4 — Jarvis tables: user_journeys, jarvis_sessions, jarvis_messages

``user_journeys`` (Spec_DB § F44 + P4 revisions): ``reselect_year``, ``back_to_plan_reason``,
``proposal``, ``version`` (compare-and-set), ``previous_journey_id``, ``plan_year_start``,
``segments``; ``tracking`` holds the revised per-holding shape (JSON, no DDL impact).
Indexes ``ix_user_journeys_user_loc_active`` and the partial unique
``ux_user_journeys_one_active (user_id, location) WHERE is_active`` (one active journey per
user + location).  ``jarvis_sessions`` (+ index (user_id, started_at)) and the append-only
``jarvis_messages`` (+ index (session_id, created_at)).

Inspector-guarded both ways: ``create_all`` may already have created a table (then only missing
indexes are added).  Plain DDL, nothing reflected, no FK to ``users`` (PATTERN-015: a fresh
migration-only DB has no ``users`` table).  Downgrade drops jarvis_messages → jarvis_sessions →
user_journeys.

Revision ID: 20261027_f44p4_jarvis_tables
Revises: 20261026_f44p2_user_portfolio_currency
Create Date: 2026-10-27 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261027_f44p4_jarvis_tables"
down_revision: Union[str, Sequence[str], None] = "20261026_f44p2_user_portfolio_currency"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TS = dict(nullable=False, server_default=sa.func.now())


def _inspector():
    return sa.inspect(op.get_bind())


def _tables() -> set[str]:
    return set(_inspector().get_table_names())


def _indexes(table: str) -> set[str]:
    return {i["name"] for i in _inspector().get_indexes(table)}


def upgrade() -> None:
    tables = _tables()
    if "user_journeys" not in tables:
        op.create_table(
            "user_journeys",
            sa.Column("journey_id", sa.String(), primary_key=True),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("location", sa.String(), nullable=False),
            sa.Column("currency", sa.String(3), nullable=False),
            sa.Column("state", sa.String(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("back_to_plan_reason", sa.String(), nullable=True),
            sa.Column("plan_updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("goal_return", sa.Float(), nullable=True),
            sa.Column("horizon_years", sa.Float(), nullable=True),
            sa.Column("goal_value", sa.Float(), nullable=True),
            sa.Column("target_return", sa.Float(), nullable=True),
            sa.Column("reselect_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("reselect_year", sa.Integer(), nullable=True),
            sa.Column("selection", sa.JSON(), nullable=True),
            sa.Column("proposal", sa.JSON(), nullable=True),
            sa.Column("tracking", sa.JSON(), nullable=True),
            sa.Column("reselections", sa.JSON(), nullable=False),
            sa.Column("segments", sa.JSON(), nullable=False),
            sa.Column("plan_year_start", sa.Date(), nullable=True),
            sa.Column("previous_journey_id", sa.String(), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("portfolio_id", sa.String(), nullable=True),
            sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("app_version", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), **_TS),
            sa.Column("updated_at", sa.DateTime(timezone=True), **_TS),
        )
    idx = _indexes("user_journeys")
    if "ix_user_journeys_user_id" not in idx:
        op.create_index("ix_user_journeys_user_id", "user_journeys", ["user_id"])
    if "ix_user_journeys_user_loc_active" not in idx:
        op.create_index("ix_user_journeys_user_loc_active", "user_journeys",
                        ["user_id", "location", "is_active"])
    if "ux_user_journeys_one_active" not in idx:
        op.create_index("ux_user_journeys_one_active", "user_journeys", ["user_id", "location"],
                        unique=True, sqlite_where=sa.text("is_active = 1"),
                        postgresql_where=sa.text("is_active"))

    if "jarvis_sessions" not in tables:
        op.create_table(
            "jarvis_sessions",
            sa.Column("session_id", sa.String(), primary_key=True),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("location", sa.String(), nullable=True),
            sa.Column("journey_id", sa.String(), sa.ForeignKey("user_journeys.journey_id"),
                      nullable=True),
            sa.Column("provider", sa.String(), nullable=False, server_default="minilm"),
            sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("claude_tokens_in", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("claude_tokens_out", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("started_at", sa.DateTime(timezone=True), **_TS),
            sa.Column("last_activity_at", sa.DateTime(timezone=True), **_TS),
            sa.Column("status", sa.String(), nullable=False, server_default="open"),
        )
    idx = _indexes("jarvis_sessions")
    if "ix_jarvis_sessions_user_id" not in idx:
        op.create_index("ix_jarvis_sessions_user_id", "jarvis_sessions", ["user_id"])
    if "ix_jarvis_sessions_user_started" not in idx:
        op.create_index("ix_jarvis_sessions_user_started", "jarvis_sessions",
                        ["user_id", "started_at"])

    if "jarvis_messages" not in tables:
        op.create_table(
            "jarvis_messages",
            sa.Column("message_id", sa.String(), primary_key=True),
            sa.Column("session_id", sa.String(), sa.ForeignKey("jarvis_sessions.session_id"),
                      nullable=False),
            sa.Column("role", sa.String(), nullable=False),
            sa.Column("text", sa.Text(), nullable=True),
            sa.Column("intent", sa.String(), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("slots", sa.JSON(), nullable=True),
            sa.Column("template_id", sa.String(), nullable=True),
            sa.Column("provider", sa.String(), nullable=False, server_default="minilm"),
            sa.Column("tool_calls", sa.JSON(), nullable=True),
            sa.Column("tokens_in", sa.Integer(), nullable=True),
            sa.Column("tokens_out", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), **_TS),
        )
    if "ix_jarvis_messages_session_created" not in _indexes("jarvis_messages"):
        op.create_index("ix_jarvis_messages_session_created", "jarvis_messages",
                        ["session_id", "created_at"])


def downgrade() -> None:
    tables = _tables()
    for name in ("jarvis_messages", "jarvis_sessions", "user_journeys"):
        if name in tables:
            op.drop_table(name)
