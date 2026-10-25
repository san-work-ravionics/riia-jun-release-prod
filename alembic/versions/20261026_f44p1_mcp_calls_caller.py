"""F44 Phase 1 — mcp_calls: + transport, caller, user_id (ADR-007 §7)

Three nullable columns (rows written before P1 keep NULL) and an index on user_id (no FK —
stdio / anonymous calls have no user).

`mcp_calls` is created by the app's create_all at startup, not by an Alembic revision, so on a
fresh migration-only database the table does not exist yet: upgrade and downgrade are
inspector-guarded and do nothing then (create_all later creates the table with the columns).
Plain ALTER TABLE ADD COLUMN (no batch rebuild) — nothing is reflected, so a database without
`users` (PATTERN-015) is fine. Downgrade drops the index and the columns (SQLite >= 3.35).

Revision ID: 20261026_f44p1_mcp_calls_caller
Revises: 20261025_f43p2_rename_retire_columns_location_pk
Create Date: 2026-10-26 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261026_f44p1_mcp_calls_caller"
down_revision: Union[str, Sequence[str], None] = "20261025_f43p2_rename_retire_columns_location_pk"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "mcp_calls"
_COLUMNS = ("transport", "caller", "user_id")
_INDEX = "ix_mcp_calls_user_id"


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table() -> bool:
    return _TABLE in _inspector().get_table_names()


def _col_names() -> set[str]:
    return {c["name"] for c in _inspector().get_columns(_TABLE)}


def _index_names() -> set[str]:
    return {i["name"] for i in _inspector().get_indexes(_TABLE)}


def upgrade() -> None:
    if not _has_table():
        return
    cols = _col_names()
    for name in _COLUMNS:
        if name not in cols:
            op.add_column(_TABLE, sa.Column(name, sa.String(), nullable=True))
    if _INDEX not in _index_names():
        op.create_index(_INDEX, _TABLE, ["user_id"])


def downgrade() -> None:
    if not _has_table():
        return
    if _INDEX in _index_names():
        op.drop_index(_INDEX, table_name=_TABLE)
    cols = _col_names()
    for name in reversed(_COLUMNS):
        if name in cols:
            op.get_bind().execute(sa.text(f"ALTER TABLE {_TABLE} DROP COLUMN {name}"))
