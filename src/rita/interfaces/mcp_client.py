"""In-memory MCP client — how RITA modules (and Jarvis) call each other's tools (F44 P1, ADR-007 §4).

No network and no extra process: an MCP ``ClientSession`` talks to the shared server over the SDK's
in-memory streams.  The caller identity (user + ``caller`` label) is the identity of the request
that started the call — never a tool argument.

Async code::

    async with memory_client(identity_for(user, "jarvis")) as mcp:
        plan = await mcp.call("whatineed.get_plan", {"location": "europe"})
        plan.structured["result"]["retire_age"]

Sync service code (services and SQLAlchemy are synchronous; FastAPI runs sync routes in a worker
thread) — **one session per request**, reused for every call in that request::

    with McpRequestClient(identity_for(user, "module:portfolio")) as mcp:
        goal = mcp.call("whatineed.get_plan")

or as a route dependency: ``mcp: McpRequestClient = Depends(mcp_client_dependency("jarvis"))``.

The sync bridge runs the session on its own event loop in a helper thread (anyio blocking portal),
so it never blocks the server's event loop; calling it *on* an event-loop thread raises
``RuntimeError`` (use ``memory_client`` there).  A tool error comes back as ``McpCallError`` with the
stable ``code`` (``not_found`` | ``forbidden`` | ``invalid_input`` | ``unavailable``).
"""
from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import anyio
import anyio.from_thread
from mcp.shared.memory import create_connected_server_and_client_session

from rita.interfaces.mcp_auth import McpIdentity, identity_scope
from rita.interfaces.mcp_tools import server

_CALLER_RE = re.compile(r"^(jarvis|external|system|module:[a-z][a-z0-9_]*)$")


def identity_for(user, caller: str) -> McpIdentity:
    """In-memory identity for ``user`` (a ``UserModel`` or None) and a ``caller`` label:
    ``jarvis``, ``module:<name>``, ``system`` or ``external``."""
    if not _CALLER_RE.match(caller):
        raise ValueError(f"invalid MCP caller {caller!r}")
    if user is None:
        return McpIdentity(transport="memory", caller=caller)
    return McpIdentity.from_user(user, transport="memory", caller=caller)


class McpCallError(Exception):
    """A tool returned an error result."""

    def __init__(self, tool: str, code: str, message: str, call_id: str | None) -> None:
        super().__init__(f"{tool}: {code}: {message}")
        self.tool = tool
        self.code = code
        self.message = message
        self.call_id = call_id


@dataclass(frozen=True)
class ToolCallResult:
    name: str
    structured: dict[str, Any] | None
    text: str
    call_id: str | None   # the mcp_calls row of this call


def _to_result(name: str, res) -> ToolCallResult:
    text = "\n".join(getattr(c, "text", "") for c in res.content)
    call_id = (res.meta or {}).get("mcp_call_id")
    if res.isError:
        err = (res.structuredContent or {}).get("error") or {}
        raise McpCallError(name, err.get("code", "unavailable"), err.get("message", text), call_id)
    return ToolCallResult(name=name, structured=res.structuredContent, text=text, call_id=call_id)


class AsyncMcpClient:
    def __init__(self, session) -> None:
        self._session = session

    async def call(self, name: str, arguments: dict[str, Any] | None = None) -> ToolCallResult:
        return _to_result(name, await self._session.call_tool(name, arguments or {}))

    async def list_tools(self) -> list:
        return (await self._session.list_tools()).tools


@asynccontextmanager
async def memory_client(identity: McpIdentity) -> AsyncIterator[AsyncMcpClient]:
    """An initialised in-memory MCP session whose calls run as ``identity``."""
    if identity.transport != "memory":
        raise ValueError("memory_client needs a transport='memory' identity")
    # The server task started below inherits this context — the identity is per session, so two
    # concurrent sessions (two requests) never see each other's user.
    with identity_scope(identity):
        try:
            async with create_connected_server_and_client_session(server) as session:
                yield AsyncMcpClient(session)
        except BaseExceptionGroup as group:
            # The SDK runs the session in a task group, which wraps an exception raised in the
            # caller's ``async with`` body; re-raise the caller's own exception unwrapped.
            leaf = _single_leaf(group)
            if leaf is None:
                raise
            raise leaf from None


def _single_leaf(group: BaseExceptionGroup) -> BaseException | None:
    exc: BaseException = group
    while isinstance(exc, BaseExceptionGroup):
        if len(exc.exceptions) != 1:
            return None
        exc = exc.exceptions[0]
    return exc


def _assert_not_on_event_loop() -> None:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    raise RuntimeError(
        "McpRequestClient is for synchronous code in a worker thread; "
        "on the event loop use `async with memory_client(...)`"
    )


class McpRequestClient:
    """Synchronous in-memory MCP client: one session for the lifetime of the ``with`` block."""

    def __init__(self, identity: McpIdentity) -> None:
        self._identity = identity
        self._portal_cm = None
        self._portal = None
        self._client_cm = None
        self._client: AsyncMcpClient | None = None

    def __enter__(self) -> "McpRequestClient":
        _assert_not_on_event_loop()
        self._portal_cm = anyio.from_thread.start_blocking_portal()
        self._portal = self._portal_cm.__enter__()
        try:
            self._client_cm = self._portal.wrap_async_context_manager(memory_client(self._identity))
            self._client = self._client_cm.__enter__()
        except BaseException:
            self._portal_cm.__exit__(None, None, None)
            raise
        return self

    def call(self, name: str, arguments: dict[str, Any] | None = None) -> ToolCallResult:
        if self._client is None or self._portal is None:
            raise RuntimeError("McpRequestClient used outside its `with` block")
        return self._portal.call(self._client.call, name, arguments)

    def list_tools(self) -> list:
        if self._client is None or self._portal is None:
            raise RuntimeError("McpRequestClient used outside its `with` block")
        return self._portal.call(self._client.list_tools)

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if self._client_cm is not None:
                self._client_cm.__exit__(exc_type, exc, tb)
        finally:
            self._client = None
            self._client_cm = None
            if self._portal_cm is not None:
                self._portal_cm.__exit__(None, None, None)
            self._portal = None
            self._portal_cm = None


def mcp_client_dependency(caller: str) -> Callable[..., Iterator[McpRequestClient]]:
    """FastAPI dependency factory: one in-memory session per request for the signed-in user."""
    from fastapi import Depends

    from rita.auth import get_current_user

    identity_for(None, caller)  # validate the label at import time

    def _dep(user=Depends(get_current_user)) -> Iterator[McpRequestClient]:
        with McpRequestClient(identity_for(user, caller)) as client:
            yield client

    return _dep
