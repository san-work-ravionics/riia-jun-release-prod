"""F43 Phase 2 — rename corpus/pot columns; per-location plan PK

1. user_retirement_plan_history: corpus_at_retire → portfolio_at_retire,
   corpus_out_age → portfolio_out_age
2. user_retirement_plans: change PK from (user_id) to (user_id, location)
   so each user can save one plan per location (Europe, India, US).

Reversible. Downgrade collapses per-location rows: keeps the most-recently
updated row per user (arbitrary when updated_at ties).

Revision ID: 20261025_f43p2_rename_retire_columns_location_pk
Revises: 20261024_f43_retirement_plan_history
Create Date: 2026-10-25 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261025_f43p2_rename_retire_columns_location_pk"
down_revision: Union[str, Sequence[str], None] = "20261024_f43_retirement_plan_history"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_HIST = "user_retirement_plan_history"
_PLAN = "user_retirement_plans"


def _col_names(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    # ── 1. Rename history columns ────────────────────────────────────────────
    cols = _col_names(_HIST)
    renames = []
    if "corpus_at_retire" in cols:
        renames.append(("corpus_at_retire", "portfolio_at_retire", sa.Float()))
    if "corpus_out_age" in cols:
        renames.append(("corpus_out_age", "portfolio_out_age", sa.Integer()))
    if renames:
        with op.batch_alter_table(_HIST) as batch_op:
            for old, new, typ in renames:
                batch_op.alter_column(old, new_column_name=new, existing_type=typ, nullable=True)

    # ── 2. Change user_retirement_plans PK to (user_id, location) ───────────
    plan_cols = _col_names(_PLAN)
    if "location" in plan_cols:
        with op.batch_alter_table(_PLAN, recreate="always") as batch_op:
            batch_op.create_primary_key("pk_user_retirement_plans", ["user_id", "location"])


def downgrade() -> None:
    # ── 2. Revert PK to user_id only (keep one row per user) ────────────────
    bind = op.get_bind()
    plan_cols = _col_names(_PLAN)
    if "location" in plan_cols:
        # Keep the most-recently-updated row per user before collapsing PK
        bind.execute(sa.text(
            f"DELETE FROM {_PLAN} WHERE rowid NOT IN ("
            f"  SELECT MAX(rowid) FROM {_PLAN} GROUP BY user_id)"
        ))
        with op.batch_alter_table(_PLAN, recreate="always") as batch_op:
            batch_op.create_primary_key("pk_user_retirement_plans", ["user_id"])

    # ── 1. Revert history renames ────────────────────────────────────────────
    cols = _col_names(_HIST)
    renames = []
    if "portfolio_at_retire" in cols:
        renames.append(("portfolio_at_retire", "corpus_at_retire", sa.Float()))
    if "portfolio_out_age" in cols:
        renames.append(("portfolio_out_age", "corpus_out_age", sa.Integer()))
    if renames:
        with op.batch_alter_table(_HIST) as batch_op:
            for old, new, typ in renames:
                batch_op.alter_column(old, new_column_name=new, existing_type=typ, nullable=True)
