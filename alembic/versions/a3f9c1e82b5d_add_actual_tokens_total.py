"""add actual_tokens_total to agent_build_agents

Revision ID: a3f9c1e82b5d
Revises: 47b9b71fa2f6
Create Date: 2026-05-15 08:59:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3f9c1e82b5d'
down_revision: Union[str, Sequence[str], None] = '47b9b71fa2f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add actual_tokens_total column to agent_build_agents if not already present."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_columns = [col["name"] for col in inspector.get_columns("agent_build_agents")]
    if "actual_tokens_total" not in existing_columns:
        op.add_column(
            "agent_build_agents",
            sa.Column("actual_tokens_total", sa.Integer(), nullable=True),
        )


def downgrade() -> None:
    """Remove actual_tokens_total column from agent_build_agents."""
    op.drop_column("agent_build_agents", "actual_tokens_total")
