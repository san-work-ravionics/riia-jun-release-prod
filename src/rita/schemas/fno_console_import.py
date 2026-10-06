"""Pydantic contracts for the F42 Phase 2 Console import (Workflow POST/DELETE, Experience GETs).

Dates are ISO strings (YYYY-MM-DD).  Counts are never null; dates are null when no data.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class RowErrorOut(BaseModel):
    row: Optional[int] = None
    field: Optional[str] = None
    code: str
    message: str


class PeriodOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_: Optional[str] = Field(default=None, alias="from")
    to: Optional[str] = None


class FileResult(BaseModel):
    file_name: str
    kind: Optional[Literal["tradebook", "pnl", "ledger"]] = None
    status: Literal["ok", "partial", "failed"]
    rows_parsed: int = 0
    inserted: int = 0
    updated: int = 0
    skipped_duplicates: int = 0
    rejected: int = 0
    period: PeriodOut = Field(default_factory=PeriodOut)
    warnings: list[str] = Field(default_factory=list)
    errors: list[RowErrorOut] = Field(default_factory=list)
    import_run_id: Optional[str] = None


class ImportTotals(BaseModel):
    inserted: int = 0
    updated: int = 0
    skipped_duplicates: int = 0
    rejected: int = 0
    files_failed: int = 0


class FnoImportResponse(BaseModel):
    files: list[FileResult]
    totals: ImportTotals


class PurgeCounts(BaseModel):
    personal_fno_trades: int = 0
    personal_fno_pnl_lines: int = 0
    personal_fno_pnl_charges: int = 0
    personal_fno_ledger_entries: int = 0
    personal_fno_import_runs: int = 0


class PurgeResponse(BaseModel):
    deleted: PurgeCounts


class ImportRunSummary(BaseModel):
    id: str
    kind: str
    file_name: str
    status: str
    rows_parsed: int
    rows_inserted: int
    rows_updated: int
    rows_skipped: int
    rows_rejected: int
    period_from: Optional[str] = None
    period_to: Optional[str] = None
    created_at: str


class ImportScope(BaseModel):
    underlyings: list[str]
    expiry_months: list[int]
    expiry_year: int
    date_from: str


class ImportLimits(BaseModel):
    max_file_bytes: int
    max_files: int
    max_total_bytes: int
    allowed_extensions: list[str]


class TradesCoverage(BaseModel):
    count: int = 0
    in_scope_count: int = 0
    first_date: Optional[str] = None
    last_date: Optional[str] = None
    fut_count: int = 0
    option_count: int = 0
    unparsed_count: int = 0


class PnlPeriod(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_: str = Field(alias="from")
    to: str


class PnlCoverage(BaseModel):
    line_count: int = 0
    periods: list[PnlPeriod] = Field(default_factory=list)


class LedgerCoverage(BaseModel):
    count: int = 0
    first_date: Optional[str] = None
    last_date: Optional[str] = None


class LastImports(BaseModel):
    tradebook: Optional[ImportRunSummary] = None
    pnl: Optional[ImportRunSummary] = None
    ledger: Optional[ImportRunSummary] = None


class SampleStatus(BaseModel):
    """F42 P5: state of the bundled synthetic sample data for this user (additive block)."""
    enabled: bool
    loaded: bool
    offer: bool
    can_load: bool
    unavailable_reason: Optional[str] = None
    window: Optional[PeriodOut] = None
    file_prefix: str


class SampleLoadResponse(BaseModel):
    """POST console-import/sample.  Business refusals are HTTP 200 with status 'refused'."""
    status: Literal["loaded", "already_loaded", "refused"]
    reason: Optional[Literal["has_own_data", "sample_files_missing", "sample_disabled",
                             "sample_failed"]] = None
    message: str
    window: Optional[PeriodOut] = None
    files: list[FileResult] = Field(default_factory=list)
    totals: ImportTotals = Field(default_factory=ImportTotals)


class ImportStatusResponse(BaseModel):
    has_data: bool
    scope: ImportScope
    limits: ImportLimits
    trades: TradesCoverage
    pnl: PnlCoverage
    ledger: LedgerCoverage
    last_imports: LastImports
    recent_runs: list[ImportRunSummary]
    sample: Optional[SampleStatus] = None       # F42 P5, additive


class ImportedTradesFilter(BaseModel):
    underlying: str
    include_fut: bool
    expiry_months: list[int]
    expiry_year: int
    date_from: str
    date_to: Optional[str] = None


class ImportedTradeRow(BaseModel):
    trade_date: str
    order_execution_time: Optional[str] = None
    symbol: str
    underlying: Optional[str] = None
    instrument_type: str
    strike: Optional[float] = None
    expiry_date: Optional[str] = None
    trade_type: Literal["buy", "sell"]
    quantity: int
    price: float
    trade_id: str
    order_id: str


class ImportedTradesResponse(BaseModel):
    page: int
    page_size: int
    total: int
    total_pages: int
    filter: ImportedTradesFilter
    items: list[ImportedTradeRow]
