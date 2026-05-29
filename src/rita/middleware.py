"""RITA request middleware.

TraceIDMiddleware
----------------
Attaches a trace ID to every request so errors and logs can be correlated.

- Reads `X-Request-ID` from the incoming request headers if the client supplies one.
- Generates a new UUID4 otherwise.
- Stores the trace ID in a ContextVar so exception handlers can read it without
  threading issues (each async task gets its own slot).
- Writes `X-Request-ID` back onto the response headers.

ApiCallLogMiddleware
--------------------
Logs every API request's path, method, status code, and duration to the
api_call_log table. Fires after the response is produced — no latency impact
on the response itself. Skips static assets, health checks, and docs.
On DB write failure, logs a warning and continues — never raises.
"""

from __future__ import annotations

import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Module-level ContextVar — safe for concurrent async requests
trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")

log = structlog.get_logger()

# Paths that should never be logged to api_call_log
_EXCLUDED_PATHS = {"/health", "/readyz", "/metrics", "/docs", "/openapi.json", "/redoc", "/favicon.ico"}
_EXCLUDED_PREFIXES = ("/dashboard", "/static", "/openapi")


class TraceIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        trace_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        token = trace_id_var.set(trace_id)
        structlog.contextvars.bind_contextvars(trace_id=trace_id)
        response = None
        try:
            response = await call_next(request)
        finally:
            log.info(
                "http.request",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code if response is not None else None,
            )
            structlog.contextvars.clear_contextvars()
            trace_id_var.reset(token)
        response.headers["X-Request-ID"] = trace_id
        return response


class ApiCallLogMiddleware(BaseHTTPMiddleware):
    """Log API request metrics to api_call_log after each response."""

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        # Skip non-API paths
        if path in _EXCLUDED_PATHS or any(path.startswith(p) for p in _EXCLUDED_PREFIXES):
            return await call_next(request)

        start = time.monotonic()
        response = None
        unhandled_exc = None
        try:
            response = await call_next(request)
        except Exception as exc:
            unhandled_exc = exc

        duration_ms = (time.monotonic() - start) * 1000
        status_code = response.status_code if response is not None else 500

        try:
            from rita.database import SessionLocal
            from rita.models.api_call_log import ApiCallLogModel

            db = SessionLocal()
            try:
                record = ApiCallLogModel(
                    call_id=str(uuid.uuid4()),
                    path=path,
                    method=request.method,
                    status_code=status_code,
                    duration_ms=round(duration_ms, 2),
                    called_at=datetime.now(timezone.utc).replace(tzinfo=None),
                    recorded_at=datetime.now(timezone.utc).replace(tzinfo=None),
                )
                db.add(record)
                db.commit()
            finally:
                db.close()
        except Exception as exc:
            structlog.get_logger().warning("api_call_log.write_failed", error=str(exc))

        if unhandled_exc is not None:
            raise unhandled_exc
        return response
