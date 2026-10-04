"""F40: user_hedge_plan_history table + user_hedge_plans.selections

Revision ID: 20261005_f40_hedge_plan_history
Revises: 20261003_add_last_step_to_user_hedge_plans
Create Date: 2026-10-05 00:00:00.000000

Idempotent: lifespan create_all may already have created the new table, and
create_all never adds columns, so each object is inspector-guarded.
"""
from typing import Union, Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20261005_f40_hedge_plan_history"
down_revision: Union[str, Sequence[str], None] = "20261003_add_last_step_to_user_hedge_plans"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "user_hedge_plan_history"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    plan_cols = [c["name"] for c in inspector.get_columns("user_hedge_plans")]
    if "selections" not in plan_cols:
        op.add_column("user_hedge_plans", sa.Column("selections", sa.JSON(), nullable=True))

    if _TABLE not in inspector.get_table_names():
        op.create_table(
            _TABLE,
            sa.Column("history_id", sa.String(), primary_key=True),
            sa.Column("key_id", sa.String(), sa.ForeignKey("user_portfolio_keys.key_id"), nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("saved_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("trigger", sa.String(), nullable=False),
            sa.Column("source", sa.String(), nullable=False),
            sa.Column("last_step", sa.String(), nullable=True),
            sa.Column("scenario_tab", sa.String(), nullable=False),
            sa.Column("coverage", sa.Integer(), nullable=False),
            sa.Column("duration", sa.String(), nullable=False),
            sa.Column("hedged_ids", sa.JSON(), nullable=False),
            sa.Column("selections", sa.JSON(), nullable=True),
            sa.Column("instruments", sa.JSON(), nullable=False),
            sa.Column("portfolio", sa.JSON(), nullable=False),
            sa.Column("margin", sa.JSON(), nullable=True),
            sa.Column("schema_version", sa.Integer(), nullable=False),
            sa.Column("app_version", sa.String(), nullable=False),
        )
        op.create_index("ix_user_hedge_plan_history_user_id", _TABLE, ["user_id"])
        op.create_index("ix_user_hedge_plan_history_key_saved", _TABLE, ["key_id", "saved_at"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    if _TABLE in inspector.get_table_names():
        op.drop_table(_TABLE)

    plan_cols = [c["name"] for c in inspector.get_columns("user_hedge_plans")]
    if "selections" in plan_cols:
        with op.batch_alter_table("user_hedge_plans") as batch_op:
            batch_op.drop_column("selections")
