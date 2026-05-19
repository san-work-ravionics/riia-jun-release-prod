"""add commentary_logs table

Revision ID: c7e2a4f81d39
Revises: a3f9c1e82b5d
Create Date: 2026-05-15 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7e2a4f81d39'
down_revision: Union[str, Sequence[str], None] = 'a3f9c1e82b5d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create commentary_logs table if not already present."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing = inspector.get_table_names()

    if "commentary_logs" not in existing:
        op.create_table(
            "commentary_logs",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("app", sa.String(), nullable=False),
            sa.Column("page", sa.String(), nullable=False),
            sa.Column("instrument", sa.String(), nullable=True),
            sa.Column("latency_ms", sa.Float(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("commentary_preview", sa.String(), nullable=False),
            sa.Column("timestamp", sa.DateTime(), nullable=False),
        )


def downgrade() -> None:
    """Drop commentary_logs table."""
    op.drop_table("commentary_logs")
