"""RITA global exception handlers.

All handlers return a consistent JSON shape:

    {"detail": <message or list>, "trace_id": "<uuid>"}

and echo the trace ID in the `X-Request-ID` response header so clients can
correlate errors even when they did not supply an ID themselves.

Registration order in main.py matters:
  1. StarletteHTTPException  — covers HTTPException raised in route handlers
  2. RequestValidationError  — covers 422 Pydantic/FastAPI request validation
  3. RepositoryValidationError — covers CSV schema violations from the data layer
  4. Exception               — catch-all for any unhandled runtime error (→ 500)
"""

from __future__ import annotations

import structlog
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from rita.middleware import trace_id_var
from rita.repositories.base import RepositoryValidationError

log = structlog.get_logger()


def _tid() -> str:
    return trace_id_var.get() or ""


def _headers() -> dict[str, str]:
    tid = _tid()
    return {"X-Request-ID": tid} if tid else {}


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "trace_id": _tid()},
        headers=_headers(),
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "trace_id": _tid()},
        headers=_headers(),
    )


async def repository_validation_handler(request: Request, exc: RepositoryValidationError) -> JSONResponse:
    log.warning("repository_validation_error", trace_id=_tid())
    return JSONResponse(
        status_code=422,
        content={"detail": f"Data integrity error: {exc.errors!r}", "trace_id": _tid()},
        headers=_headers(),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    log.error("unhandled_exception", exc_info=exc, trace_id=_tid())
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "trace_id": _tid()},
        headers=_headers(),
    )
