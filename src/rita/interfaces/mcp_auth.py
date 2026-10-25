"""MCP auth — caller identity and the JWT gate for the network transports (F44 P1, ADR-007 §5–§6).

- ``McpIdentity`` — who is calling a tool: transport (``memory``/``http``/``stdio``/``sse``), caller
  (``jarvis``, ``module:<name>``, ``external``, ``system``) and the user (id + RBAC flags) or None.
  Tools never take a ``user_id`` argument; they read the identity of the call.
- ``McpJwtGate`` — ASGI wrapper for ``/mcp`` and ``/mcp/messages/``: no / invalid / expired token →
  HTTP 401 ``WWW-Authenticate: Bearer`` before any MCP message is processed.  The token is checked
  by ``rita.auth.resolve_token_user`` — the same check as ``get_current_user``.
- ``authenticate_request`` — the same check for the ``GET /mcp/sse`` endpoint function.

The resolved identity is stored in the ASGI scope state (per request) and read back by the tool
dispatch from the MCP request context.  In-memory and stdio calls set it through a context
variable instead (``identity_scope``).
"""
from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import anyio
import structlog
from fastapi import HTTPException
from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

log = structlog.get_logger(__name__)

STATE_KEY = "rita_mcp_identity"

TRANSPORTS = ("memory", "http", "stdio", "sse")


@dataclass(frozen=True)
class McpIdentity:
    """Identity of one MCP call (immutable — safe to share between tasks of one request)."""

    transport: str
    caller: str
    user_id: str | None = None
    can_access_ops: bool = False
    can_assist_research: bool = False
    can_create_portfolio: bool = False
    can_review_portfolio: bool = False

    @classmethod
    def from_user(cls, user, *, transport: str, caller: str) -> "McpIdentity":
        """Snapshot a ``UserModel`` (no ORM object crosses task / session boundaries)."""
        return cls(
            transport=transport,
            caller=caller,
            user_id=str(user.id),
            can_access_ops=bool(getattr(user, "can_access_ops", False)),
            can_assist_research=bool(getattr(user, "can_assist_research", False)),
            can_create_portfolio=bool(getattr(user, "can_create_portfolio", False)),
            can_review_portfolio=bool(getattr(user, "can_review_portfolio", False)),
        )

    def to_user(self):
        """A transient ``UserModel`` for services that take a user (never added to a session)."""
        from rita.models.user import UserModel

        return UserModel(
            id=self.user_id,
            can_access_ops=self.can_access_ops,
            can_assist_research=self.can_assist_research,
            can_create_portfolio=self.can_create_portfolio,
            can_review_portfolio=self.can_review_portfolio,
        )


# ── in-process identity (memory / stdio) ────────────────────────────────────────

_identity_var: contextvars.ContextVar[McpIdentity | None] = contextvars.ContextVar(
    "rita_mcp_identity", default=None,
)


def current_context_identity() -> McpIdentity | None:
    return _identity_var.get()


@contextmanager
def identity_scope(identity: McpIdentity) -> Iterator[None]:
    """Set the identity for MCP calls served in this context (and tasks started from it)."""
    token = _identity_var.set(identity)
    try:
        yield
    finally:
        _identity_var.reset(token)


# ── token check ────────────────────────────────────────────────────────────────

def _session_factory():
    """DB session for the token check (indirection so tests can point it at a test DB)."""
    from rita.database import SessionLocal

    return SessionLocal()


def _resolve(token: str, transport: str) -> McpIdentity:
    from rita.auth import resolve_token_user

    db = _session_factory()
    try:
        user = resolve_token_user(token, db)
        return McpIdentity.from_user(user, transport=transport, caller="external")
    finally:
        db.close()


def _unauthorized(detail: str) -> JSONResponse:
    return JSONResponse(
        {"detail": detail}, status_code=401, headers={"WWW-Authenticate": "Bearer"},
    )


async def _identity_from_headers(headers: Headers, transport: str) -> McpIdentity | JSONResponse:
    auth = headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return _unauthorized("Not authenticated")
    try:
        # The user lookup is a sync DB query — keep it off the event loop.
        return await anyio.to_thread.run_sync(_resolve, token.strip(), transport)
    except HTTPException as exc:
        return _unauthorized(str(exc.detail))
    except Exception as exc:  # noqa: BLE001 — a broken token check must never let a call through
        log.warning("mcp.auth_failed", transport=transport, error=type(exc).__name__)
        return _unauthorized("Invalid or expired token")


async def authenticate_request(request: Request, transport: str) -> McpIdentity | JSONResponse:
    """Check the bearer token of ``request``; identity on success (also stored in the scope)."""
    result = await _identity_from_headers(request.headers, transport)
    if isinstance(result, McpIdentity):
        request.scope.setdefault("state", {})[STATE_KEY] = result
    return result


class McpJwtGate:
    """ASGI wrapper: 401 unless the request carries a valid RITA JWT; then call ``app``."""

    def __init__(self, app: ASGIApp, transport: str) -> None:
        self.app = app
        self.transport = transport

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":
            # Fail closed (F44 P1 review): websocket or any other scope never reaches MCP.
            log.warning("mcp.gate_rejected_scope", scope_type=scope["type"], transport=self.transport)
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            return
        result = await _identity_from_headers(Headers(scope=scope), self.transport)
        if isinstance(result, JSONResponse):
            await result(scope, receive, send)
            return
        scope.setdefault("state", {})[STATE_KEY] = result
        await self.app(scope, receive, send)


def identity_from_request(request) -> McpIdentity | None:
    """Identity stored by the gate on a Starlette request (None if absent)."""
    if request is None:
        return None
    state = getattr(request, "scope", {}).get("state") or {}
    ident = state.get(STATE_KEY)
    return ident if isinstance(ident, McpIdentity) else None
