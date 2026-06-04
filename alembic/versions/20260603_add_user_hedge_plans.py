"""add user_hedge_plans table

Revision ID: 20260603_add_user_hedge_plans
Revises: 20260602_add_total_value_eur
Create Date: 2026-06-03 16:40:00.000000

"""
from typing import Union, Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260603_add_user_hedge_plans"
down_revision: Union[str, Sequence[str], None] = "20260602_add_total_value_eur"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = inspector.get_table_names()

    if "user_hedge_plans" not in existing:
        op.create_table(
            "user_hedge_plans",
            sa.Column("key_id", sa.VARCHAR(), nullable=False),
            sa.Column("hedged_ids", sa.JSON(), nullable=False),
            sa.Column("coverage", sa.Integer(), nullable=False),
            sa.Column("scenario_tab", sa.VARCHAR(), nullable=False),
            sa.Column("duration", sa.VARCHAR(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["key_id"], ["user_portfolio_keys.key_id"]),
            sa.PrimaryKeyConstraint("key_id"),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = inspector.get_table_names()

    if "user_hedge_plans" in existing:
        op.drop_table("user_hedge_plans")
