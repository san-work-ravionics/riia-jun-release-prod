"""Unit tests for the API Metrics feature.

Covers:
  - ApiCallLogRepository.aggregate_by_path_method — happy path + edge cases
  - GET /api/experience/ops/api-metrics — response shape vs schema contract
  - API-frontend contract check (schema fields vs JS r.field reads)

Edge cases from Architect spec:
  1. Empty api_call_log table → items=[] returned
  2. All errors (all status_code >= 400) → error_rate_pct = 100.0
  3. Single row → call_count=1, p50/p95 both = that row's duration
  4. Null duration_ms rows → p50_ms and p95_ms are None (Optional[float])
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# ---------------------------------------------------------------------------
# Config-path patch — must happen before rita imports (mirrors conftest.py)
# ---------------------------------------------------------------------------
import rita.config as _rita_config

_rita_config._CONFIG_DIR = Path(__file__).parent.parent.parent / "config"
_rita_config.get_settings.cache_clear()

from rita.database import Base, get_db  # noqa: E402
import rita.models  # noqa: F401 — registers all ORM models with Base.metadata
from rita.models.api_call_log import ApiCallLogModel  # noqa: E402
from rita.repositories.api_call_log import ApiCallLogRepository  # noqa: E402
from rita.schemas.api_metrics import ApiMetricsResponse, ApiMetricsRow  # noqa: E402


# ---------------------------------------------------------------------------
# Shared in-memory DB fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def db_session():
    """Isolated in-memory SQLite session; tables created fresh per test."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def _insert_row(
    session,
    path: str,
    method: str,
    status_code: int | None,
    duration_ms: float | None,
    called_at: datetime | None = None,
):
    """Helper: insert a raw ApiCallLogModel row without going through the repo create()."""
    if called_at is None:
        called_at = datetime(2026, 5, 17, 10, 0, 0)
    row = ApiCallLogModel(
        path=path,
        method=method,
        status_code=status_code,
        duration_ms=duration_ms,
        called_at=called_at,
    )
    session.add(row)
    session.commit()
    return row


# ===========================================================================
# 1. ApiCallLogRepository unit tests (pure Python, no HTTP)
# ===========================================================================

class TestApiCallLogRepositoryAggregation:
    """Verify aggregate_by_path_method produces correct aggregates."""

    # ── Happy path: multiple rows, correct p50/p95 calculation ────────────

    def test_happy_path_multiple_rows_correct_aggregates(self, db_session):
        """Five GET /api/v1/test calls: call_count=5, p50/p95 computed correctly."""
        durations = [10.0, 20.0, 30.0, 40.0, 50.0]
        for i, d in enumerate(durations):
            _insert_row(
                db_session,
                path="/api/v1/test",
                method="GET",
                status_code=200,
                duration_ms=d,
                called_at=datetime(2026, 5, 17, 10, i, 0),
            )

        repo = ApiCallLogRepository(db_session)
        result = repo.aggregate_by_path_method()

        assert len(result) == 1
        row = result[0]
        assert row["path"] == "/api/v1/test"
        assert row["method"] == "GET"
        assert row["call_count"] == 5
        assert row["error_count"] == 0
        assert row["error_rate_pct"] == 0.0

        # p50: sorted index n//2 = 5//2 = 2 → 30.0
        assert row["p50_ms"] == 30.0
        # p95: sorted index int(5 * 0.95) = 4 → 50.0
        assert row["p95_ms"] == 50.0

    def test_happy_path_two_distinct_endpoints(self, db_session):
        """Two distinct path+method pairs produce two separate aggregate rows."""
        _insert_row(db_session, "/api/v1/a", "GET", 200, 100.0)
        _insert_row(db_session, "/api/v1/a", "GET", 200, 200.0)
        _insert_row(db_session, "/api/v1/b", "POST", 201, 50.0)

        repo = ApiCallLogRepository(db_session)
        result = repo.aggregate_by_path_method()

        assert len(result) == 2
        paths = {r["path"] for r in result}
        assert paths == {"/api/v1/a", "/api/v1/b"}

        row_a = next(r for r in result if r["path"] == "/api/v1/a")
        assert row_a["call_count"] == 2
        row_b = next(r for r in result if r["path"] == "/api/v1/b")
        assert row_b["call_count"] == 1

    def test_result_sorted_by_call_count_descending(self, db_session):
        """Results are returned sorted by call_count descending."""
        for _ in range(3):
            _insert_row(db_session, "/api/v1/busy", "GET", 200, 10.0)
        _insert_row(db_session, "/api/v1/quiet", "GET", 200, 10.0)

        repo = ApiCallLogRepository(db_session)
        result = repo.aggregate_by_path_method()

        assert result[0]["path"] == "/api/v1/busy"
        assert result[0]["call_count"] == 3
        assert result[1]["path"] == "/api/v1/quiet"
        assert result[1]["call_count"] == 1

    def test_error_count_and_error_rate_pct(self, db_session):
        """2 of 4 calls return 4xx — error_count=2, error_rate_pct=50.0."""
        _insert_row(db_session, "/api/v1/mixed", "GET", 200, 10.0)
        _insert_row(db_session, "/api/v1/mixed", "GET", 200, 20.0)
        _insert_row(db_session, "/api/v1/mixed", "GET", 400, 30.0)
        _insert_row(db_session, "/api/v1/mixed", "GET", 500, 40.0)

        repo = ApiCallLogRepository(db_session)
        result = repo.aggregate_by_path_method()

        assert len(result) == 1
        row = result[0]
        assert row["error_count"] == 2
        assert row["error_rate_pct"] == 50.0

    def test_last_called_at_is_isoformat_string(self, db_session):
        """last_called_at is an ISO-formatted string derived from max called_at."""
        _insert_row(db_session, "/api/v1/ts", "GET", 200, 10.0,
                    called_at=datetime(2026, 5, 17, 8, 0, 0))
        _insert_row(db_session, "/api/v1/ts", "GET", 200, 20.0,
                    called_at=datetime(2026, 5, 17, 9, 0, 0))

        repo = ApiCallLogRepository(db_session)
        result = repo.aggregate_by_path_method()

        assert result[0]["last_called_at"] == datetime(2026, 5, 17, 9, 0, 0).isoformat()

    # ── Edge case 1: Empty table ───────────────────────────────────────────

    def test_empty_table_returns_empty_list(self, db_session):
        """Edge case 1 (Architect): empty api_call_log table → result = []."""
        repo = ApiCallLogRepository(db_session)
        result = repo.aggregate_by_path_method()
        assert result == []

    # ── Edge case 2: All errors ────────────────────────────────────────────

    def test_all_errors_gives_100_pct_error_rate(self, db_session):
        """Edge case 2: all calls return 4xx/5xx → error_rate_pct = 100.0."""
        _insert_row(db_session, "/api/v1/fail", "GET", 500, 10.0)
        _insert_row(db_session, "/api/v1/fail", "GET", 404, 20.0)
        _insert_row(db_session, "/api/v1/fail", "GET", 400, 30.0)

        repo = ApiCallLogRepository(db_session)
        result = repo.aggregate_by_path_method()

        assert len(result) == 1
        row = result[0]
        assert row["error_count"] == 3
        assert row["error_rate_pct"] == 100.0

    # ── Edge case 3: Single row ────────────────────────────────────────────

    def test_single_row_p50_p95_equal_duration(self, db_session):
        """Edge case 3: single row → call_count=1, p50 and p95 both equal that duration."""
        _insert_row(db_session, "/api/v1/solo", "GET", 200, 42.5)

        repo = ApiCallLogRepository(db_session)
        result = repo.aggregate_by_path_method()

        assert len(result) == 1
        row = result[0]
        assert row["call_count"] == 1
        assert row["p50_ms"] == 42.5
        assert row["p95_ms"] == 42.5

    # ── Edge case 4: Null duration_ms ─────────────────────────────────────

    def test_null_duration_ms_yields_none_percentiles(self, db_session):
        """Edge case 4: duration_ms is None → p50_ms and p95_ms are None."""
        _insert_row(db_session, "/api/v1/nolatency", "GET", 200, None)

        repo = ApiCallLogRepository(db_session)
        result = repo.aggregate_by_path_method()

        assert len(result) == 1
        row = result[0]
        assert row["p50_ms"] is None
        assert row["p95_ms"] is None

    def test_mixed_null_and_non_null_duration(self, db_session):
        """Rows with null duration are excluded from percentile calculation."""
        _insert_row(db_session, "/api/v1/mixed-dur", "GET", 200, None)
        _insert_row(db_session, "/api/v1/mixed-dur", "GET", 200, 50.0)
        _insert_row(db_session, "/api/v1/mixed-dur", "GET", 200, None)

        repo = ApiCallLogRepository(db_session)
        result = repo.aggregate_by_path_method()

        assert len(result) == 1
        row = result[0]
        assert row["call_count"] == 3
        # Only one duration value (50.0) → p50 = p95 = 50.0
        assert row["p50_ms"] == 50.0
        assert row["p95_ms"] == 50.0

    # ── Filter: method_filter ──────────────────────────────────────────────

    def test_method_filter_returns_only_matching_method(self, db_session):
        """method_filter='GET' excludes POST rows."""
        _insert_row(db_session, "/api/v1/x", "GET", 200, 10.0)
        _insert_row(db_session, "/api/v1/x", "POST", 201, 20.0)

        repo = ApiCallLogRepository(db_session)
        result = repo.aggregate_by_path_method(method_filter="GET")

        assert len(result) == 1
        assert result[0]["method"] == "GET"

    def test_method_filter_is_case_insensitive(self, db_session):
        """method_filter='get' (lowercase) should match 'GET' rows."""
        _insert_row(db_session, "/api/v1/ci", "GET", 200, 10.0)

        repo = ApiCallLogRepository(db_session)
        result = repo.aggregate_by_path_method(method_filter="get")

        assert len(result) == 1
        assert result[0]["method"] == "GET"

    # ── Filter: path_prefix ────────────────────────────────────────────────

    def test_path_prefix_filter_limits_results(self, db_session):
        """path_prefix='/api/v1/ops' only returns paths that start with that prefix."""
        _insert_row(db_session, "/api/v1/ops/status", "GET", 200, 10.0)
        _insert_row(db_session, "/api/v1/rita/health", "GET", 200, 20.0)

        repo = ApiCallLogRepository(db_session)
        result = repo.aggregate_by_path_method(path_prefix="/api/v1/ops")

        assert len(result) == 1
        assert result[0]["path"] == "/api/v1/ops/status"


# ===========================================================================
# 2. Schema unit tests (no HTTP, pure Python)
# ===========================================================================

class TestApiMetricsSchema:
    """Verify ApiMetricsRow and ApiMetricsResponse Pydantic models."""

    def test_api_metrics_row_all_8_fields_present(self):
        """ApiMetricsRow must declare exactly 8 fields per Architect contract."""
        fields = set(ApiMetricsRow.model_fields.keys())
        expected = {
            "path", "method", "call_count",
            "p50_ms", "p95_ms",
            "error_count", "error_rate_pct", "last_called_at",
        }
        assert expected == fields, (
            f"Field mismatch: expected={expected}, got={fields}"
        )

    def test_api_metrics_row_optional_fields(self):
        """p50_ms, p95_ms, last_called_at are Optional — should accept None."""
        row = ApiMetricsRow(
            path="/api/v1/test",
            method="GET",
            call_count=5,
            p50_ms=None,
            p95_ms=None,
            error_count=0,
            error_rate_pct=0.0,
            last_called_at=None,
        )
        assert row.p50_ms is None
        assert row.p95_ms is None
        assert row.last_called_at is None

    def test_api_metrics_row_instantiation_with_full_data(self):
        row = ApiMetricsRow(
            path="/api/v1/test",
            method="GET",
            call_count=10,
            p50_ms=25.5,
            p95_ms=98.0,
            error_count=1,
            error_rate_pct=10.0,
            last_called_at="2026-05-17T10:00:00",
        )
        assert row.path == "/api/v1/test"
        assert row.method == "GET"
        assert row.call_count == 10
        assert row.p50_ms == 25.5
        assert row.p95_ms == 98.0
        assert row.error_count == 1
        assert row.error_rate_pct == 10.0
        assert row.last_called_at == "2026-05-17T10:00:00"

    def test_api_metrics_response_wraps_items_list(self):
        resp = ApiMetricsResponse(items=[])
        assert resp.items == []

    def test_api_metrics_response_with_items(self):
        row = ApiMetricsRow(
            path="/api/v1/x", method="GET", call_count=1,
            p50_ms=10.0, p95_ms=10.0, error_count=0,
            error_rate_pct=0.0, last_called_at=None,
        )
        resp = ApiMetricsResponse(items=[row])
        assert len(resp.items) == 1
        assert resp.items[0].path == "/api/v1/x"


# ===========================================================================
# 3. Endpoint tests (HTTP via TestClient, in-memory DB)
# ===========================================================================

class TestApiMetricsEndpoint:
    """Test GET /api/experience/ops/api-metrics via FastAPI TestClient."""

    @pytest.fixture(autouse=True)
    def _setup_client(self, db_session):
        """Override get_db with the in-memory session; skip auth."""
        from unittest.mock import patch as _patch
        import pandas as _pd

        from fastapi.testclient import TestClient
        from rita.auth import get_current_user
        from rita.main import app

        _empty_df = _pd.DataFrame({
            "date": _pd.Series([], dtype="datetime64[ns]"),
            "close": _pd.Series([], dtype=float),
            "open": _pd.Series([], dtype=float),
            "high": _pd.Series([], dtype=float),
            "low": _pd.Series([], dtype=float),
            "volume": _pd.Series([], dtype=float),
        })

        def override_get_db():
            yield db_session

        app.dependency_overrides[get_current_user] = lambda: "test-user"
        app.dependency_overrides[get_db] = override_get_db

        with _patch("pandas.read_csv", return_value=_empty_df):
            with TestClient(app) as c:
                self.client = c
                self.db_session = db_session
                yield

        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_db, None)

    # ── Test 1: Empty table → 200 with items=[] ────────────────────────────

    def test_empty_table_returns_200_with_empty_items(self):
        """Edge case 1 (Architect): no rows in db → items=[] with HTTP 200."""
        resp = self.client.get("/api/experience/ops/api-metrics")
        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert body["items"] == []

    # ── Test 2: Happy path response shape matches schema ───────────────────

    def test_happy_path_response_shape_matches_schema(self):
        """Response items have exactly the 8 contracted schema fields."""
        _insert_row(self.db_session, "/api/v1/test", "GET", 200, 50.0)
        _insert_row(self.db_session, "/api/v1/test", "GET", 200, 100.0)

        resp = self.client.get("/api/experience/ops/api-metrics")
        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert len(body["items"]) == 1

        row = body["items"][0]
        expected_fields = {
            "path", "method", "call_count",
            "p50_ms", "p95_ms",
            "error_count", "error_rate_pct", "last_called_at",
        }
        assert expected_fields == set(row.keys()), (
            f"Response row keys mismatch: expected={expected_fields}, got={set(row.keys())}"
        )

    def test_response_values_are_correct_types(self):
        """call_count is int, p50_ms/p95_ms are float, error_rate_pct is float."""
        _insert_row(self.db_session, "/api/v1/typed", "GET", 200, 30.0)

        resp = self.client.get("/api/experience/ops/api-metrics")
        assert resp.status_code == 200
        row = resp.json()["items"][0]

        assert isinstance(row["call_count"], int)
        assert isinstance(row["error_count"], int)
        assert isinstance(row["error_rate_pct"], float)
        assert isinstance(row["p50_ms"], float)
        assert isinstance(row["p95_ms"], float)

    # ── Test 3: method query param filters results ─────────────────────────

    def test_method_query_param_filters(self):
        """?method=GET returns only GET rows."""
        _insert_row(self.db_session, "/api/v1/filter", "GET", 200, 10.0)
        _insert_row(self.db_session, "/api/v1/filter", "POST", 201, 20.0)

        resp = self.client.get("/api/experience/ops/api-metrics", params={"method": "GET"})
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert all(r["method"] == "GET" for r in items)

    # ── Test 4: path_prefix query param filters results ───────────────────

    def test_path_prefix_query_param_filters(self):
        """?path_prefix=/api/v1/ops returns only matching paths."""
        _insert_row(self.db_session, "/api/v1/ops/status", "GET", 200, 10.0)
        _insert_row(self.db_session, "/api/v1/rita/health", "GET", 200, 20.0)

        resp = self.client.get(
            "/api/experience/ops/api-metrics",
            params={"path_prefix": "/api/v1/ops"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["path"] == "/api/v1/ops/status"

    # ── Test 5: null p50_ms/p95_ms are serialised as null in JSON ─────────

    def test_null_duration_serialised_as_null(self):
        """Rows with null duration_ms → p50_ms and p95_ms are null in response."""
        _insert_row(self.db_session, "/api/v1/nulldur", "GET", 200, None)

        resp = self.client.get("/api/experience/ops/api-metrics")
        assert resp.status_code == 200
        row = resp.json()["items"][0]
        assert row["p50_ms"] is None
        assert row["p95_ms"] is None

    # ── Test 6: Endpoint is read-only — no db.commit in handler ───────────

    def test_endpoint_is_read_only(self):
        """Experience tier: GET /api-metrics handler must not call db.commit()."""
        import inspect
        from rita.api.experience.ops import get_api_metrics

        source = inspect.getsource(get_api_metrics)
        assert "db.commit()" not in source, (
            "get_api_metrics must not call db.commit() — experience tier is read-only"
        )

    # ── Test 7: limit param is respected ──────────────────────────────────

    def test_limit_param_caps_rows_fetched(self):
        """?limit=1 should return at most one aggregate row."""
        _insert_row(self.db_session, "/api/v1/a", "GET", 200, 10.0)
        _insert_row(self.db_session, "/api/v1/b", "GET", 200, 20.0)

        resp = self.client.get("/api/experience/ops/api-metrics", params={"limit": 1})
        assert resp.status_code == 200
        # limit=1 means the repo fetches at most 1 raw row, which produces ≤1 aggregate
        assert len(resp.json()["items"]) <= 1


# ===========================================================================
# 4. API-frontend contract check (static verification)
# ===========================================================================

class TestApiMetricsContractCheck:
    """FC-004: every field the JS r.field reads must exist in ApiMetricsRow schema."""

    # All r.field accesses found in dashboard/js/ops/api-metrics.js:
    #   r.method      (filterApiMetrics line 24)
    #   r.path        (filterApiMetrics line 25, renderMetrics tbody)
    #   r.call_count  (renderMetrics reduce + tbody)
    #   r.error_count (renderMetrics reduce + tbody)
    #   r.p50_ms      (renderMetrics tbody)
    #   r.p95_ms      (renderMetrics tbody)
    #   r.error_rate_pct (renderMetrics tbody)
    # data.items      (loadApiMetrics line 9 — top-level wrapper field)
    JS_R_FIELD_READS = {
        "path",
        "method",
        "call_count",
        "p50_ms",
        "p95_ms",
        "error_count",
        "error_rate_pct",
    }

    JS_DATA_FIELD_READS = {"items"}  # data.items on ApiMetricsResponse

    def test_all_js_row_fields_present_in_schema(self):
        """Every r.field accessed in api-metrics.js must be declared in ApiMetricsRow."""
        schema_fields = set(ApiMetricsRow.model_fields.keys())
        missing = self.JS_R_FIELD_READS - schema_fields
        assert not missing, (
            f"CONTRACT MISMATCH — JS reads fields not in ApiMetricsRow schema: {missing}"
        )

    def test_all_js_data_fields_present_in_response_schema(self):
        """data.items must be declared in ApiMetricsResponse."""
        response_fields = set(ApiMetricsResponse.model_fields.keys())
        missing = self.JS_DATA_FIELD_READS - response_fields
        assert not missing, (
            f"CONTRACT MISMATCH — JS reads data.{missing} not in ApiMetricsResponse"
        )

    def test_last_called_at_in_schema_but_not_rendered_in_js(self):
        """Schema sends last_called_at but JS doesn't render it — this is acceptable."""
        schema_fields = set(ApiMetricsRow.model_fields.keys())
        # last_called_at is in schema
        assert "last_called_at" in schema_fields
        # but NOT in JS reads (JS omits it from the tbody columns) — that's fine
        assert "last_called_at" not in self.JS_R_FIELD_READS

    def test_contract_table_all_matches(self):
        """
        FC-004 contract table:
        Schema field      | JS r.field read | Match?
        ------------------|-----------------|-------
        path              | r.path          | YES
        method            | r.method        | YES
        call_count        | r.call_count    | YES
        p50_ms            | r.p50_ms        | YES
        p95_ms            | r.p95_ms        | YES
        error_count       | r.error_count   | YES
        error_rate_pct    | r.error_rate_pct| YES
        last_called_at    | (not read)      | n/a — server extra field, OK
        """
        schema_fields = set(ApiMetricsRow.model_fields.keys())
        mismatches = []
        for field in self.JS_R_FIELD_READS:
            if field not in schema_fields:
                mismatches.append(field)
        assert not mismatches, f"JS reads fields absent from schema: {mismatches}"


# ===========================================================================
# 5. FC-IMP import check (named exports in source modules)
# ===========================================================================

class TestFCImpImportCheck:
    """Verify named imports used by api-metrics.js exist in their source modules.

    api-metrics.js imports:
      - { api }    from './api.js'
      - { setEl }  from './utils.js'
    """

    def test_setEl_export_present_in_ops_utils_js(self):
        """setEl must be exported from dashboard/js/ops/utils.js."""
        utils_path = (
            Path(__file__).parent.parent.parent
            / "dashboard" / "js" / "ops" / "utils.js"
        )
        assert utils_path.exists(), f"utils.js not found at {utils_path}"
        content = utils_path.read_text(encoding="utf-8")
        # Accept either a local definition or a named re-export from shared/utils.js
        assert ("export function setEl(" in content or "export {" in content and "setEl" in content), (
            "setEl is not exported from dashboard/js/ops/utils.js — FC-IMP FAIL"
        )

    def test_api_export_present_in_ops_api_js(self):
        """api must be exported from dashboard/js/ops/api.js."""
        api_path = (
            Path(__file__).parent.parent.parent
            / "dashboard" / "js" / "ops" / "api.js"
        )
        assert api_path.exists(), f"api.js not found at {api_path}"
        content = api_path.read_text(encoding="utf-8")
        # Accept both named export and default export patterns
        assert "export" in content and "api" in content, (
            "api export not found in dashboard/js/ops/api.js — FC-IMP FAIL"
        )
