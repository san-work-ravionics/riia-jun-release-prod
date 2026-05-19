"""Structlog configuration for RITA.

Call configure_logging(log_level) once at application startup (in main.py lifespan).
All subsequent structlog.get_logger() calls inherit this configuration.

JSON output is always used. In local dev, pipe through `jq` for readability.
"""

from __future__ import annotations

import logging
import logging.handlers
import pathlib
from datetime import datetime, timezone

import structlog


def log_event(logger, level: str, event: str, **kwargs) -> None:
    """Emit a structured log event to both structlog (console) and stdlib JSONL files."""
    import json as _json
    import logging as _std

    try:
        from rita.middleware import trace_id_var
        trace_id = trace_id_var.get("")
    except Exception:
        trace_id = ""

    data = _json.dumps({
        "event": event,
        "trace_id": trace_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **kwargs,
    })
    std_level = getattr(_std, level.upper(), _std.INFO)
    _std.getLogger("rita.events").log(std_level, data, extra={"rita_event": event})

    # Also emit to structlog for console visibility
    try:
        bound = logger.bind(event=event, trace_id=trace_id, **kwargs)
        getattr(bound, level)(event)
    except Exception:
        pass


class _PrefixFilter(logging.Filter):
    """Pass only log records whose message starts with one of the given prefixes."""

    def __init__(self, prefixes: tuple) -> None:
        super().__init__()
        self._prefixes = prefixes

    def filter(self, record: logging.LogRecord) -> bool:
        event = getattr(record, "rita_event", record.getMessage())
        return any(event.startswith(p) for p in self._prefixes)


def configure_logging(log_level: str = "info") -> None:
    """Configure stdlib logging (4 rotating JSONL handlers) and structlog.

    Idempotent — safe to call multiple times (tests, hot reload).
    Each call checks whether handlers for a given file are already attached
    before adding them, so duplicate handlers are never created.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    root = logging.getLogger()
    existing_filenames = {getattr(h, "baseFilename", None) for h in root.handlers}

    log_dir = pathlib.Path("logs")
    log_dir.mkdir(exist_ok=True)

    # Map: output filename → message prefix filter (None = catch-all)
    _FILE_MAP: dict[str, str | tuple | None] = {
        "app.jsonl": None,  # default — catches everything not matched below
        "experience.jsonl": "experience.",
        "jobs.jsonl": ("training.", "backtest.", "drift.", "trade."),
        "client-errors.jsonl": "client.",
    }

    json_formatter = logging.Formatter(
        '{"time":"%(asctime)s","level":"%(levelname)s","name":"%(name)s","message":%(message)s}'
    )

    for filename, prefix in _FILE_MAP.items():
        filepath = str(log_dir / filename)
        if filepath in existing_filenames:
            continue
        handler = logging.handlers.RotatingFileHandler(
            filepath, maxBytes=10 * 1024 * 1024, backupCount=7, encoding="utf-8"
        )
        handler.setFormatter(json_formatter)
        if prefix is not None:
            prefixes = (prefix,) if isinstance(prefix, str) else prefix
            handler.addFilter(_PrefixFilter(prefixes))
        root.addHandler(handler)

    root.setLevel(level)

    try:
        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.stdlib.add_log_level,
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.processors.JSONRenderer(),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(level),
            context_class=dict,
            logger_factory=structlog.PrintLoggerFactory(),
        )
    except Exception:
        pass  # structlog not available in test environments
