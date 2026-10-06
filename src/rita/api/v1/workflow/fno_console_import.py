"""Workflow tier — F42 Phase 2 Zerodha Console import (upload + delete-my-data).

ADR-001 Tier 2: calls FnoImportService only.  PERSONAL DATA: files are parsed in memory and
never persisted to our storage (the web framework may spool large multipart bodies to its own
temp files; the file name is never used as a path).  All rows are written with the caller's
user id; the client never supplies one.

POST   /api/v1/workflow/fno/console-import              multipart field `files` (1..N)
POST   /api/v1/workflow/fno/console-import/sample       F42 P5: load the bundled SYNTHETIC sample (no body)
DELETE /api/v1/workflow/fno/console-import?confirm=true[&kind=tradebook|pnl|ledger]
"""
from __future__ import annotations

from typing import Callable, Literal, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

from rita.auth import get_current_user
from rita.config import get_settings
from rita.database import get_db
from rita.models.user import UserModel
from rita.schemas.fno_console_import import FnoImportResponse, PurgeResponse, SampleLoadResponse
from rita.services.fno_import_service import FnoImportService, UploadInput
from rita.services.fno_sample_service import FnoSampleService


class _EarlyLimitRoute(APIRoute):
    """Reject an oversized request from Content-Length before the body is parsed/spooled."""

    def get_route_handler(self) -> Callable:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            if request.method == "POST":
                cfg = get_settings().trade_analysis
                limit = cfg.import_max_total_bytes + 4096 * cfg.import_max_files
                raw_len = request.headers.get("content-length")
                if raw_len is None:  # chunked body cannot be bounded before spooling
                    raise HTTPException(status_code=411, detail="Content-Length header required")
                try:
                    declared = int(raw_len)
                except ValueError:
                    declared = 0
                if declared > limit:
                    raise HTTPException(status_code=413, detail="Upload exceeds the total size limit")
            return await original(request)

        return handler


router = APIRouter(prefix="/api/v1/workflow/fno", tags=["workflow:fno-console-import"],
                   route_class=_EarlyLimitRoute)
# The sample endpoint takes no body, so it must NOT use _EarlyLimitRoute (which demands a Content-Length).
sample_router = APIRouter(prefix="/api/v1/workflow/fno", tags=["workflow:fno-console-import"])


def _get_service(db: Session = Depends(get_db)) -> FnoImportService:
    return FnoImportService(db)


@router.post("/console-import", response_model=FnoImportResponse)
async def upload_console_files(
    files: list[UploadFile] = File(...),
    current_user: UserModel = Depends(get_current_user),
    svc: FnoImportService = Depends(_get_service),
) -> FnoImportResponse:
    cfg = get_settings().trade_analysis
    if await run_in_threadpool(svc.is_sample_data, current_user.id):
        # F42 P5: real uploads are blocked while the synthetic sample is loaded (user decision 1)
        raise HTTPException(status_code=409,
                            detail="Sample data is loaded. Remove it before importing your own files.")
    if not files:
        raise HTTPException(status_code=422, detail="No files supplied")
    if len(files) > cfg.import_max_files:
        raise HTTPException(status_code=413, detail=f"At most {cfg.import_max_files} files per upload")
    uploads: list[UploadInput] = []
    total = 0
    for f in files:
        data = await f.read(cfg.import_max_file_bytes + 1)  # bounded read
        too_large = len(data) > cfg.import_max_file_bytes
        total += len(data)
        if total > cfg.import_max_total_bytes:
            raise HTTPException(status_code=413, detail="Upload exceeds the total size limit")
        uploads.append(UploadInput(name=f.filename or "", data=b"" if too_large else data,
                                   too_large=too_large))
    return await run_in_threadpool(svc.import_files, current_user.id, uploads)


@router.delete("/console-import", response_model=PurgeResponse)
def delete_my_console_data(
    confirm: bool = Query(default=False),
    kind: Optional[Literal["tradebook", "pnl", "ledger"]] = Query(default=None),
    current_user: UserModel = Depends(get_current_user),
    svc: FnoImportService = Depends(_get_service),
) -> PurgeResponse:
    if not confirm:
        raise HTTPException(status_code=422, detail="confirm=true is required to delete imported data")
    return svc.purge(current_user.id, kind)


def _get_sample_service(db: Session = Depends(get_db)) -> FnoSampleService:
    return FnoSampleService.from_settings(db)


@sample_router.post("/console-import/sample", response_model=SampleLoadResponse)
def load_sample_data(
    current_user: UserModel = Depends(get_current_user),
    svc: FnoSampleService = Depends(_get_sample_service),
) -> SampleLoadResponse:
    """Load the bundled synthetic sample into the CALLER's own tables (never merges into real data).

    Business refusals are HTTP 200 with ``status: "refused"`` + ``reason`` (the shared JS api()
    helper hides non-2xx bodies)."""
    return svc.load(current_user.id)
