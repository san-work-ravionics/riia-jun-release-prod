"""ORM models for the F42 Phase 2 Zerodha Console import.

All five tables hold PERSONAL financial data, keyed by ``user_id`` (a plain String, no FK:
the dev user is synthetic).  The ``personal_`` table prefix is a deliberate marker: these
tables must be excluded from seeds, fixtures, demo-data / backup-sharing scripts, exports,
LLM prompts and logs.

Conventions: String uuid4 primary keys; money as Numeric(18,4, asdecimal=False) (floats on
SQLite, portable to Postgres); ``import_run_id`` is the FK to the run that first inserted
the row.  Repositories never commit; FnoImportService commits once per file.

fno_pnl_charges.entry_date uses the sentinel 1970-01-01 instead of NULL so the unique key
works on Postgres (NULLs are distinct there).
"""
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    Column, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text,
    UniqueConstraint, func,
)

from rita.database import Base

NO_ENTRY_DATE = date(1970, 1, 1)


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _money() -> Numeric:
    return Numeric(18, 4, asdecimal=False)


# PERSONAL DATA — personal_ prefix: never include in seeds, fixtures, exports, LLM prompts or logs
class FnoImportRunModel(Base):
    """Audit row, one per uploaded file (also for failed files)."""

    __tablename__ = "personal_fno_import_runs"

    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, nullable=False)
    kind = Column(String, nullable=False)  # tradebook | pnl | ledger | unknown (failed detection)
    file_name = Column(String, nullable=False)  # sanitised basename, display only
    file_sha256 = Column(String(64), nullable=False)
    file_size = Column(Integer, nullable=False)
    period_from = Column(Date, nullable=True)
    period_to = Column(Date, nullable=True)
    rows_parsed = Column(Integer, nullable=False, default=0)
    rows_inserted = Column(Integer, nullable=False, default=0)
    rows_updated = Column(Integer, nullable=False, default=0)
    rows_skipped = Column(Integer, nullable=False, default=0)
    rows_rejected = Column(Integer, nullable=False, default=0)
    status = Column(String, nullable=False)  # ok | partial | failed
    error_summary = Column(Text, nullable=True)  # codes/messages only, never row contents
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now,
                        server_default=func.now())

    __table_args__ = (
        Index("ix_personal_fno_import_runs_user_kind_created", "user_id", "kind", "created_at"),
        Index("ix_personal_fno_import_runs_user_sha", "user_id", "file_sha256"),
    )


# PERSONAL DATA — personal_ prefix: never include in seeds, fixtures, exports, LLM prompts or logs
class FnoTradeModel(Base):
    """Tradebook row.  Natural key (user_id, trade_id, order_id, trade_date)."""

    __tablename__ = "personal_fno_trades"

    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, nullable=False)
    import_run_id = Column(String, ForeignKey("personal_fno_import_runs.id"), nullable=False)
    symbol = Column(String, nullable=False)
    isin = Column(String, nullable=True)
    trade_date = Column(Date, nullable=False)
    exchange = Column(String, nullable=True)
    segment = Column(String, nullable=True)
    series = Column(String, nullable=True)
    trade_type = Column(String, nullable=False)  # buy | sell
    auction = Column(String, nullable=True)
    quantity = Column(Integer, nullable=False)  # positive; sign carried by trade_type
    price = Column(_money(), nullable=False)
    trade_id = Column(String, nullable=False)
    order_id = Column(String, nullable=False)
    order_execution_time = Column(DateTime, nullable=True)  # naive, treated as IST
    expiry_date = Column(Date, nullable=True)
    underlying = Column(String, nullable=True)
    instrument_type = Column(String, nullable=False, default="UNKNOWN")  # CE | PE | FUT | UNKNOWN
    strike = Column(_money(), nullable=True)
    opt_expiry = Column(Date, nullable=True)
    expiry_ym = Column(String(7), nullable=True)  # YYYY-MM
    parse_status = Column(String, nullable=False, default="ok")  # ok | fallback | unparsed
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now,
                        server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "trade_id", "order_id", "trade_date",
                         name="uq_personal_fno_trades_natural"),
        Index("ix_personal_fno_trades_user_date", "user_id", "trade_date"),
        Index("ix_personal_fno_trades_user_und_exp", "user_id", "underlying", "opt_expiry"),
        Index("ix_personal_fno_trades_user_type", "user_id", "instrument_type"),
        Index("ix_personal_fno_trades_user_ym", "user_id", "expiry_ym"),
    )


# PERSONAL DATA — personal_ prefix: never include in seeds, fixtures, exports, LLM prompts or logs
class FnoPnlLineModel(Base):
    """Per-symbol P&L aggregate over the file's period.  Same period re-import REPLACES."""

    __tablename__ = "personal_fno_pnl_lines"

    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, nullable=False)
    import_run_id = Column(String, ForeignKey("personal_fno_import_runs.id"), nullable=False)
    symbol = Column(String, nullable=False)
    isin = Column(String, nullable=True)
    period_from = Column(Date, nullable=False)
    period_to = Column(Date, nullable=False)
    quantity = Column(Integer, nullable=True)
    buy_value = Column(_money(), nullable=True)
    sell_value = Column(_money(), nullable=True)
    realized_pnl = Column(_money(), nullable=True)
    realized_pnl_pct = Column(_money(), nullable=True)
    prev_close_price = Column(_money(), nullable=True)
    open_quantity = Column(Integer, nullable=True)
    open_quantity_type = Column(String, nullable=True)
    open_value = Column(_money(), nullable=True)
    unrealized_pnl = Column(_money(), nullable=True)
    unrealized_pnl_pct = Column(_money(), nullable=True)
    underlying = Column(String, nullable=True)
    instrument_type = Column(String, nullable=False, default="UNKNOWN")
    strike = Column(_money(), nullable=True)
    opt_expiry = Column(Date, nullable=True)
    expiry_ym = Column(String(7), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now,
                        server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "symbol", "period_from", "period_to",
                         name="uq_personal_fno_pnl_lines"),
        Index("ix_personal_fno_pnl_lines_user_period", "user_id", "period_from", "period_to"),
    )


# PERSONAL DATA — personal_ prefix: never include in seeds, fixtures, exports, LLM prompts or logs
class FnoPnlChargeModel(Base):
    """Long-format P&L summary / charges / other-debits-credits items for a period."""

    __tablename__ = "personal_fno_pnl_charges"

    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, nullable=False)
    import_run_id = Column(String, ForeignKey("personal_fno_import_runs.id"), nullable=False)
    period_from = Column(Date, nullable=False)
    period_to = Column(Date, nullable=False)
    section = Column(String, nullable=False)  # summary | charges | other_dc
    item = Column(String, nullable=False)
    entry_date = Column(Date, nullable=False, default=NO_ENTRY_DATE)  # sentinel 1970-01-01
    amount = Column(_money(), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now,
                        server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "section", "item", "period_from", "period_to", "entry_date",
                         name="uq_personal_fno_pnl_charges"),
        Index("ix_personal_fno_pnl_charges_user_period", "user_id", "period_from", "period_to"),
    )


# PERSONAL DATA — personal_ prefix: never include in seeds, fixtures, exports, LLM prompts or logs
class FnoLedgerEntryModel(Base):
    """Ledger row.  Dedupe: (user_id, posting_date, content_hash, occurrence), count-based."""

    __tablename__ = "personal_fno_ledger_entries"

    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, nullable=False)
    import_run_id = Column(String, ForeignKey("personal_fno_import_runs.id"), nullable=False)
    particulars = Column(Text, nullable=False)
    posting_date = Column(Date, nullable=False)
    cost_center = Column(String, nullable=True)
    voucher_type = Column(String, nullable=True)
    debit = Column(_money(), nullable=False, default=0)
    credit = Column(_money(), nullable=False, default=0)
    net_balance = Column(_money(), nullable=True)
    content_hash = Column(String(64), nullable=False)
    occurrence = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now,
                        server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "posting_date", "content_hash", "occurrence",
                         name="uq_personal_fno_ledger"),
        Index("ix_personal_fno_ledger_entries_user_date", "user_id", "posting_date"),
        Index("ix_personal_fno_ledger_entries_user_voucher", "user_id", "voucher_type"),
    )
