"""add agent_performance table

Revision ID: 993fec6a43bd
Revises: 20260611_seed_demo_user
Create Date: 2026-06-26 20:15:38.115056

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '993fec6a43bd'
down_revision: Union[str, Sequence[str], None] = '20260611_seed_demo_user'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema — create agent_performance table only (Feature 32)."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing = inspector.get_table_names()

    if "agent_performance" not in existing:
        op.create_table(
            "agent_performance",
            sa.Column("perf_id", sa.String(), nullable=False),
            sa.Column("agent_name", sa.String(), nullable=False),
            sa.Column("intent", sa.String(), nullable=False),
            sa.Column("recommendation", sa.String(), nullable=True),
            sa.Column("outcome_status", sa.String(), nullable=True),
            sa.Column("training_run_id", sa.String(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("perf_id"),
        )
        op.create_index(
            "ix_agent_performance_agent_created",
            "agent_performance",
            ["agent_name", "created_at"],
            unique=False,
        )


def downgrade() -> None:
    """Downgrade schema — drop agent_performance table only."""
    op.drop_index("ix_agent_performance_agent_created", table_name="agent_performance")
    op.drop_table("agent_performance")
