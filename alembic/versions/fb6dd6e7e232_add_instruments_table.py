"""add instruments table

Revision ID: fb6dd6e7e232
Revises: 11a27794a41e
Create Date: 2026-04-12 17:17:17.897783

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fb6dd6e7e232'
down_revision: Union[str, Sequence[str], None] = '11a27794a41e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if 'instruments' not in existing_tables:
        op.create_table(
            'instruments',
            sa.Column('instrument_id', sa.String(), nullable=False),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('exchange', sa.String(), nullable=False),
            sa.Column('country_code', sa.String(), nullable=False),
            sa.Column('lot_size', sa.Integer(), nullable=True),
            sa.Column('is_available', sa.Boolean(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint('instrument_id'),
        )

    existing_cols = {c['name'] for c in inspector.get_columns('training_runs')}
    if 'instrument' not in existing_cols:
        op.add_column(
            'training_runs',
            sa.Column('instrument', sa.String(), nullable=False, server_default='NIFTY'),
        )


def downgrade() -> None:
    """Downgrade schema."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    existing_cols = {c['name'] for c in inspector.get_columns('training_runs')}
    if 'instrument' in existing_cols:
        op.drop_column('training_runs', 'instrument')

    if 'instruments' in inspector.get_table_names():
        op.drop_table('instruments')
