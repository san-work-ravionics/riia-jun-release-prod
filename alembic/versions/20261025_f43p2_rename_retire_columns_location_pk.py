"""F43 Phase 2 — rename corpus/pot columns; per-location plan PK

1. user_retirement_plan_history: corpus_at_retire → portfolio_at_retire,
   corpus_out_age → portfolio_out_age
2. user_retirement_plans: change PK from (user_id) to (user_id, location)
   so each user can save one plan per location (Europe, India, US).

Reversible. Downgrade collapses per-location rows: keeps the most-recently
updated row per user (arbitrary when updated_at ties).

Both tables have FKs to `users`, which is created at app startup by create_all
(not via Alembic). batch_alter_table reflects FK targets, which fails when
`users` is absent in migration-only test databases. All DDL here uses raw SQL
to bypass Alembic's reflection entirely.

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
_PLAN_TMP = "user_retirement_plans_tmp"


def _col_names(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()

    # ── 1. Rename history columns (SQLite 3.25+ RENAME COLUMN; no table rebuild) ──
    cols = _col_names(_HIST)
    if "corpus_at_retire" in cols:
        bind.execute(sa.text(
            f"ALTER TABLE {_HIST} RENAME COLUMN corpus_at_retire TO portfolio_at_retire"
        ))
    if "corpus_out_age" in cols:
        bind.execute(sa.text(
            f"ALTER TABLE {_HIST} RENAME COLUMN corpus_out_age TO portfolio_out_age"
        ))

    # ── 2. Change user_retirement_plans PK to (user_id, location) ───────────
    # Rebuild the table to change the PK; raw SQL avoids reflecting `users` (FK parent).
    plan_cols = _col_names(_PLAN)
    if "location" in plan_cols:
        bind.execute(sa.text(f"""
            CREATE TABLE {_PLAN_TMP} (
                user_id TEXT NOT NULL,
                inputs JSON NOT NULL,
                schema_version INTEGER NOT NULL DEFAULT 1,
                location TEXT NOT NULL DEFAULT 'europe',
                created_at DATETIME,
                updated_at DATETIME NOT NULL,
                PRIMARY KEY (user_id, location)
            )
        """))
        bind.execute(sa.text(f"""
            INSERT INTO {_PLAN_TMP} (user_id, inputs, schema_version, location, created_at, updated_at)
            SELECT user_id, inputs, schema_version, location, created_at, updated_at
            FROM {_PLAN}
        """))
        bind.execute(sa.text(f"DROP TABLE {_PLAN}"))
        bind.execute(sa.text(f"ALTER TABLE {_PLAN_TMP} RENAME TO {_PLAN}"))


def downgrade() -> None:
    bind = op.get_bind()

    # ── 2. Revert PK to user_id only (keep one row per user) ────────────────
    plan_cols = _col_names(_PLAN)
    if "location" in plan_cols:
        # Keep the most-recently-updated row per user before collapsing PK
        bind.execute(sa.text(f"""
            DELETE FROM {_PLAN} WHERE rowid NOT IN (
                SELECT MAX(rowid) FROM {_PLAN} GROUP BY user_id
            )
        """))
        bind.execute(sa.text(f"""
            CREATE TABLE {_PLAN_TMP} (
                user_id TEXT NOT NULL,
                inputs JSON NOT NULL,
                schema_version INTEGER NOT NULL DEFAULT 1,
                location TEXT NOT NULL DEFAULT 'europe',
                created_at DATETIME,
                updated_at DATETIME NOT NULL,
                PRIMARY KEY (user_id)
            )
        """))
        bind.execute(sa.text(f"""
            INSERT INTO {_PLAN_TMP} (user_id, inputs, schema_version, location, created_at, updated_at)
            SELECT user_id, inputs, schema_version, location, created_at, updated_at
            FROM {_PLAN}
        """))
        bind.execute(sa.text(f"DROP TABLE {_PLAN}"))
        bind.execute(sa.text(f"ALTER TABLE {_PLAN_TMP} RENAME TO {_PLAN}"))

    # ── 1. Revert history renames ────────────────────────────────────────────
    cols = _col_names(_HIST)
    if "portfolio_at_retire" in cols:
        bind.execute(sa.text(
            f"ALTER TABLE {_HIST} RENAME COLUMN portfolio_at_retire TO corpus_at_retire"
        ))
    if "portfolio_out_age" in cols:
        bind.execute(sa.text(
            f"ALTER TABLE {_HIST} RENAME COLUMN portfolio_out_age TO corpus_out_age"
        ))
