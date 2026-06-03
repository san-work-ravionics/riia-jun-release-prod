"""add total_value_eur to user_portfolios

Revision ID: 20260602_add_total_value_eur
Revises: 20260530_add_user_portfolio_tables
Create Date: 2026-06-02 18:00:00.000000

"""
from typing import Union, Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260602_add_total_value_eur"
down_revision: Union[str, Sequence[str], None] = "20260530_add_user_portfolio_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    cols = {c["name"] for c in inspector.get_columns("user_portfolios")}
    if "total_value_eur" not in cols:
        op.add_column("user_portfolios", sa.Column("total_value_eur", sa.Float(), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    cols = {c["name"] for c in inspector.get_columns("user_portfolios")}
    if "total_value_eur" in cols:
        op.drop_column("user_portfolios", "total_value_eur")
