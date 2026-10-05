"""F42 Phase 2: personal_fno_* Console-import tables

Revision ID: 20261006_f42_console_import
Revises: 20261005_f40_hedge_plan_history
Create Date: 2026-10-06 00:00:00.000000

All five tables hold PERSONAL financial data (hence the personal_ prefix).
Idempotent: lifespan create_all may already have created the tables, so each table is
inspector-guarded (its indexes/constraints are created with it).
"""
from typing import Union, Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20261006_f42_console_import"
down_revision: Union[str, Sequence[str], None] = "20261005_f40_hedge_plan_history"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RUNS = "personal_fno_import_runs"
_TRADES = "personal_fno_trades"
_LINES = "personal_fno_pnl_lines"
_CHARGES = "personal_fno_pnl_charges"
_LEDGER = "personal_fno_ledger_entries"
_DEPENDENT = [_TRADES, _LINES, _CHARGES, _LEDGER]


def _money() -> sa.Numeric:
    return sa.Numeric(18, 4, asdecimal=False)


def _now() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                     server_default=sa.func.now())


def _run_fk() -> sa.Column:
    return sa.Column("import_run_id", sa.String(), sa.ForeignKey(f"{_RUNS}.id"), nullable=False)


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())

    if _RUNS not in existing:
        op.create_table(
            _RUNS,
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("file_name", sa.String(), nullable=False),
            sa.Column("file_sha256", sa.String(64), nullable=False),
            sa.Column("file_size", sa.Integer(), nullable=False),
            sa.Column("period_from", sa.Date(), nullable=True),
            sa.Column("period_to", sa.Date(), nullable=True),
            sa.Column("rows_parsed", sa.Integer(), nullable=False),
            sa.Column("rows_inserted", sa.Integer(), nullable=False),
            sa.Column("rows_updated", sa.Integer(), nullable=False),
            sa.Column("rows_skipped", sa.Integer(), nullable=False),
            sa.Column("rows_rejected", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("error_summary", sa.Text(), nullable=True),
            _now(),
        )
        op.create_index("ix_personal_fno_import_runs_user_kind_created", _RUNS,
                        ["user_id", "kind", "created_at"])
        op.create_index("ix_personal_fno_import_runs_user_sha", _RUNS, ["user_id", "file_sha256"])

    if _TRADES not in existing:
        op.create_table(
            _TRADES,
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("user_id", sa.String(), nullable=False),
            _run_fk(),
            sa.Column("symbol", sa.String(), nullable=False),
            sa.Column("isin", sa.String(), nullable=True),
            sa.Column("trade_date", sa.Date(), nullable=False),
            sa.Column("exchange", sa.String(), nullable=True),
            sa.Column("segment", sa.String(), nullable=True),
            sa.Column("series", sa.String(), nullable=True),
            sa.Column("trade_type", sa.String(), nullable=False),
            sa.Column("auction", sa.String(), nullable=True),
            sa.Column("quantity", sa.Integer(), nullable=False),
            sa.Column("price", _money(), nullable=False),
            sa.Column("trade_id", sa.String(), nullable=False),
            sa.Column("order_id", sa.String(), nullable=False),
            sa.Column("order_execution_time", sa.DateTime(), nullable=True),
            sa.Column("expiry_date", sa.Date(), nullable=True),
            sa.Column("underlying", sa.String(), nullable=True),
            sa.Column("instrument_type", sa.String(), nullable=False),
            sa.Column("strike", _money(), nullable=True),
            sa.Column("opt_expiry", sa.Date(), nullable=True),
            sa.Column("expiry_ym", sa.String(7), nullable=True),
            sa.Column("parse_status", sa.String(), nullable=False),
            _now(),
            sa.UniqueConstraint("user_id", "trade_id", "order_id", "trade_date",
                                name="uq_personal_fno_trades_natural"),
        )
        op.create_index("ix_personal_fno_trades_user_date", _TRADES, ["user_id", "trade_date"])
        op.create_index("ix_personal_fno_trades_user_und_exp", _TRADES,
                        ["user_id", "underlying", "opt_expiry"])
        op.create_index("ix_personal_fno_trades_user_type", _TRADES, ["user_id", "instrument_type"])
        op.create_index("ix_personal_fno_trades_user_ym", _TRADES, ["user_id", "expiry_ym"])

    if _LINES not in existing:
        op.create_table(
            _LINES,
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("user_id", sa.String(), nullable=False),
            _run_fk(),
            sa.Column("symbol", sa.String(), nullable=False),
            sa.Column("isin", sa.String(), nullable=True),
            sa.Column("period_from", sa.Date(), nullable=False),
            sa.Column("period_to", sa.Date(), nullable=False),
            sa.Column("quantity", sa.Integer(), nullable=True),
            sa.Column("buy_value", _money(), nullable=True),
            sa.Column("sell_value", _money(), nullable=True),
            sa.Column("realized_pnl", _money(), nullable=True),
            sa.Column("realized_pnl_pct", _money(), nullable=True),
            sa.Column("prev_close_price", _money(), nullable=True),
            sa.Column("open_quantity", sa.Integer(), nullable=True),
            sa.Column("open_quantity_type", sa.String(), nullable=True),
            sa.Column("open_value", _money(), nullable=True),
            sa.Column("unrealized_pnl", _money(), nullable=True),
            sa.Column("unrealized_pnl_pct", _money(), nullable=True),
            sa.Column("underlying", sa.String(), nullable=True),
            sa.Column("instrument_type", sa.String(), nullable=False),
            sa.Column("strike", _money(), nullable=True),
            sa.Column("opt_expiry", sa.Date(), nullable=True),
            sa.Column("expiry_ym", sa.String(7), nullable=True),
            _now(),
            sa.UniqueConstraint("user_id", "symbol", "period_from", "period_to",
                                name="uq_personal_fno_pnl_lines"),
        )
        op.create_index("ix_personal_fno_pnl_lines_user_period", _LINES,
                        ["user_id", "period_from", "period_to"])

    if _CHARGES not in existing:
        op.create_table(
            _CHARGES,
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("user_id", sa.String(), nullable=False),
            _run_fk(),
            sa.Column("period_from", sa.Date(), nullable=False),
            sa.Column("period_to", sa.Date(), nullable=False),
            sa.Column("section", sa.String(), nullable=False),
            sa.Column("item", sa.String(), nullable=False),
            sa.Column("entry_date", sa.Date(), nullable=False),
            sa.Column("amount", _money(), nullable=False),
            _now(),
            sa.UniqueConstraint("user_id", "section", "item", "period_from", "period_to",
                                "entry_date", name="uq_personal_fno_pnl_charges"),
        )
        op.create_index("ix_personal_fno_pnl_charges_user_period", _CHARGES,
                        ["user_id", "period_from", "period_to"])

    if _LEDGER not in existing:
        op.create_table(
            _LEDGER,
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("user_id", sa.String(), nullable=False),
            _run_fk(),
            sa.Column("particulars", sa.Text(), nullable=False),
            sa.Column("posting_date", sa.Date(), nullable=False),
            sa.Column("cost_center", sa.String(), nullable=True),
            sa.Column("voucher_type", sa.String(), nullable=True),
            sa.Column("debit", _money(), nullable=False),
            sa.Column("credit", _money(), nullable=False),
            sa.Column("net_balance", _money(), nullable=True),
            sa.Column("content_hash", sa.String(64), nullable=False),
            sa.Column("occurrence", sa.Integer(), nullable=False),
            _now(),
            sa.UniqueConstraint("user_id", "posting_date", "content_hash", "occurrence",
                                name="uq_personal_fno_ledger"),
        )
        op.create_index("ix_personal_fno_ledger_entries_user_date", _LEDGER,
                        ["user_id", "posting_date"])
        op.create_index("ix_personal_fno_ledger_entries_user_voucher", _LEDGER,
                        ["user_id", "voucher_type"])


def downgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for table in _DEPENDENT + [_RUNS]:  # dependents first (FK order)
        if table in existing:
            op.drop_table(table)
