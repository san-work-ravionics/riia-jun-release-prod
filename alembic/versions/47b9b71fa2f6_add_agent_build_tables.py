"""add agent_build_runs and agent_build_agents tables

Revision ID: 47b9b71fa2f6
Revises: fb6dd6e7e232
Create Date: 2026-05-07 07:17:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '47b9b71fa2f6'
down_revision: Union[str, Sequence[str], None] = 'fb6dd6e7e232'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing = inspector.get_table_names()

    if "agent_build_runs" not in existing:
        op.create_table(
            "agent_build_runs",
            sa.Column("run_id", sa.String(), primary_key=True),
            sa.Column("app", sa.String(), nullable=False),
            sa.Column("request", sa.Text(), nullable=True),
            sa.Column("skill_file", sa.String(), nullable=True),
            sa.Column("overall_status", sa.String(), nullable=False),
            sa.Column("total_tokens_estimated", sa.Integer(), nullable=True),
            sa.Column("duration_minutes", sa.Float(), nullable=True),
            sa.Column("branch", sa.String(), nullable=True),
            sa.Column("merge_status", sa.String(), nullable=True),
            sa.Column("merge_commit", sa.String(), nullable=True),
            sa.Column("recorded_at", sa.DateTime(), nullable=False),
        )

    if "agent_build_agents" not in existing:
        op.create_table(
            "agent_build_agents",
            sa.Column("agent_id", sa.String(), primary_key=True),
            sa.Column("run_id", sa.String(), sa.ForeignKey("agent_build_runs.run_id"), nullable=False),
            sa.Column("role", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("steps_required", sa.Integer(), nullable=True),
            sa.Column("steps_completed", sa.Integer(), nullable=True),
            sa.Column("adherence_score", sa.Float(), nullable=True),
            sa.Column("token_estimate", sa.Integer(), nullable=True),
            sa.Column("grounding_checks", sa.JSON(), nullable=True),
            sa.Column("failure_modes", sa.JSON(), nullable=True),
            sa.Column("recorded_at", sa.DateTime(), nullable=False),
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("agent_build_agents")
    op.drop_table("agent_build_runs")
