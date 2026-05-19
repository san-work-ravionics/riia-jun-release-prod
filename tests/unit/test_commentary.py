"""Unit tests for POST /api/v1/commentary and related commentary infrastructure.

Coverage
--------
1. HTTP 400 for unknown app+page combination
2. HTTP 400 for strategy page called without instrument
3. HTTP 200 response shape — all 5 schema fields present, correct types
4. commentary field is always a non-empty string (never None)
5. Monitor endpoint (/api/v1/chat/monitor) includes the 3 commentary KPI keys
6. CommentaryLogRepository.get_summary() returns correct dict keys
7. API-frontend contract — schema field names match exactly what commentary.js reads

Strategy
--------
- Handlers (_handle_overview, _handle_strategy) are patched to avoid CSV / ML deps.
- CommentaryLogRepository.create is patched to avoid DB audit write failures in
  unit-test context where the real schema may not exist.
- get_db is overridden with a real in-memory SQLite session from conftest (db_session)
  for repository tests; TestClient uses the same fixture.
- Tests that only exercise HTTP routing use a mock_db that satisfies the session
  interface but does not need real tables.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _client_with_mock_db(mock_db=None):
    """Return a TestClient with get_db overridden (no real DB needed)."""
    from rita.main import app
    from rita.database import get_db

    if mock_db is None:
        mock_db = MagicMock()

    app.dependency_overrides[get_db] = lambda: mock_db
    c = TestClient(app, raise_server_exceptions=False)
    return app, c, get_db


def _clear(app, get_db):
    app.dependency_overrides.pop(get_db, None)


def _overview_handler_result():
    """Minimal return value for _handle_overview — no CSV needed."""
    return {
        "commentary": "Cross-instrument overview: US: NVIDIA (NEUTRAL weekly / NEUTRAL monthly). Signals are computed from SMA-20, RSI-14.",
        "instruments_analyzed": ["NVIDIA", "ASML", "NIFTY", "BANKNIFTY"],
    }


def _strategy_handler_result():
    """Minimal return value for _handle_strategy — no CSV needed."""
    return {
        "commentary": "For NIFTY, RITA's strategy engine recommends holding cash.",
        "instruments_analyzed": ["NIFTY"],
    }


# ---------------------------------------------------------------------------
# 1. HTTP 400 — unknown app+page combination
# ---------------------------------------------------------------------------

class TestUnknownAppPage:
    """Requests with app+page not in the dispatch table must return HTTP 400."""

    def test_unknown_app_returns_400(self):
        app, client, get_db = _client_with_mock_db()
        try:
            resp = client.post("/api/v1/commentary", json={"app": "unknown", "page": "overview"})
            assert resp.status_code == 400, f"Expected 400, got {resp.status_code}"
        finally:
            _clear(app, get_db)

    def test_unknown_page_returns_400(self):
        app, client, get_db = _client_with_mock_db()
        try:
            resp = client.post("/api/v1/commentary", json={"app": "rita", "page": "nonexistent"})
            assert resp.status_code == 400, f"Expected 400, got {resp.status_code}"
        finally:
            _clear(app, get_db)

    def test_unknown_combo_detail_mentions_app_and_page(self):
        app, client, get_db = _client_with_mock_db()
        try:
            resp = client.post("/api/v1/commentary", json={"app": "fno", "page": "dashboard"})
            body = resp.json()
            assert "detail" in body
            detail = body["detail"]
            assert "fno" in detail or "dashboard" in detail, (
                f"400 detail should mention app/page, got: {detail}"
            )
        finally:
            _clear(app, get_db)


# ---------------------------------------------------------------------------
# 2. HTTP 400 — strategy page without instrument
# ---------------------------------------------------------------------------

class TestStrategyWithoutInstrument:
    """POST with page='strategy' but no instrument field must return HTTP 400."""

    def test_strategy_no_instrument_returns_400(self):
        app, client, get_db = _client_with_mock_db()
        try:
            resp = client.post("/api/v1/commentary", json={"app": "rita", "page": "strategy"})
            assert resp.status_code == 400, f"Expected 400, got {resp.status_code}"
        finally:
            _clear(app, get_db)

    def test_strategy_null_instrument_returns_400(self):
        app, client, get_db = _client_with_mock_db()
        try:
            resp = client.post(
                "/api/v1/commentary",
                json={"app": "rita", "page": "strategy", "instrument": None},
            )
            assert resp.status_code == 400, f"Expected 400, got {resp.status_code}"
        finally:
            _clear(app, get_db)

    def test_strategy_no_instrument_error_message(self):
        app, client, get_db = _client_with_mock_db()
        try:
            resp = client.post("/api/v1/commentary", json={"app": "rita", "page": "strategy"})
            body = resp.json()
            assert "instrument" in body.get("detail", ""), (
                f"Error detail should mention 'instrument', got: {body.get('detail')}"
            )
        finally:
            _clear(app, get_db)


# ---------------------------------------------------------------------------
# 3. HTTP 200 — response shape (all 5 fields, correct types)
# ---------------------------------------------------------------------------

class TestOverviewResponseShape:
    """Valid overview request must return HTTP 200 with all 5 schema fields."""

    def test_overview_returns_200(self):
        app, client, get_db = _client_with_mock_db()
        try:
            with patch(
                "rita.api.v1.workflow.commentary._handle_overview",
                return_value=_overview_handler_result(),
            ), patch(
                "rita.repositories.commentary_log.CommentaryLogRepository.create",
                return_value=MagicMock(),
            ):
                resp = client.post("/api/v1/commentary", json={"app": "rita", "page": "overview"})
            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        finally:
            _clear(app, get_db)

    def test_overview_response_has_commentary_field(self):
        app, client, get_db = _client_with_mock_db()
        try:
            with patch(
                "rita.api.v1.workflow.commentary._handle_overview",
                return_value=_overview_handler_result(),
            ), patch(
                "rita.repositories.commentary_log.CommentaryLogRepository.create",
                return_value=MagicMock(),
            ):
                resp = client.post("/api/v1/commentary", json={"app": "rita", "page": "overview"})
            body = resp.json()
            assert "commentary" in body, "Response must include 'commentary'"
            assert isinstance(body["commentary"], str)
        finally:
            _clear(app, get_db)

    def test_overview_response_has_instruments_analyzed_field(self):
        app, client, get_db = _client_with_mock_db()
        try:
            with patch(
                "rita.api.v1.workflow.commentary._handle_overview",
                return_value=_overview_handler_result(),
            ), patch(
                "rita.repositories.commentary_log.CommentaryLogRepository.create",
                return_value=MagicMock(),
            ):
                resp = client.post("/api/v1/commentary", json={"app": "rita", "page": "overview"})
            body = resp.json()
            assert "instruments_analyzed" in body, "Response must include 'instruments_analyzed'"
            assert isinstance(body["instruments_analyzed"], list)
        finally:
            _clear(app, get_db)

    def test_overview_response_has_latency_ms_field(self):
        app, client, get_db = _client_with_mock_db()
        try:
            with patch(
                "rita.api.v1.workflow.commentary._handle_overview",
                return_value=_overview_handler_result(),
            ), patch(
                "rita.repositories.commentary_log.CommentaryLogRepository.create",
                return_value=MagicMock(),
            ):
                resp = client.post("/api/v1/commentary", json={"app": "rita", "page": "overview"})
            body = resp.json()
            assert "latency_ms" in body, "Response must include 'latency_ms'"
            assert isinstance(body["latency_ms"], (int, float))
        finally:
            _clear(app, get_db)

    def test_overview_response_has_app_field(self):
        app, client, get_db = _client_with_mock_db()
        try:
            with patch(
                "rita.api.v1.workflow.commentary._handle_overview",
                return_value=_overview_handler_result(),
            ), patch(
                "rita.repositories.commentary_log.CommentaryLogRepository.create",
                return_value=MagicMock(),
            ):
                resp = client.post("/api/v1/commentary", json={"app": "rita", "page": "overview"})
            body = resp.json()
            assert "app" in body, "Response must include 'app'"
            assert body["app"] == "rita"
        finally:
            _clear(app, get_db)

    def test_overview_response_has_page_field(self):
        app, client, get_db = _client_with_mock_db()
        try:
            with patch(
                "rita.api.v1.workflow.commentary._handle_overview",
                return_value=_overview_handler_result(),
            ), patch(
                "rita.repositories.commentary_log.CommentaryLogRepository.create",
                return_value=MagicMock(),
            ):
                resp = client.post("/api/v1/commentary", json={"app": "rita", "page": "overview"})
            body = resp.json()
            assert "page" in body, "Response must include 'page'"
            assert body["page"] == "overview"
        finally:
            _clear(app, get_db)

    def test_overview_instruments_analyzed_is_list_of_strings(self):
        app, client, get_db = _client_with_mock_db()
        try:
            with patch(
                "rita.api.v1.workflow.commentary._handle_overview",
                return_value=_overview_handler_result(),
            ), patch(
                "rita.repositories.commentary_log.CommentaryLogRepository.create",
                return_value=MagicMock(),
            ):
                resp = client.post("/api/v1/commentary", json={"app": "rita", "page": "overview"})
            body = resp.json()
            for item in body["instruments_analyzed"]:
                assert isinstance(item, str), f"instruments_analyzed items must be str, got {type(item)}"
        finally:
            _clear(app, get_db)


class TestStrategyResponseShape:
    """Valid strategy request must return HTTP 200 with all 5 schema fields."""

    def test_strategy_returns_200(self):
        app, client, get_db = _client_with_mock_db()
        try:
            with patch(
                "rita.api.v1.workflow.commentary._handle_strategy",
                return_value=_strategy_handler_result(),
            ), patch(
                "rita.repositories.commentary_log.CommentaryLogRepository.create",
                return_value=MagicMock(),
            ):
                resp = client.post(
                    "/api/v1/commentary",
                    json={"app": "rita", "page": "strategy", "instrument": "NIFTY"},
                )
            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        finally:
            _clear(app, get_db)

    def test_strategy_response_all_five_fields_present(self):
        app, client, get_db = _client_with_mock_db()
        try:
            with patch(
                "rita.api.v1.workflow.commentary._handle_strategy",
                return_value=_strategy_handler_result(),
            ), patch(
                "rita.repositories.commentary_log.CommentaryLogRepository.create",
                return_value=MagicMock(),
            ):
                resp = client.post(
                    "/api/v1/commentary",
                    json={"app": "rita", "page": "strategy", "instrument": "NIFTY"},
                )
            body = resp.json()
            for field in ("commentary", "instruments_analyzed", "latency_ms", "app", "page"):
                assert field in body, f"Response missing '{field}': {list(body.keys())}"
        finally:
            _clear(app, get_db)


# ---------------------------------------------------------------------------
# 4. commentary field is always a string (never None)
# ---------------------------------------------------------------------------

class TestCommentaryAlwaysString:
    """commentary must be a non-None, non-empty string in all scenarios."""

    def test_commentary_is_string_on_success(self):
        app, client, get_db = _client_with_mock_db()
        try:
            with patch(
                "rita.api.v1.workflow.commentary._handle_overview",
                return_value=_overview_handler_result(),
            ), patch(
                "rita.repositories.commentary_log.CommentaryLogRepository.create",
                return_value=MagicMock(),
            ):
                resp = client.post("/api/v1/commentary", json={"app": "rita", "page": "overview"})
            body = resp.json()
            assert isinstance(body["commentary"], str), "commentary must be str"
            assert body["commentary"] is not None, "commentary must not be None"
        finally:
            _clear(app, get_db)

    def test_commentary_is_string_even_when_handler_raises(self):
        """When the handler raises an unexpected exception, the endpoint must
        catch it, return HTTP 200, and set commentary to a fallback string."""
        app, client, get_db = _client_with_mock_db()
        try:
            with patch(
                "rita.api.v1.workflow.commentary._handle_overview",
                side_effect=RuntimeError("simulated data error"),
            ), patch(
                "rita.repositories.commentary_log.CommentaryLogRepository.create",
                return_value=MagicMock(),
            ):
                resp = client.post("/api/v1/commentary", json={"app": "rita", "page": "overview"})
            assert resp.status_code == 200, (
                f"HTTP 500 must never be raised; got {resp.status_code}"
            )
            body = resp.json()
            assert isinstance(body["commentary"], str), "commentary must be str on error path"
            assert len(body["commentary"]) > 0, "commentary must not be empty string on error path"
        finally:
            _clear(app, get_db)

    def test_no_http_500_on_handler_error(self):
        """Endpoint MUST NOT return HTTP 500 even if the handler raises."""
        app, client, get_db = _client_with_mock_db()
        try:
            with patch(
                "rita.api.v1.workflow.commentary._handle_overview",
                side_effect=Exception("simulated crash"),
            ), patch(
                "rita.repositories.commentary_log.CommentaryLogRepository.create",
                return_value=MagicMock(),
            ):
                resp = client.post("/api/v1/commentary", json={"app": "rita", "page": "overview"})
            assert resp.status_code != 500, "Endpoint must never return HTTP 500"
        finally:
            _clear(app, get_db)


# ---------------------------------------------------------------------------
# 5. Monitor endpoint includes commentary KPIs
# ---------------------------------------------------------------------------

class TestMonitorIncludesCommentaryKPIs:
    """GET /api/v1/chat/monitor must include commentary_count, commentary_avg_latency_ms,
    commentary_error_count merged into the summary dict."""

    _KPI_KEYS = (
        "commentary_count",
        "commentary_avg_latency_ms",
        "commentary_error_count",
    )

    def _client_with_db(self, db_session):
        """Return (app, client, get_db) with a generator-style get_db override."""
        from rita.main import app
        from rita.database import get_db

        def _override():
            yield db_session

        app.dependency_overrides[get_db] = _override
        client = TestClient(app, raise_server_exceptions=False)
        return app, client, get_db

    def test_monitor_returns_200(self, db_session):
        app, client, get_db = self._client_with_db(db_session)
        try:
            resp = client.get("/api/v1/chat/monitor")
            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        finally:
            app.dependency_overrides.pop(get_db, None)

    def test_monitor_summary_has_commentary_count(self, db_session):
        app, client, get_db = self._client_with_db(db_session)
        try:
            resp = client.get("/api/v1/chat/monitor")
            body = resp.json()
            assert "summary" in body
            assert "commentary_count" in body["summary"], (
                f"'commentary_count' missing from monitor summary; keys: {list(body['summary'].keys())}"
            )
        finally:
            app.dependency_overrides.pop(get_db, None)

    def test_monitor_summary_has_commentary_avg_latency_ms(self, db_session):
        app, client, get_db = self._client_with_db(db_session)
        try:
            resp = client.get("/api/v1/chat/monitor")
            body = resp.json()
            assert "commentary_avg_latency_ms" in body["summary"], (
                f"'commentary_avg_latency_ms' missing from monitor summary"
            )
        finally:
            app.dependency_overrides.pop(get_db, None)

    def test_monitor_summary_has_commentary_error_count(self, db_session):
        app, client, get_db = self._client_with_db(db_session)
        try:
            resp = client.get("/api/v1/chat/monitor")
            body = resp.json()
            assert "commentary_error_count" in body["summary"], (
                f"'commentary_error_count' missing from monitor summary"
            )
        finally:
            app.dependency_overrides.pop(get_db, None)

    def test_monitor_commentary_kpis_are_numeric_on_empty_db(self, db_session):
        """With zero commentary logs, KPIs must be 0/0.0, not None or missing."""
        app, client, get_db = self._client_with_db(db_session)
        try:
            resp = client.get("/api/v1/chat/monitor")
            body = resp.json()
            summary = body["summary"]
            assert isinstance(summary["commentary_count"], int)
            assert isinstance(summary["commentary_avg_latency_ms"], (int, float))
            assert isinstance(summary["commentary_error_count"], int)
            assert summary["commentary_count"] == 0
            assert summary["commentary_error_count"] == 0
        finally:
            app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# 6. CommentaryLogRepository.get_summary() — correct dict keys
# ---------------------------------------------------------------------------

class TestCommentaryLogRepositoryGetSummary:
    """Unit tests for CommentaryLogRepository.get_summary() on a real in-memory DB."""

    def test_get_summary_returns_dict_with_all_keys(self, db_session):
        from rita.repositories.commentary_log import CommentaryLogRepository

        repo = CommentaryLogRepository(db_session)
        result = repo.get_summary()
        assert isinstance(result, dict)
        assert "commentary_count" in result, f"Missing key 'commentary_count', got {list(result.keys())}"
        assert "commentary_avg_latency_ms" in result, f"Missing key 'commentary_avg_latency_ms'"
        assert "commentary_error_count" in result, f"Missing key 'commentary_error_count'"

    def test_get_summary_empty_db_returns_zeros(self, db_session):
        from rita.repositories.commentary_log import CommentaryLogRepository

        repo = CommentaryLogRepository(db_session)
        result = repo.get_summary()
        assert result["commentary_count"] == 0
        assert result["commentary_avg_latency_ms"] == 0.0
        assert result["commentary_error_count"] == 0

    def test_get_summary_counts_log_entries(self, db_session):
        from rita.repositories.commentary_log import CommentaryLogRepository
        from rita.schemas.commentary import CommentaryLogCreate

        repo = CommentaryLogRepository(db_session)

        # Insert 2 ok + 1 error log entries
        for i in range(2):
            repo.create(CommentaryLogCreate(
                id=f"id-ok-{i}",
                app="rita",
                page="overview",
                instrument=None,
                latency_ms=50.0 + i * 10,
                status="ok",
                commentary_preview="preview text",
                timestamp=datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc),
            ))
        repo.create(CommentaryLogCreate(
            id="id-err-0",
            app="rita",
            page="overview",
            instrument=None,
            latency_ms=120.0,
            status="error",
            commentary_preview="error preview",
            timestamp=datetime(2026, 5, 15, 12, 1, 0, tzinfo=timezone.utc),
        ))

        result = repo.get_summary()
        assert result["commentary_count"] == 3
        assert result["commentary_error_count"] == 1

    def test_get_summary_avg_latency_is_correct(self, db_session):
        from rita.repositories.commentary_log import CommentaryLogRepository
        from rita.schemas.commentary import CommentaryLogCreate

        repo = CommentaryLogRepository(db_session)
        latencies = [100.0, 200.0]
        for i, lat in enumerate(latencies):
            repo.create(CommentaryLogCreate(
                id=f"lat-{i}",
                app="rita",
                page="overview",
                instrument=None,
                latency_ms=lat,
                status="ok",
                commentary_preview="preview",
                timestamp=datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc),
            ))

        result = repo.get_summary()
        assert result["commentary_avg_latency_ms"] == 150.0, (
            f"Expected avg 150.0, got {result['commentary_avg_latency_ms']}"
        )

    def test_get_summary_values_are_correct_types(self, db_session):
        from rita.repositories.commentary_log import CommentaryLogRepository

        repo = CommentaryLogRepository(db_session)
        result = repo.get_summary()
        assert isinstance(result["commentary_count"], int)
        assert isinstance(result["commentary_avg_latency_ms"], float)
        assert isinstance(result["commentary_error_count"], int)


# ---------------------------------------------------------------------------
# 7. API-frontend contract verification
# ---------------------------------------------------------------------------

class TestAPIFrontendContract:
    """Verify schema field names exactly match what commentary.js and export.js read.

    commentary.js line 79:  (res && res.commentary) ? res.commentary : '—'
    export.js line 82:      commentaryResult.value?.commentary
    JS does not directly read res.instruments_analyzed, res.latency_ms,
    res.app, or res.page — but those fields are validated below as part of the
    CommentaryResponse schema contract so any rename is caught early.
    """

    def test_contract_commentary_field_name(self):
        """JS reads res.commentary — must be exactly 'commentary' (not 'text', 'body', etc.)."""
        app, client, get_db = _client_with_mock_db()
        try:
            with patch(
                "rita.api.v1.workflow.commentary._handle_overview",
                return_value=_overview_handler_result(),
            ), patch(
                "rita.repositories.commentary_log.CommentaryLogRepository.create",
                return_value=MagicMock(),
            ):
                resp = client.post("/api/v1/commentary", json={"app": "rita", "page": "overview"})
            body = resp.json()
            # JS: res.commentary
            assert "commentary" in body, (
                "FIELD MISMATCH: JS reads res.commentary but key not found in response"
            )
            assert isinstance(body["commentary"], str)
            assert len(body["commentary"]) > 0
        finally:
            _clear(app, get_db)

    def test_contract_instruments_analyzed_field_name(self):
        """Schema field 'instruments_analyzed' must be present in response."""
        app, client, get_db = _client_with_mock_db()
        try:
            with patch(
                "rita.api.v1.workflow.commentary._handle_overview",
                return_value=_overview_handler_result(),
            ), patch(
                "rita.repositories.commentary_log.CommentaryLogRepository.create",
                return_value=MagicMock(),
            ):
                resp = client.post("/api/v1/commentary", json={"app": "rita", "page": "overview"})
            body = resp.json()
            # Schema: instruments_analyzed: list[str]
            assert "instruments_analyzed" in body, (
                "FIELD MISMATCH: 'instruments_analyzed' not found in response"
            )
            assert isinstance(body["instruments_analyzed"], list)
        finally:
            _clear(app, get_db)

    def test_contract_latency_ms_field_name(self):
        """Schema field 'latency_ms' must be present in response."""
        app, client, get_db = _client_with_mock_db()
        try:
            with patch(
                "rita.api.v1.workflow.commentary._handle_overview",
                return_value=_overview_handler_result(),
            ), patch(
                "rita.repositories.commentary_log.CommentaryLogRepository.create",
                return_value=MagicMock(),
            ):
                resp = client.post("/api/v1/commentary", json={"app": "rita", "page": "overview"})
            body = resp.json()
            # Schema: latency_ms: float
            assert "latency_ms" in body, (
                "FIELD MISMATCH: 'latency_ms' not found in response"
            )
            assert isinstance(body["latency_ms"], (int, float))
            assert body["latency_ms"] >= 0
        finally:
            _clear(app, get_db)

    def test_contract_app_field_name(self):
        """Schema field 'app' echoes the request value."""
        app, client, get_db = _client_with_mock_db()
        try:
            with patch(
                "rita.api.v1.workflow.commentary._handle_overview",
                return_value=_overview_handler_result(),
            ), patch(
                "rita.repositories.commentary_log.CommentaryLogRepository.create",
                return_value=MagicMock(),
            ):
                resp = client.post("/api/v1/commentary", json={"app": "rita", "page": "overview"})
            body = resp.json()
            # Schema: app: str
            assert "app" in body, "FIELD MISMATCH: 'app' not found in response"
            assert body["app"] == "rita"
        finally:
            _clear(app, get_db)

    def test_contract_page_field_name(self):
        """Schema field 'page' echoes the request value."""
        app, client, get_db = _client_with_mock_db()
        try:
            with patch(
                "rita.api.v1.workflow.commentary._handle_overview",
                return_value=_overview_handler_result(),
            ), patch(
                "rita.repositories.commentary_log.CommentaryLogRepository.create",
                return_value=MagicMock(),
            ):
                resp = client.post("/api/v1/commentary", json={"app": "rita", "page": "overview"})
            body = resp.json()
            # Schema: page: str
            assert "page" in body, "FIELD MISMATCH: 'page' not found in response"
            assert body["page"] == "overview"
        finally:
            _clear(app, get_db)

    def test_contract_strategy_commentary_field_for_export_js(self):
        """export.js line 82 reads commentaryResult.value?.commentary —
        verify strategy response also has the commentary field."""
        app, client, get_db = _client_with_mock_db()
        try:
            with patch(
                "rita.api.v1.workflow.commentary._handle_strategy",
                return_value=_strategy_handler_result(),
            ), patch(
                "rita.repositories.commentary_log.CommentaryLogRepository.create",
                return_value=MagicMock(),
            ):
                resp = client.post(
                    "/api/v1/commentary",
                    json={"app": "rita", "page": "strategy", "instrument": "NIFTY"},
                )
            body = resp.json()
            # export.js: commentaryResult.value?.commentary
            assert "commentary" in body, (
                "FIELD MISMATCH: export.js reads .commentary but field not found in strategy response"
            )
            assert isinstance(body["commentary"], str)
        finally:
            _clear(app, get_db)
