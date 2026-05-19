"""Tests for TraceIDMiddleware and global exception handlers (Day 12).

Tests cover:
- Every response carries X-Request-ID header (middleware injects it).
- A custom X-Request-ID supplied by the client is echoed back.
- 404 errors have {detail, trace_id} JSON shape.
- 422 validation errors have {detail, trace_id} JSON shape.
- Unhandled exceptions produce a 500 with {detail, trace_id}.
- RepositoryValidationError produces a 422 with {detail, trace_id}.
"""

from __future__ import annotations

from datetime import datetime, date, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


_NOW = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)


def _override(app, dep, mock_value):
    from rita.auth import get_current_user
    app.dependency_overrides[dep] = lambda: mock_value
    # Bypass JWT auth for workflow endpoint tests
    app.dependency_overrides[get_current_user] = lambda: "test-user"


def _clear(app, dep):
    from rita.auth import get_current_user
    app.dependency_overrides.pop(dep, None)
    app.dependency_overrides.pop(get_current_user, None)


# ---------------------------------------------------------------------------
# X-Request-ID / TraceIDMiddleware
# ---------------------------------------------------------------------------

class TestTraceIDMiddleware:
    def test_response_always_has_x_request_id_header(self):
        """Every response has an X-Request-ID header (auto-generated)."""
        from rita.main import app
        from rita.api.v1.system.positions import get_repo
        mock_repo = MagicMock()
        mock_repo.read_all.return_value = []
        try:
            _override(app, get_repo, mock_repo)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/system/positions/")
            assert "x-request-id" in response.headers
        finally:
            _clear(app, get_repo)

    def test_custom_x_request_id_is_echoed_back(self):
        """A custom X-Request-ID from the client is echoed in the response."""
        from rita.main import app
        from rita.api.v1.system.positions import get_repo
        mock_repo = MagicMock()
        mock_repo.read_all.return_value = []
        try:
            _override(app, get_repo, mock_repo)
            client = TestClient(app, raise_server_exceptions=False)
            custom_id = "my-trace-id-12345"
            response = client.get(
                "/api/v1/system/positions/",
                headers={"X-Request-ID": custom_id},
            )
            assert response.headers.get("x-request-id") == custom_id
        finally:
            _clear(app, get_repo)

    def test_auto_generated_x_request_id_is_uuid_format(self):
        """Auto-generated X-Request-ID looks like a UUID (36 chars with hyphens)."""
        from rita.main import app
        from rita.api.v1.system.positions import get_repo
        mock_repo = MagicMock()
        mock_repo.read_all.return_value = []
        try:
            _override(app, get_repo, mock_repo)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/system/positions/")
            trace_id = response.headers.get("x-request-id", "")
            # UUID4 format: 8-4-4-4-12 = 36 chars
            assert len(trace_id) == 36
            assert trace_id.count("-") == 4
        finally:
            _clear(app, get_repo)

    def test_health_endpoint_has_x_request_id(self):
        """The /health endpoint also gets an X-Request-ID header from middleware."""
        from rita.main import app
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/health")
        assert "x-request-id" in response.headers


# ---------------------------------------------------------------------------
# HTTP exception handler — 404 shape
# ---------------------------------------------------------------------------

class TestHttpExceptionHandler:
    def test_404_response_has_detail_key(self):
        """404 response body contains 'detail' key."""
        from rita.main import app
        from rita.api.v1.system.positions import get_repo
        mock_repo = MagicMock()
        mock_repo.find_by_id.return_value = None
        try:
            _override(app, get_repo, mock_repo)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/system/positions/nonexistent")
            assert "detail" in response.json()
        finally:
            _clear(app, get_repo)

    def test_404_response_has_trace_id_key(self):
        """404 response body contains 'trace_id' key."""
        from rita.main import app
        from rita.api.v1.system.positions import get_repo
        mock_repo = MagicMock()
        mock_repo.find_by_id.return_value = None
        try:
            _override(app, get_repo, mock_repo)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/system/positions/nonexistent")
            assert "trace_id" in response.json()
        finally:
            _clear(app, get_repo)

    def test_404_response_trace_id_matches_response_header(self):
        """trace_id in 404 body matches X-Request-ID response header."""
        from rita.main import app
        from rita.api.v1.system.positions import get_repo
        mock_repo = MagicMock()
        mock_repo.find_by_id.return_value = None
        try:
            _override(app, get_repo, mock_repo)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/system/positions/nonexistent")
            body_trace_id = response.json().get("trace_id", "")
            header_trace_id = response.headers.get("x-request-id", "")
            assert body_trace_id == header_trace_id
        finally:
            _clear(app, get_repo)

    def test_404_on_unknown_route_has_detail_and_trace_id(self):
        """Hitting a completely unknown route returns 404 with detail + trace_id."""
        from rita.main import app
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/v1/this-route-does-not-exist")
        assert response.status_code == 404
        body = response.json()
        assert "detail" in body
        assert "trace_id" in body


# ---------------------------------------------------------------------------
# Validation exception handler — 422 shape
# ---------------------------------------------------------------------------

class TestValidationExceptionHandler:
    def test_422_response_has_detail_key(self):
        """422 validation error response body contains 'detail' key."""
        from rita.main import app
        from rita.api.v1.workflow.train import get_service
        mock_svc = MagicMock()
        try:
            _override(app, get_service, mock_svc)
            client = TestClient(app, raise_server_exceptions=False)
            # Send empty JSON object — all required fields are missing
            response = client.post("/api/v1/workflow/train/", json={})
            assert response.status_code == 422
            assert "detail" in response.json()
        finally:
            _clear(app, get_service)

    def test_422_response_has_trace_id_key(self):
        """422 validation error response body contains 'trace_id' key."""
        from rita.main import app
        from rita.api.v1.workflow.train import get_service
        mock_svc = MagicMock()
        try:
            _override(app, get_service, mock_svc)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post("/api/v1/workflow/train/", json={})
            assert "trace_id" in response.json()
        finally:
            _clear(app, get_service)

    def test_422_response_has_x_request_id_header(self):
        """422 validation error response carries X-Request-ID header."""
        from rita.main import app
        from rita.api.v1.workflow.train import get_service
        mock_svc = MagicMock()
        try:
            _override(app, get_service, mock_svc)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post("/api/v1/workflow/train/", json={})
            assert "x-request-id" in response.headers
        finally:
            _clear(app, get_service)


# ---------------------------------------------------------------------------
# Repository validation error handler — 422 shape
# ---------------------------------------------------------------------------

class TestRepositoryValidationHandler:
    def test_repository_validation_error_returns_422(self):
        """RepositoryValidationError from a route raises a 422 response."""
        from rita.main import app
        from rita.api.v1.system.positions import get_repo
        from rita.repositories.base import RepositoryValidationError

        mock_repo = MagicMock()
        mock_repo.read_all.side_effect = RepositoryValidationError(
            row={"position_id": "bad-row"},
            errors=[{"type": "missing", "loc": ("instrument",), "msg": "Field required"}],
        )
        try:
            _override(app, get_repo, mock_repo)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/system/positions/")
            assert response.status_code == 422
        finally:
            _clear(app, get_repo)

    def test_repository_validation_error_has_trace_id(self):
        """RepositoryValidationError response body contains 'trace_id'."""
        from rita.main import app
        from rita.api.v1.system.positions import get_repo
        from rita.repositories.base import RepositoryValidationError

        mock_repo = MagicMock()
        mock_repo.read_all.side_effect = RepositoryValidationError(
            row={"position_id": "bad-row"},
            errors=[{"type": "missing", "loc": ("instrument",), "msg": "Field required"}],
        )
        try:
            _override(app, get_repo, mock_repo)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/system/positions/")
            assert "trace_id" in response.json()
        finally:
            _clear(app, get_repo)


# ---------------------------------------------------------------------------
# Unhandled exception handler — 500 shape
# ---------------------------------------------------------------------------

class TestUnhandledExceptionHandler:
    def test_unhandled_exception_returns_500(self):
        """An unhandled RuntimeError in a route handler produces a 500."""
        from rita.main import app
        from rita.api.v1.system.positions import get_repo

        mock_repo = MagicMock()
        mock_repo.read_all.side_effect = RuntimeError("boom — unexpected error")
        try:
            _override(app, get_repo, mock_repo)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/system/positions/")
            assert response.status_code == 500
        finally:
            _clear(app, get_repo)

    def test_unhandled_exception_has_detail_and_trace_id(self):
        """500 response body has 'detail' and 'trace_id' keys."""
        from rita.main import app
        from rita.api.v1.system.positions import get_repo

        mock_repo = MagicMock()
        mock_repo.read_all.side_effect = RuntimeError("unexpected")
        try:
            _override(app, get_repo, mock_repo)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/system/positions/")
            body = response.json()
            assert "detail" in body
            assert "trace_id" in body
        finally:
            _clear(app, get_repo)
