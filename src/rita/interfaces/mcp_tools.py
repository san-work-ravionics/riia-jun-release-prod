"""
Shared MCP Server instance — one server, namespaced tools, one dispatch (F44 P1, ADR-007).

Served by every transport:
  - in-memory  ``mcp_client.py``      (RITA modules / Jarvis, same process)
  - HTTP       ``mcp_http_app.py``    (``/mcp`` streamable HTTP, JWT)
  - SSE        ``mcp_sse_app.py``     (``/mcp/sse``, JWT, deprecated)
  - stdio      ``rita_mcp_server.py`` (Claude Desktop local; Auth ``none`` tools + legacy aliases)

The dispatch is the single path every call takes: resolve the caller identity → check the tool is
offered on this transport and the caller has the access it declares → validate the input (Pydantic)
→ run the synchronous handler in a worker thread (never on the event loop) → build the result
(structured content + short text, or a coded error) → write one ``mcp_calls`` row.  A logger
failure never fails the call.

No transport-specific setup (no chdir, no logging redirect, no sys.path hacks) belongs here — keep
this module side-effect-free at import time.
"""
from __future__ import annotations

import time
import uuid
from typing import Any

import anyio
import structlog
from mcp.server import Server
from mcp.types import CallToolResult, TextContent, Tool
from pydantic import BaseModel, ValidationError

from rita.interfaces.mcp_auth import McpIdentity, current_context_identity, identity_from_request
from rita.interfaces.tools import ToolContext, ToolError, ToolSpec, all_tools

try:
    from rita.core.mcp_logger import log_mcp_call as _log_call
except ImportError:  # pragma: no cover
    def _log_call(**_kw) -> None:  # noqa: E704
        pass

log = structlog.get_logger(__name__)

server = Server("rita")

REGISTRY: dict[str, ToolSpec] = {spec.name: spec for spec in all_tools()}

_ANONYMOUS = McpIdentity(transport="memory", caller="external")


def tools_registered() -> int:
    return len(REGISTRY)


# ── identity + access ──────────────────────────────────────────────────────────

def _call_identity() -> McpIdentity:
    """HTTP / SSE: the identity the JWT gate put on the request.  Memory / stdio: the context
    identity set by the client helper / stdio server.  Otherwise an anonymous caller (no user)."""
    request = None
    try:
        request = server.request_context.request
    except LookupError:
        pass
    ident = identity_from_request(request)
    if ident is not None:
        return ident
    ident = current_context_identity()
    if ident is not None:
        return ident
    return _ANONYMOUS


def offered(spec: ToolSpec, identity: McpIdentity) -> bool:
    """stdio offers only the tools that need no user (+ legacy aliases); others offer all."""
    return spec.stdio if identity.transport == "stdio" else True


def check_access(spec: ToolSpec, identity: McpIdentity) -> None:
    if identity.transport == "stdio":
        if not spec.stdio:
            raise ToolError("forbidden", f"{spec.name} needs a signed-in user; not available over stdio")
        return  # local process: today's behaviour for the stdio tools
    if "none" in spec.auth:
        return
    if identity.caller == "system" and "system" in spec.auth:
        return
    if "user" in spec.auth and identity.user_id:
        if spec.requires_flag and not getattr(identity, spec.requires_flag, False):
            raise ToolError("forbidden", f"{spec.name} requires {spec.requires_flag}")
        return
    raise ToolError("forbidden", f"{spec.name} needs a signed-in user")


# ── catalogue ──────────────────────────────────────────────────────────────────

def tool_definition(spec: ToolSpec) -> Tool:
    return Tool(
        name=spec.name,
        description=spec.description,
        inputSchema=spec.input_json_schema(),
        outputSchema=spec.output_json_schema(),
    )


@server.list_tools()
async def list_tools() -> list[Tool]:
    identity = _call_identity()
    return [tool_definition(s) for s in REGISTRY.values() if offered(s, identity)]


# ── dispatch ───────────────────────────────────────────────────────────────────

def _error_result(code: str, message: str) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=f"{code}: {message}")],
        structuredContent={"error": {"code": code, "message": message}},
        isError=True,
    )


# Allow-list (F44 P1 review): only these keys are logged with their value — instrument / location
# ids, enums and small counts.  Any other string (free text: query, message, …) is logged as
# ``<key>_len=N``; anything else (amounts and rates: portfolio_value, portfolio_inr, target_return,
# value_now, goal_value, …) as the bare key, never the value.
SAFE_ARG_KEYS = frozenset({
    "instrument", "instrument_id", "instruments", "location", "limit", "horizon", "months",
    "horizon_days", "time_horizon_days", "years", "currency", "base", "quote", "as_of", "mode",
    "state", "id",
})


def _summarise_args(arguments: dict[str, Any]) -> str:
    """Key args for mcp_calls.args_summary — allow-listed values only; no text, no amounts."""
    parts = []
    for key, value in (arguments or {}).items():
        if value is None:
            continue
        if key in SAFE_ARG_KEYS:
            parts.append(f"{key}={str(value)[:40]}")
        elif isinstance(value, str):
            parts.append(f"{key}_len={len(value)}")
        else:
            parts.append(str(key)[:40])
    return ", ".join(parts)[:300]


def _write_log(**kw) -> None:
    try:
        _log_call(**kw)
    except Exception as exc:  # noqa: BLE001 — logging never fails a tool call
        log.warning("mcp.log_failed", tool=kw.get("tool_name"), error=type(exc).__name__)


async def dispatch(name: str, arguments: dict[str, Any] | None) -> CallToolResult:
    """Run one tool call for the current caller identity (all transports come through here)."""
    identity = _call_identity()
    arguments = arguments or {}
    call_id = str(uuid.uuid4())
    t0 = time.perf_counter()
    status = "ok"
    summary = ""
    spec = REGISTRY.get(name)
    try:
        if spec is None:
            raise ToolError("not_found", f"Unknown tool: {name}")
        check_access(spec, identity)
        try:
            inp = spec.input_model.model_validate(arguments)
        except ValidationError as exc:
            raise ToolError("invalid_input", _validation_message(exc)) from exc
        ctx = ToolContext(identity=identity)
        out = await anyio.to_thread.run_sync(spec.handler, inp, ctx)
        if spec.legacy:
            text = str(out)
            result = CallToolResult(content=[TextContent(type="text", text=text)])
            summary = spec.summary(text)
        else:
            if not isinstance(out, spec.output_model):
                out = spec.output_model.model_validate(out)
            result = CallToolResult(
                content=[TextContent(type="text", text=spec.text(out))],
                structuredContent=_dump(out),
            )
            summary = spec.summary(out)
    except ToolError as exc:
        status = "error"
        summary = f"{exc.code}: {exc.message}"
        if spec is not None and spec.legacy and exc.code in ("not_found", "unavailable"):
            # Legacy aliases answered failures as text before F44 — keep that shape.
            result = CallToolResult(content=[TextContent(type="text", text=f"RITA error ({name}): {exc.message}")])
        else:
            result = _error_result(exc.code, exc.message)
    except Exception as exc:  # noqa: BLE001 — a tool bug is an 'unavailable' error, never a 500
        status = "error"
        log.warning("mcp.tool_failed", tool=name, error=type(exc).__name__, detail=str(exc)[:200])
        summary = f"unavailable: {type(exc).__name__}"
        if spec is not None and spec.legacy:
            result = CallToolResult(content=[TextContent(type="text", text=f"RITA error ({name}): {exc}")])
        else:
            result = _error_result("unavailable", f"{name} failed: {type(exc).__name__}")

    duration_ms = round((time.perf_counter() - t0) * 1_000, 1)
    await anyio.to_thread.run_sync(lambda: _write_log(
        tool_name=name,
        args_summary=_summarise_args(arguments),
        result_summary=summary[:200],
        duration_ms=duration_ms,
        status=status,
        transport=identity.transport,
        caller=identity.caller,
        user_id=identity.user_id,
        call_id=call_id,
    ))
    result.meta = {**(result.meta or {}), "mcp_call_id": call_id}
    return result


def _dump(out: BaseModel) -> dict[str, Any]:
    return out.model_dump(mode="json")


def _validation_message(exc: ValidationError) -> str:
    errs = exc.errors()[:3]
    return "; ".join(f"{'.'.join(str(p) for p in e.get('loc', ())) or 'input'}: {e.get('msg')}" for e in errs)


@server.call_tool(validate_input=False)
async def call_tool(name: str, arguments: dict) -> CallToolResult:
    # Input is validated by the tool's Pydantic model inside dispatch (coded invalid_input + log).
    return await dispatch(name, arguments)
