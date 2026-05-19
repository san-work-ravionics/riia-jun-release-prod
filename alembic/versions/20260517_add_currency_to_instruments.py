"""add currency to instruments table

Revision ID: 20260517_add_currency
Revises: c7e2a4f81d39
Create Date: 2026-05-17 21:37:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260517_add_currency'
down_revision: Union[str, Sequence[str], None] = 'e9f3b2c41a07'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add currency column to instruments table (idempotent)."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_cols = {c['name'] for c in inspector.get_columns('instruments')}
    if 'currency' not in existing_cols:
        op.add_column(
            'instruments',
            sa.Column('currency', sa.String(10), nullable=True),
        )


def downgrade() -> None:
    """Remove currency column from instruments table (idempotent)."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_cols = {c['name'] for c in inspector.get_columns('instruments')}
    if 'currency' in existing_cols:
        op.drop_column('instruments', 'currency')
