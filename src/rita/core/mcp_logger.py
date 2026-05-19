"""
RITA Core — MCP Call Logger

Writes one DB row per MCP tool invocation made via rita_mcp_server.
Reads are served by GET /api/v1/mcp-calls via MCPCallRepository.

The MCP server is a separate process — it opens its own SessionLocal()
per write, following the same pattern as background threads (Spec_DB §5).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone


def log_mcp_call(
    tool_name: str,
    args_summary: str,
    result_summary: str,
    duration_ms: float,
    status: str = "ok",
) -> None:
    """Insert one MCP tool-call row into the mcp_calls table."""
    from rita.database import SessionLocal
    from rita.models.mcp_call import MCPCallModel
    from rita.repositories.mcp_call import MCPCallRepository

    now = datetime.now(timezone.utc)
    record = MCPCallModel(
        call_id        = str(uuid.uuid4()),
        timestamp      = now,
        tool_name      = tool_name,
        status         = status,
        duration_ms    = round(duration_ms, 1),
        args_summary   = args_summary[:300],
        result_summary = result_summary[:200],
        recorded_at    = now,
    )
    db = SessionLocal()
    try:
        MCPCallRepository(db).create(record)
    finally:
        db.close()


def get_mcp_calls(limit: int = 100) -> list[dict]:
    """Return the most recent MCP call rows as dicts, newest first."""
    from rita.database import SessionLocal
    from rita.repositories.mcp_call import MCPCallRepository

    db = SessionLocal()
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
            }
            for r in rows
        ]
    finally:
        db.close()
