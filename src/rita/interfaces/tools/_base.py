"""Tool definition types shared by the per-namespace tool modules (F44 P1, ADR-007).

A tool is a ``ToolSpec``: name, Pydantic input/output models, a **synchronous** handler that calls
services (never routers or repositories), the access it needs, and short text / log renderings.
The one dispatch in ``rita.interfaces.mcp_tools`` validates input, checks access, runs the handler
in a worker thread, builds the MCP result and writes the ``mcp_calls`` row.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from rita.interfaces.mcp_auth import McpIdentity

ERROR_CODES = ("not_found", "forbidden", "invalid_input", "unavailable")


class ToolError(Exception):
    """A tool failure with a stable code: not_found | forbidden | invalid_input | unavailable."""

    def __init__(self, code: str, message: str) -> None:
        if code not in ERROR_CODES:
            raise ValueError(f"unknown tool error code {code!r}")
        super().__init__(message)
        self.code = code
        self.message = message


def _default_session():
    from rita.database import SessionLocal

    return SessionLocal()


# Indirection so tests can point every tool call at a test database.
_session_factory: list[Callable[[], Any]] = [_default_session]


# The logger's factory before the tools override it, restored on reset (so a test fixture's reset
# returns the logger to whatever conftest pointed it at — never silently to the dev DB).
_saved_logger_factory: list[Callable[[], Any]] = []


def set_session_factory(factory: Callable[[], Any] | None) -> None:
    """Override the DB session factory used by tools **and** the mcp_calls logger.

    ``None`` restores ``SessionLocal`` for tools and the logger's previous factory."""
    from rita.core import mcp_logger

    if factory is not None:
        if not _saved_logger_factory:
            _saved_logger_factory.append(mcp_logger._session_factory[0])
        mcp_logger._session_factory[0] = factory
    elif _saved_logger_factory:
        mcp_logger._session_factory[0] = _saved_logger_factory.pop()
    _session_factory[0] = factory or _default_session


@dataclass(frozen=True)
class ToolContext:
    """What a handler gets besides its input: the caller identity and a session opener."""

    identity: McpIdentity

    @contextmanager
    def session(self) -> Iterator[Any]:
        """A DB session opened for this tool call and closed when done (ADR-007 §2)."""
        db = _session_factory[0]()
        try:
            yield db
        finally:
            db.close()

    def require_user(self):
        """The calling user as a transient ``UserModel``; ``forbidden`` if there is none."""
        if not self.identity.user_id:
            raise ToolError("forbidden", "this tool needs a signed-in user")
        return self.identity.to_user()


def _no_text(_out: Any) -> str:
    return "ok"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_model: type[BaseModel]
    handler: Callable[[Any, ToolContext], Any]
    # Access (catalogue column "Auth"): "none" = anyone; "user" = signed-in user; "system" = the
    # P6 scheduled-job identity may also call it.
    auth: frozenset[str]
    output_model: type[BaseModel] | None = None      # None = legacy alias (Markdown text only)
    requires_flag: str | None = None                 # RBAC flag on the user, e.g. "can_access_ops"
    text: Callable[[Any], str] = _no_text            # short text rendering of the output
    summary: Callable[[Any], str] = _no_text         # mcp_calls.result_summary — no personal data
    stdio: bool = False                              # exposed on the local stdio server
    input_schema: dict | None = None                 # explicit schema (legacy aliases keep theirs)

    @property
    def legacy(self) -> bool:
        return self.output_model is None

    def input_json_schema(self) -> dict:
        if self.input_schema is not None:
            return self.input_schema
        schema = self.input_model.model_json_schema()
        schema.pop("title", None)
        return schema

    def output_json_schema(self) -> dict | None:
        if self.output_model is None:
            return None
        return self.output_model.model_json_schema(mode="serialization")
