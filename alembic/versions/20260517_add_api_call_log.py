"""add api_call_log table

Revision ID: e9f3b2c41a07
Revises: c7e2a4f81d39
Create Date: 2026-05-17

"""
from alembic import op
import sqlalchemy as sa

revision = 'e9f3b2c41a07'
down_revision = 'c7e2a4f81d39'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'api_call_log' not in inspector.get_table_names():
        op.create_table(
            'api_call_log',
            sa.Column('call_id', sa.String(), primary_key=True),
            sa.Column('path', sa.String(), nullable=False),
            sa.Column('method', sa.String(), nullable=False),
            sa.Column('status_code', sa.Integer(), nullable=True),
            sa.Column('duration_ms', sa.Float(), nullable=True),
            sa.Column('called_at', sa.DateTime(), nullable=False),
            sa.Column('recorded_at', sa.DateTime(), nullable=False),
        )


def downgrade():
    op.drop_table('api_call_log')
