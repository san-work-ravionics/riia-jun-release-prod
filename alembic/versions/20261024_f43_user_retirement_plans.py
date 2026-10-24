"""F43 Phase 1 — add user_retirement_plans table

One row per user with the "What I Need" plan inputs (JSON), restored on page open.

Note (design review A1): user_id is an FK to users.id. SQLite does not enforce it by
default, so the synthetic development user ``rita-dev`` can save without a users row.
On PostgreSQL the FK is enforced: a ``users`` row with id ``rita-dev`` must exist
before a dev-mode save (see Spec_DB.md).

Revision ID: 20261024_f43_user_retirement_plans
Revises: 20261006_f42_console_import
Create Date: 2026-10-24 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20261024_f43_user_retirement_plans"
down_revision: Union[str, Sequence[str], None] = "20261006_f42_console_import"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "user_retirement_plans" not in inspector.get_table_names():
        op.create_table(
            "user_retirement_plans",
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("inputs", sa.JSON(), nullable=False),
            sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("location", sa.String(), nullable=False, server_default="europe"),
            sa.Column("created_at", sa.DateTime(), nullable=True, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("user_id"),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "user_retirement_plans" in inspector.get_table_names():
        op.drop_table("user_retirement_plans")
