"""add yf_ticker to instruments table

Revision ID: 20260520_add_yf_ticker
Revises: 20260517_add_currency
Create Date: 2026-05-20 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260520_add_yf_ticker'
down_revision: Union[str, Sequence[str], None] = '20260517_add_currency'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add yf_ticker column to instruments table (idempotent)."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_cols = {c['name'] for c in inspector.get_columns('instruments')}
    if 'yf_ticker' not in existing_cols:
        op.add_column(
            'instruments',
            sa.Column('yf_ticker', sa.String(), nullable=True),
        )


def downgrade() -> None:
    """Remove yf_ticker column from instruments table (idempotent)."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_cols = {c['name'] for c in inspector.get_columns('instruments')}
    if 'yf_ticker' in existing_cols:
        op.drop_column('instruments', 'yf_ticker')
