"""F42 Phase 2 — Zerodha Console import service (Workflow tier business logic).

Everything is parsed in memory from bytes; this service never writes files and never uses
the uploaded file name as a path.  One DB commit per file; a failed file leaves an audit row
(written in its own commit after rollback).  PERSONAL DATA: logs carry counts only.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from rita.config import get_settings
from rita.models.fno_import import NO_ENTRY_DATE, FnoImportRunModel as Run
from rita.repositories.fno_import import (
    FnoImportRunRepo, FnoLedgerRepo, FnoPnlRepo, FnoTradeRepo,
)
from rita.schemas.fno_console_import import (
    FileResult, FnoImportResponse, ImportedTradeRow, ImportedTradesFilter,
    ImportedTradesResponse, ImportLimits, ImportRunSummary, ImportScope, ImportStatusResponse,
    ImportTotals, LastImports, LedgerCoverage, PeriodOut, PnlCoverage, PnlPeriod, PurgeCounts,
    PurgeResponse, RowErrorOut, TradesCoverage,
)
from rita.services.console_parsers import (
    LEDGER, PNL, TRADEBOOK, ParsedFile, ParseFailure, parse_file,
)

log = structlog.get_logger(__name__)

_NAME_OK = re.compile(r"[^\w .()\-&]")
_XLSX_MAGIC = b"PK\x03\x04"
_KINDS = (TRADEBOOK, PNL, LEDGER)


@dataclass
class UploadInput:
    name: str
    data: bytes
    too_large: bool = False


def sanitize_file_name(name: Optional[str]) -> str:
    """Display-only basename: never used as a path."""
    base = os.path.basename((name or "").replace("\\", "/")).strip()
    base = _NAME_OK.sub("_", base)[:200].strip()
    return base or "file"


def _iso(d: Optional[date]) -> Optional[str]:
    return d.isoformat() if d else None


def _summary(r: Run) -> ImportRunSummary:
    return ImportRunSummary(
        id=r.id, kind=r.kind, file_name=r.file_name, status=r.status,
        rows_parsed=r.rows_parsed or 0, rows_inserted=r.rows_inserted or 0,
        rows_updated=r.rows_updated or 0, rows_skipped=r.rows_skipped or 0,
        rows_rejected=r.rows_rejected or 0, period_from=_iso(r.period_from),
        period_to=_iso(r.period_to),
        created_at=r.created_at.isoformat() if r.created_at else "",
    )


class FnoImportService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._runs = FnoImportRunRepo(db)
        self._trades = FnoTradeRepo(db)
        self._pnl = FnoPnlRepo(db)
        self._ledger = FnoLedgerRepo(db)
        self._cfg = get_settings().trade_analysis

    # ── public ─────────────────────────────────────────────────────────────────

    def import_files(self, user_id: str, uploads: list[UploadInput]) -> FnoImportResponse:
        results = [self._import_one(user_id, u) for u in uploads]
        totals = ImportTotals(
            inserted=sum(r.inserted for r in results), updated=sum(r.updated for r in results),
            skipped_duplicates=sum(r.skipped_duplicates for r in results),
            rejected=sum(r.rejected for r in results),
            files_failed=sum(1 for r in results if r.status == "failed"),
        )
        return FnoImportResponse(files=results, totals=totals)

    def purge(self, user_id: str, kind: Optional[str] = None) -> PurgeResponse:
        """Delete the caller's rows (children first, then run rows); one commit."""
        c = PurgeCounts()
        if kind in (None, TRADEBOOK):
            c.personal_fno_trades = self._trades.purge(user_id)
        if kind in (None, PNL):
            c.personal_fno_pnl_lines, c.personal_fno_pnl_charges = self._pnl.purge(user_id)
        if kind in (None, LEDGER):
            c.personal_fno_ledger_entries = self._ledger.purge(user_id)
        c.personal_fno_import_runs = self._runs.purge(user_id, kind)
        self._db.commit()
        log.info("fno_import_purge", kind=kind or "all", runs=c.personal_fno_import_runs)
        return PurgeResponse(deleted=c)

    # ── per file ───────────────────────────────────────────────────────────────

    def _validate(self, up: UploadInput) -> None:
        ext = os.path.splitext(os.path.basename(up.name or "").lower())[1]
        if ext not in [e.lower() for e in self._cfg.import_allowed_extensions]:
            raise ParseFailure("unsupported_extension", "Only .csv and .xlsx files are supported")
        if up.too_large:
            raise ParseFailure("file_too_large",
                               f"File exceeds {self._cfg.import_max_file_bytes} bytes")
        if len(up.data) > self._cfg.import_max_file_bytes:
            raise ParseFailure("file_too_large",
                               f"File exceeds {self._cfg.import_max_file_bytes} bytes")
        if not up.data:
            raise ParseFailure("empty_file", "File is empty")
        is_zip = up.data[:4] == _XLSX_MAGIC
        if ext == ".xlsx" and not is_zip:
            raise ParseFailure("bad_file_type", "File content is not an .xlsx workbook")
        if ext == ".csv" and (is_zip or b"\x00" in up.data[:8192]):
            raise ParseFailure("bad_file_type", "File content is not text CSV")

    def _import_one(self, user_id: str, up: UploadInput) -> FileResult:
        name = sanitize_file_name(up.name)
        sha = hashlib.sha256(up.data).hexdigest()
        size = len(up.data)
        try:
            self._validate(up)
            parsed = parse_file(up.data, name, self._cfg.import_max_rows,
                                self._cfg.symbol_aliases)
        except ParseFailure as e:
            return self._fail(user_id, name, sha, size, None, e.code, e.message)

        if parsed.rows_parsed > 0 and not parsed.records and parsed.rows_rejected >= parsed.rows_parsed:
            return self._fail(user_id, name, sha, size, parsed, "all_rows_rejected",
                              "Every data row was rejected", parsed.errors)

        for attempt in (1, 2):
            try:
                result = self._persist(user_id, name, sha, size, parsed)
                self._db.commit()
                log.info("fno_import_file", kind=parsed.kind, status=result.status,
                         parsed=result.rows_parsed, inserted=result.inserted,
                         updated=result.updated, skipped=result.skipped_duplicates,
                         rejected=result.rejected, sha=sha[:8])
                return result
            except IntegrityError:
                self._db.rollback()  # concurrent double upload: retry once in dedupe mode
                log.warning("fno_import_integrity_retry", attempt=attempt, sha=sha[:8])
            except Exception as e:  # noqa: BLE001 — audit row, never a 500 for one bad file
                self._db.rollback()
                log.error("fno_import_failed", kind=parsed.kind, err=type(e).__name__, sha=sha[:8])
                return self._fail(user_id, name, sha, size, parsed, "import_failed",
                                  "Import failed; nothing was stored for this file")
        return self._fail(user_id, name, sha, size, parsed, "import_failed",
                          "Import conflicted with a concurrent upload; please retry")

    def _fail(self, user_id: str, name: str, sha: str, size: int, parsed: Optional[ParsedFile],
              code: str, message: str, errors: Optional[list] = None) -> FileResult:
        self._db.rollback()
        errs = [RowErrorOut(row=e.row, field=e.field, code=e.code, message=e.message)
                for e in (errors or [])] or [RowErrorOut(code=code, message=message)]
        kind = parsed.kind if parsed else None
        run = Run(
            user_id=user_id, kind=kind or "unknown", file_name=name, file_sha256=sha,
            file_size=size, period_from=parsed.period_from if parsed else None,
            period_to=parsed.period_to if parsed else None,
            rows_parsed=parsed.rows_parsed if parsed else 0, rows_inserted=0, rows_updated=0,
            rows_skipped=0, rows_rejected=parsed.rows_rejected if parsed else 0,
            status="failed", error_summary=f"{code}: {message}"[:1000],
        )
        self._runs.add(run)
        self._db.commit()
        log.info("fno_import_file", kind=kind or "unknown", status="failed", code=code, sha=sha[:8])
        return FileResult(
            file_name=name, kind=kind, status="failed",
            rows_parsed=run.rows_parsed, rejected=run.rows_rejected,
            period=PeriodOut(**{"from": _iso(run.period_from), "to": _iso(run.period_to)}),
            warnings=list(parsed.warnings) if parsed else [], errors=errs, import_run_id=run.id,
        )

    def _persist(self, user_id: str, name: str, sha: str, size: int,
                 parsed: ParsedFile) -> FileResult:
        run = Run(
            user_id=user_id, kind=parsed.kind, file_name=name, file_sha256=sha, file_size=size,
            period_from=parsed.period_from, period_to=parsed.period_to,
            rows_parsed=parsed.rows_parsed, rows_inserted=0, rows_updated=0, rows_skipped=0,
            rows_rejected=parsed.rows_rejected, status="ok",
        )
        self._runs.add(run)
        warnings = list(parsed.warnings)
        if parsed.kind == TRADEBOOK:
            ins, upd, skip = self._write_trades(user_id, run.id, parsed)
        elif parsed.kind == LEDGER:
            ins, upd, skip = self._write_ledger(user_id, run.id, parsed)
        else:
            ins, upd, skip = self._write_pnl(user_id, run.id, parsed, warnings)
        run.rows_inserted, run.rows_updated, run.rows_skipped = ins, upd, skip
        run.status = "partial" if parsed.rows_rejected else "ok"
        if parsed.errors:
            run.error_summary = "; ".join(
                f"row {e.row} {e.field}: {e.code}" for e in parsed.errors[:10])
        self._db.flush()
        return FileResult(
            file_name=name, kind=parsed.kind, status=run.status, rows_parsed=parsed.rows_parsed,
            inserted=ins, updated=upd, skipped_duplicates=skip, rejected=parsed.rows_rejected,
            period=PeriodOut(**{"from": _iso(parsed.period_from), "to": _iso(parsed.period_to)}),
            warnings=warnings,
            errors=[RowErrorOut(row=e.row, field=e.field, code=e.code, message=e.message)
                    for e in parsed.errors],
            import_run_id=run.id,
        )

    def _write_trades(self, uid: str, run_id: str, p: ParsedFile) -> tuple[int, int, int]:
        keys = [(r["trade_id"], r["order_id"], r["trade_date"]) for r in p.records]
        existing = self._trades.existing_keys(uid, keys)
        new = [r for r, k in zip(p.records, keys) if k not in existing]
        self._trades.insert_new(uid, run_id, new)
        return len(new), 0, len(p.records) - len(new) + p.duplicates_in_file

    def _write_ledger(self, uid: str, run_id: str, p: ParsedFile) -> tuple[int, int, int]:
        if not p.records:
            return 0, 0, 0
        counts = self._ledger.existing_counts(uid, p.period_from, p.period_to)
        # count-based rule: file has N identical rows (occurrence 0..N-1), DB has M -> insert N-M
        new = [r for r in p.records
               if r["occurrence"] >= counts.get((r["posting_date"], r["content_hash"]), 0)]
        self._ledger.insert_new(uid, run_id, new)
        return len(new), 0, len(p.records) - len(new)

    def _write_pnl(self, uid: str, run_id: str, p: ParsedFile,
                   warnings: list[str]) -> tuple[int, int, int]:
        pf, pt = p.period_from, p.period_to
        old_syms = self._pnl.line_symbols(uid, pf, pt)
        old_charges = self._pnl.charge_keys(uid, pf, pt)
        self._pnl.delete_period(uid, pf, pt)  # restated file replaces the whole period
        self._db.flush()
        charges = [{**c, "entry_date": c["entry_date"] or NO_ENTRY_DATE} for c in p.charges]
        self._pnl.insert_lines(uid, run_id, p.records)
        self._pnl.insert_charges(uid, run_id, charges)
        new_syms = {r["symbol"] for r in p.records}
        new_ckeys = {(c["section"], c["item"], c["entry_date"]) for c in charges}
        upd = len(new_syms & old_syms) + len(new_ckeys & old_charges)
        ins = len(new_syms - old_syms) + len(new_ckeys - old_charges)
        stale = len(old_syms - new_syms)
        if old_syms or old_charges:
            warnings.append(
                f"Replaced existing P&L data for this period ({stale} symbol(s) no longer present)")
        return ins, upd, p.duplicates_in_file


class FnoImportReadService:
    """Read-only (Experience tier): coverage/status and the paged imported-trades list."""

    def __init__(self, db: Session) -> None:
        self._runs = FnoImportRunRepo(db)
        self._trades = FnoTradeRepo(db)
        self._pnl = FnoPnlRepo(db)
        self._ledger = FnoLedgerRepo(db)
        self._cfg = get_settings().trade_analysis

    def _months(self, only: Optional[int] = None) -> list[str]:
        ms = [only] if only else self._cfg.expiry_months
        return [f"{self._cfg.expiry_year:04d}-{m:02d}" for m in ms]

    def status(self, user_id: str) -> ImportStatusResponse:
        cfg = self._cfg
        t = self._trades.coverage(user_id)
        p = self._pnl.coverage(user_id)
        ld = self._ledger.coverage(user_id)
        in_scope = self._trades.count_in_scope(user_id, cfg.underlyings, self._months(), cfg.date_from)
        last = {k: self._runs.last_by_kind(user_id, k) for k in _KINDS}
        return ImportStatusResponse(
            has_data=bool(t["count"] or p["line_count"] or ld["count"]),
            scope=ImportScope(underlyings=cfg.underlyings, expiry_months=cfg.expiry_months,
                              expiry_year=cfg.expiry_year, date_from=cfg.date_from.isoformat()),
            limits=ImportLimits(
                max_file_bytes=cfg.import_max_file_bytes, max_files=cfg.import_max_files,
                max_total_bytes=cfg.import_max_total_bytes,
                allowed_extensions=cfg.import_allowed_extensions),
            trades=TradesCoverage(
                count=t["count"], in_scope_count=in_scope, first_date=_iso(t["first_date"]),
                last_date=_iso(t["last_date"]), fut_count=t["fut_count"],
                option_count=t["option_count"], unparsed_count=t["unparsed_count"]),
            pnl=PnlCoverage(line_count=p["line_count"], periods=[
                PnlPeriod(**{"from": a.isoformat(), "to": b.isoformat()}) for a, b in p["periods"]]),
            ledger=LedgerCoverage(count=ld["count"], first_date=_iso(ld["first_date"]),
                                  last_date=_iso(ld["last_date"])),
            last_imports=LastImports(**{k: (_summary(v) if v else None) for k, v in last.items()}),
            recent_runs=[_summary(r) for r in self._runs.recent(user_id, 20)],
        )

    def trades(self, user_id: str, underlying: str, include_fut: bool,
               expiry_month: Optional[int], date_from: Optional[date], date_to: Optional[date],
               side: Optional[str], sort: str, page: int, page_size: int) -> ImportedTradesResponse:
        cfg = self._cfg
        eff_from = date_from or cfg.date_from
        in_set = expiry_month is None or expiry_month in cfg.expiry_months
        months = self._months(expiry_month) if in_set else []
        total, rows = (0, [])
        if months:
            total, rows = self._trades.page(
                user_id, cfg.underlyings, months, eff_from, date_to, include_fut,
                None if underlying == "ALL" else underlying, side, sort == "trade_date_desc",
                page, page_size)
        items: list[Any] = [ImportedTradeRow(
            trade_date=r.trade_date.isoformat(),
            order_execution_time=r.order_execution_time.isoformat() if r.order_execution_time else None,
            symbol=r.symbol, underlying=r.underlying, instrument_type=r.instrument_type,
            strike=r.strike, expiry_date=_iso(r.expiry_date or r.opt_expiry),
            trade_type=r.trade_type, quantity=r.quantity, price=r.price,
            trade_id=r.trade_id, order_id=r.order_id) for r in rows]
        return ImportedTradesResponse(
            page=page, page_size=page_size, total=total,
            total_pages=max(1, math.ceil(total / page_size)),
            filter=ImportedTradesFilter(
                underlying=underlying, include_fut=include_fut,
                expiry_months=[expiry_month] if expiry_month else cfg.expiry_months,
                expiry_year=cfg.expiry_year, date_from=eff_from.isoformat(),
                date_to=_iso(date_to)),
            items=items,
        )
