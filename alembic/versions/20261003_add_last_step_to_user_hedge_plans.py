"""add last_step to user_hedge_plans

Revision ID: 20261003_add_last_step_to_user_hedge_plans
Revises: 20260920_seed_nse_option_bhav
Create Date: 2026-10-03 00:00:00.000000

"""
from typing import Union, Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20261003_add_last_step_to_user_hedge_plans"
down_revision: Union[str, Sequence[str], None] = "20260920_seed_nse_option_bhav"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = [c["name"] for c in inspector.get_columns("user_hedge_plans")]

    if "last_step" not in columns:
        op.add_column(
            "user_hedge_plans",
            sa.Column("last_step", sa.VARCHAR(), nullable=True, server_default="exposure"),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = [c["name"] for c in inspector.get_columns("user_hedge_plans")]

    if "last_step" in columns:
        with op.batch_alter_table("user_hedge_plans") as batch_op:
            batch_op.drop_column("last_step")
