"""
System router — MCP call log.

GET /api/v1/mcp-calls?limit=100

Returns the most recent MCP tool invocations stored in the mcp_calls table.
Consumed by mcp.js → loadMcp() in the RITA dashboard.
F44 P1: rows also carry transport, caller, user_id (nullable).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from rita.database import get_db

router = APIRouter(prefix="/api/v1/mcp-calls", tags=["system:mcp"])


@router.get("")
def list_mcp_calls(
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list:
    sql = text("""
        SELECT call_id, timestamp, tool_name, status,
               duration_ms, args_summary, result_summary,
               transport, caller, user_id
        FROM mcp_calls
        ORDER BY timestamp DESC
        LIMIT :limit
    """)
    rows = db.execute(sql, {"limit": limit}).fetchall()
    return [
        {
            "call_id":        r.call_id,
            "timestamp":      str(r.timestamp),
            "tool_name":      r.tool_name,
            "status":         r.status,
            "duration_ms":    r.duration_ms,
            "args_summary":   r.args_summary or "",
            "result_summary": r.result_summary or "",
            "transport":      r.transport,   # F44 P1 — null for rows before P1
            "caller":         r.caller,
            "user_id":        r.user_id,
        }
        for r in rows
    ]
