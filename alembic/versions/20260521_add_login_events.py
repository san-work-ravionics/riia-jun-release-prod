"""add login_events table and first_login_date column

Revision ID: 20260521_add_login_events
Revises: 20260520_add_yf_ticker
Create Date: 2026-05-21 19:56:00.000000

"""
from typing import Union, Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260521_add_login_events"
down_revision: Union[str, Sequence[str], None] = "20260520_add_yf_ticker"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create login_events table (idempotency: skip if exists)
    try:
        op.create_table(
            "login_events",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("logged_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_login_events_id"), "login_events", ["id"], unique=False)
        op.create_index(op.f("ix_login_events_user_id"), "login_events", ["user_id"], unique=False)
    except Exception:
        pass  # table already exists

    # Add first_login_date column to users (idempotency: ignore OperationalError)
    try:
        op.add_column("users", sa.Column("first_login_date", sa.DateTime(), nullable=True))
    except Exception:
        pass  # column already exists


def downgrade() -> None:
    try:
        op.drop_index(op.f("ix_login_events_user_id"), table_name="login_events")
    except Exception:
        pass
    try:
        op.drop_index(op.f("ix_login_events_id"), table_name="login_events")
    except Exception:
        pass
    try:
        op.drop_table("login_events")
    except Exception:
        pass
    try:
        op.drop_column("users", "first_login_date")
    except Exception:
        pass
