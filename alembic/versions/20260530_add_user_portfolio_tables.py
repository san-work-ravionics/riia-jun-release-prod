"""add user_portfolio_keys and user_portfolios tables

Revision ID: 20260530_add_user_portfolio_tables
Revises: 20260521_add_login_events
Create Date: 2026-05-30 15:20:00.000000

"""
from typing import Union, Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260530_add_user_portfolio_tables"
down_revision: Union[str, Sequence[str], None] = "20260521_add_login_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = inspector.get_table_names()

    if "user_portfolio_keys" not in existing:
        op.create_table(
            "user_portfolio_keys",
            sa.Column("key_id", sa.VARCHAR(), nullable=False),
            sa.Column("user_id", sa.VARCHAR(), nullable=False),
            sa.Column("created_at", sa.DATETIME(), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("key_id"),
        )

    if "user_portfolios" not in existing:
        op.create_table(
            "user_portfolios",
            sa.Column("portfolio_id", sa.VARCHAR(), nullable=False),
            sa.Column("key_id", sa.VARCHAR(), nullable=False),
            sa.Column("name", sa.VARCHAR(), nullable=True),
            sa.Column("holdings", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DATETIME(), nullable=True),
            sa.Column("updated_at", sa.DATETIME(), nullable=True),
            sa.Column("is_active", sa.BOOLEAN(), nullable=True, server_default="1"),
            sa.ForeignKeyConstraint(["key_id"], ["user_portfolio_keys.key_id"]),
            sa.PrimaryKeyConstraint("portfolio_id"),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = inspector.get_table_names()

    if "user_portfolios" in existing:
        op.drop_table("user_portfolios")

    if "user_portfolio_keys" in existing:
        op.drop_table("user_portfolio_keys")
