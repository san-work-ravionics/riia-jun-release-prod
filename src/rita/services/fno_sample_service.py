"""F42 P5 - "Load sample data": imports the bundled SYNTHETIC Console-style files for one user.

Workflow tier (ADR-001).  The three CSV files are static, committed and shipped by the deploy
rsync; this service receives their bytes from ``FnoSampleFileRepo`` (injected) and passes them to
the existing ``FnoImportService.import_files`` under the caller's user id.  It performs NO file
I/O itself (ADR-002), generates nothing, and never merges into real data.

Concurrency: a fixed array of 64 striped in-process locks keyed by user id serialises two loads
for one user.  Correct under the verified single-process deployment (Dockerfile CMD has no
``--workers``); natural-key dedupe protects the tradebook only, the ledger rule is count-based, so
scaling to more than one worker needs a DB-level guard first (see SPEC_Prod_Deploy.md).

PERSONAL DATA: logs carry counts, reason codes and file NAMES only.
"""
from __future__ import annotations

import threading
import zlib
from typing import Optional

import structlog
from sqlalchemy.orm import Session

from rita.config import get_settings
from rita.repositories.fno_import import FnoImportRunRepo, FnoLedgerRepo, FnoPnlRepo, FnoTradeRepo
from rita.repositories.fno_sample_files import FnoSampleFileRepo, SampleFilesMissing
from rita.schemas.fno_console_import import FnoImportResponse, PeriodOut, SampleLoadResponse
from rita.services.fno_import_service import FnoImportService, UploadInput, is_sample_data

log = structlog.get_logger(__name__)

_N_LOCKS = 64
_LOCKS = [threading.Lock() for _ in range(_N_LOCKS)]

_MSG = {
    "loaded": "Sample data loaded. It is synthetic and clearly labelled; remove it any time.",
    "already_loaded": "Sample data is already loaded.",
    "has_own_data": "You already have imported data. Sample data is only offered to accounts with no data.",
    "sample_files_missing": "Sample data is not available on this server.",
    "sample_disabled": "Sample data is disabled on this server.",
    "sample_failed": "Sample data could not be loaded; nothing was kept. Please try again later.",
    "sample_failed_cleanup": ("Sample load failed and cleanup was incomplete; "
                              "use 'Delete my imported data'."),
}


def lock_for(user_id: str) -> threading.Lock:
    """Bounded registry: striped by a stable hash of the user id."""
    return _LOCKS[zlib.crc32(user_id.encode("utf-8")) % _N_LOCKS]


class FnoSampleService:
    def __init__(self, db: Session, files: FnoSampleFileRepo) -> None:
        self._db = db
        self._files = files
        self._cfg = get_settings().trade_analysis
        self._runs = FnoImportRunRepo(db)
        self._trades = FnoTradeRepo(db)
        self._pnl = FnoPnlRepo(db)
        self._ledger = FnoLedgerRepo(db)
        self._importer = FnoImportService(db)

    @classmethod
    def from_settings(cls, db: Session) -> "FnoSampleService":
        """Request-time factory: the file repository points at ``data.input_dir/<sample_dir>``."""
        return cls(db, FnoSampleFileRepo.from_settings())

    # ── public ─────────────────────────────────────────────────────────────────

    def load(self, user_id: str) -> SampleLoadResponse:
        if not self._cfg.sample_enabled:
            return self._refused("sample_disabled")
        with lock_for(user_id):
            self._db.rollback()                    # fresh view of the data inside the lock
            if self._has_data(user_id):
                if is_sample_data(self._runs, self._trades, self._cfg.sample_file_prefix, user_id):
                    log.info("fno_sample_already_loaded")
                    return SampleLoadResponse(status="already_loaded", message=_MSG["already_loaded"],
                                              window=self._window(user_id))
                log.info("fno_sample_refused", reason="has_own_data")
                return self._refused("has_own_data")
            try:
                files = self._files.read_all()
            except SampleFilesMissing as e:
                log.error("fno_sample_files_missing", files=e.missing)
                return self._refused("sample_files_missing")
            before = self._runs.ids(user_id)
            uploads = [UploadInput(name=f.name, data=f.data) for f in files]
            result: Optional[FnoImportResponse] = None
            try:
                result = self._importer.import_files(user_id, uploads, allow_reserved=True)
            except Exception as e:  # noqa: BLE001 - never a 500; class name only in the log
                log.error("fno_sample_import_error", err=type(e).__name__)
            if result is None or result.totals.files_failed:
                return self._abort(user_id, before, result)
            log.info("fno_sample_loaded", inserted=result.totals.inserted, files=len(result.files))
            return SampleLoadResponse(status="loaded", message=_MSG["loaded"],
                                      window=self._window(user_id),
                                      files=result.files, totals=result.totals)

    # ── internals ──────────────────────────────────────────────────────────────

    def _has_data(self, user_id: str) -> bool:
        return bool(self._trades.coverage(user_id)["count"]
                    or self._pnl.coverage(user_id)["line_count"]
                    or self._ledger.coverage(user_id)["count"])

    def _window(self, user_id: str) -> Optional[PeriodOut]:
        run = self._runs.last_by_kind(user_id, "tradebook")
        if run is None:
            return None
        return PeriodOut(**{"from": run.period_from.isoformat() if run.period_from else None,
                            "to": run.period_to.isoformat() if run.period_to else None})

    def _refused(self, reason: str) -> SampleLoadResponse:
        return SampleLoadResponse(status="refused", reason=reason, message=_MSG[reason])  # type: ignore[arg-type]

    def _abort(self, user_id: str, before: set[str],
               result: Optional[FnoImportResponse]) -> SampleLoadResponse:
        """Undo this load only: the user had no data before it, so every row present came from it;
        run rows are deleted by id (earlier audit history, e.g. an older failed upload, is kept)."""
        failed_files = [f.file_name for f in (result.files if result else []) if f.status == "failed"]
        log.error("fno_sample_failed", failed=failed_files)
        try:
            self._db.rollback()
            ids = (self._runs.ids(user_id) - before) | {
                f.import_run_id for f in (result.files if result else []) if f.import_run_id}
            self._trades.purge(user_id)
            self._pnl.purge(user_id)
            self._ledger.purge(user_id)
            self._runs.delete_ids(user_id, ids)
            self._db.commit()
        except Exception as e:  # noqa: BLE001
            log.error("fno_sample_cleanup_failed", err=type(e).__name__)
            try:
                self._db.rollback()
            except Exception:  # noqa: BLE001
                pass
            return SampleLoadResponse(status="refused", reason="sample_failed",
                                      message=_MSG["sample_failed_cleanup"])
        return self._refused("sample_failed")

