"""Prometheus metrics instrumentation for RITA.

Wires prometheus-fastapi-instrumentator onto the FastAPI application and
exposes the standard HTTP request metrics at GET /metrics.

Excluded paths (to avoid noise in dashboards):
  - /metrics  — the scrape endpoint itself
  - /health   — liveness probe (high-frequency, low-signal)
  - /readyz   — readiness probe (high-frequency, low-signal)
"""

from __future__ import annotations

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator


def instrument_app(app: FastAPI) -> None:
    """Instrument *app* with Prometheus metrics and expose GET /metrics.

    Call this after all routers have been registered so that the instrumentator
    captures every route defined on the application.
    """
    Instrumentator(
        should_group_status_codes=False,
        excluded_handlers=["/metrics", "/health", "/readyz"],
    ).instrument(app).expose(app)
