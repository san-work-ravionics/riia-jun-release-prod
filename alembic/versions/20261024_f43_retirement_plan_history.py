"""F43 Phase 1b — add user_retirement_plan_history table

Append-only history: one row per saved "What I Need" plan, with the plan inputs
(JSON) and the key figures shown at save time. user_id is an FK to users.id
(real users in production). SQLite does not enforce it, so the synthetic dev user
``rita-dev`` can save; on PostgreSQL a users row for it is needed (see Spec_DB.md).

Revision ID: 20261024_f43_retirement_plan_history
Revises: 20261024_f43_user_retirement_plans
Create Date: 2026-10-24 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20261024_f43_retirement_plan_history"
down_revision: Union[str, Sequence[str], None] = "20261024_f43_user_retirement_plans"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "user_retirement_plan_history"
_INDEX = "ix_user_retirement_plan_history_user_saved"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        op.create_table(
            _TABLE,
            sa.Column("history_id", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("saved_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("inputs", sa.JSON(), nullable=False),
            sa.Column("location", sa.String(), nullable=False),
            sa.Column("retire_age", sa.Integer(), nullable=False),
            sa.Column("plan_until", sa.Integer(), nullable=False),
            sa.Column("need_at_retire", sa.Float(), nullable=False),
            sa.Column("monthly_at_retire", sa.Float(), nullable=False),
            sa.Column("corpus_at_retire", sa.Float(), nullable=False),
            sa.Column("sustainable_until", sa.Integer(), nullable=True),
            sa.Column("corpus_out_age", sa.Integer(), nullable=True),
            sa.Column("schema_version", sa.Integer(), nullable=False),
            sa.Column("app_version", sa.String(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("history_id"),
        )
    if _INDEX not in {ix["name"] for ix in sa.inspect(op.get_bind()).get_indexes(_TABLE)}:
        op.create_index(_INDEX, _TABLE, ["user_id", "saved_at"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE in inspector.get_table_names():
        if _INDEX in {ix["name"] for ix in inspector.get_indexes(_TABLE)}:
            op.drop_index(_INDEX, table_name=_TABLE)
        op.drop_table(_TABLE)
