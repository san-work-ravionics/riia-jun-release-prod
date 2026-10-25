"""
RITA Core — MCP Call Logger

Writes one DB row per MCP tool call, from the one tool dispatch in interfaces/mcp_tools.py — every
transport (memory / http / stdio / sse).  Reads are served by GET /api/v1/mcp-calls.

Opens its own SessionLocal() per write, following the same pattern as background threads
(Spec_DB §5) — the stdio server is a separate process, and a tool never borrows a request session.
Callers must pass summaries that hold no personal_* data or message text (ADR-007 §7).
"""
from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any


def _default_session():
    from rita.database import SessionLocal

    return SessionLocal()


# Injectable so tests never write into the real dev rita.db (F44 P1 review).
_session_factory: list[Callable[[], Any]] = [_default_session]


def set_session_factory(factory: Callable[[], Any] | None) -> None:
    """Point the call log at another DB session factory (None restores ``SessionLocal``)."""
    _session_factory[0] = factory or _default_session


def log_mcp_call(
    tool_name: str,
    args_summary: str,
    result_summary: str,
    duration_ms: float,
    status: str = "ok",
    *,
    transport: str | None = None,
    caller: str | None = None,
    user_id: str | None = None,
    call_id: str | None = None,
) -> str:
    """Insert one MCP tool-call row into the mcp_calls table; returns its ``call_id``."""
    from rita.models.mcp_call import MCPCallModel
    from rita.repositories.mcp_call import MCPCallRepository

    now = datetime.now(timezone.utc)
    call_id = call_id or str(uuid.uuid4())
    record = MCPCallModel(
        call_id        = call_id,
        timestamp      = now,
        tool_name      = tool_name,
        status         = status,
        duration_ms    = round(duration_ms, 1),
        args_summary   = args_summary[:300],
        result_summary = result_summary[:200],
        recorded_at    = now,
        transport      = transport,
        caller         = caller,
        user_id        = user_id,
    )
    db = _session_factory[0]()
    try:
        MCPCallRepository(db).create(record)
    finally:
        db.close()
    return call_id


def get_mcp_calls(limit: int = 100) -> list[dict]:
    """Return the most recent MCP call rows as dicts, newest first."""
    from rita.repositories.mcp_call import MCPCallRepository

    db = _session_factory[0]()
    try:
        rows = MCPCallRepository(db).get_recent(limit)
        return [
            {
                "call_id":        r.call_id,
                "timestamp":      r.timestamp.isoformat(),
                "tool_name":      r.tool_name,
                "status":         r.status,
                "duration_ms":    r.duration_ms,
                "args_summary":   r.args_summary or "",
                "result_summary": r.result_summary or "",
                "transport":      r.transport,
                "caller":         r.caller,
                "user_id":        r.user_id,
            }
            for r in rows
        ]
    finally:
        db.close()
