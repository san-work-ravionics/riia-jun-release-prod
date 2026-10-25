"""F44 Phase 2 — user_portfolios: + currency, location, total_value (multi-currency portfolios)

- ``currency``    VARCHAR NOT NULL DEFAULT 'EUR' — every existing row is a legacy EUR portfolio
- ``location``    VARCHAR NULL — europe | india | us; NULL = legacy cross-geography portfolio
- ``total_value`` FLOAT NULL — in ``currency``; backfilled from ``total_value_eur``

``holdings[].cash`` needs no DDL (JSON); readers accept the legacy ``cash_eur`` key.
``total_value_eur`` is kept (deprecated, written for one release).

Inspector-guarded: a database without ``user_portfolios`` is left alone. Plain ALTER TABLE ADD
COLUMN (no batch rebuild, nothing reflected), so a database without ``users`` (PATTERN-015) is
fine. Downgrade drops the three columns (SQLite >= 3.35).

Revision ID: 20261026_f44p2_user_portfolio_currency
Revises: 20261026_f44p1_mcp_calls_caller
Create Date: 2026-10-26 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261026_f44p2_user_portfolio_currency"
down_revision: Union[str, Sequence[str], None] = "20261026_f44p1_mcp_calls_caller"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "user_portfolios"
_COLUMNS = ("currency", "location", "total_value")


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table() -> bool:
    return _TABLE in _inspector().get_table_names()


def _col_names() -> set[str]:
    return {c["name"] for c in _inspector().get_columns(_TABLE)}


def upgrade() -> None:
    if not _has_table():
        return
    cols = _col_names()
    if "currency" not in cols:
        op.add_column(_TABLE, sa.Column("currency", sa.String(), nullable=False, server_default="EUR"))
    if "location" not in cols:
        op.add_column(_TABLE, sa.Column("location", sa.String(), nullable=True))
    if "total_value" not in cols:
        op.add_column(_TABLE, sa.Column("total_value", sa.Float(), nullable=True))
    # Backfill: every pre-P2 row is a legacy EUR portfolio.
    op.get_bind().execute(sa.text(
        f"UPDATE {_TABLE} SET currency = 'EUR', total_value = total_value_eur "
        "WHERE location IS NULL AND total_value IS NULL"
    ))


def downgrade() -> None:
    if not _has_table():
        return
    cols = _col_names()
    for name in reversed(_COLUMNS):
        if name in cols:
            op.get_bind().execute(sa.text(f"ALTER TABLE {_TABLE} DROP COLUMN {name}"))
