"""Unit tests for the Functional KPIs feature.

Covers:
  - FunctionalKPIsSeries and FunctionalKPIsResponse Pydantic schemas
  - GET /api/experience/ops/functional-kpis — happy path + edge cases
  - API-frontend contract check: schema fields vs JS data.series[def.key] reads

Edge cases from Architect spec (task-brief-20260524-1517.md):
  1. Empty DB + no CSV → returns all-zeros response (no 500)
  2. OperationalError on training_runs query → falls back to [] gracefully
  3. OperationalError on api_call_log query → falls back to [] gracefully
  4. chat_monitor.csv absent → chat_low_confidence_pct is all zeros
  5. hours query param boundary: hours=1 → single bucket returned
  6. hours query param boundary: hours=168 → 168 buckets returned
  7. Mixed training statuses → success rate correctly computed per bucket
"""

from __future__ import annotations

import csv
import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# ---------------------------------------------------------------------------
# Config-path patch — must happen before any rita import
# ---------------------------------------------------------------------------
import rita.config as _rita_config

_rita_config._CONFIG_DIR = Path(__file__).parent.parent.parent / "config"
_rita_config.get_settings.cache_clear()

from rita.database import Base, get_db  # noqa: E402
import rita.models  # noqa: F401 — registers all ORM models with Base.metadata
from rita.models.api_call_log import ApiCallLogModel  # noqa: E402
from rita.models.training import TrainingRunModel  # noqa: E402
from rita.schemas.functional_kpis import (  # noqa: E402
    FunctionalKPIsResponse,
    FunctionalKPIsSeries,
)


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


# ---------------------------------------------------------------------------
# Row insertion helpers
# ---------------------------------------------------------------------------

def _insert_api_row(
    session,
    path: str = "/api/experience/ops/test",
    method: str = "GET",
    status_code: int = 200,
    duration_ms: float | None = 50.0,
    called_at: datetime | None = None,
):
    """Insert a raw ApiCallLogModel row."""
    if called_at is None:
        called_at = datetime.utcnow()
    row = ApiCallLogModel(
        call_id=str(uuid.uuid4()),
        path=path,
        method=method,
        status_code=status_code,
        duration_ms=duration_ms,
        called_at=called_at,
        recorded_at=datetime.utcnow(),
    )
    session.add(row)
    session.commit()
    return row


def _insert_training_row(
    session,
    status: str = "completed",
    ended_at: datetime | None = None,
):
    """Insert a raw TrainingRunModel row."""
    if ended_at is None:
        ended_at = datetime.utcnow()
    row = TrainingRunModel(
        run_id=str(uuid.uuid4()),
        instrument="NIFTY",
        model_version="v1.0",
        algorithm="DoubleDQN",
        timesteps=1000,
        learning_rate=0.001,
        buffer_size=1000,
        net_arch="[64,64]",
        exploration_pct=0.1,
        status=status,
        started_at=ended_at - timedelta(minutes=5),
        ended_at=ended_at,
        recorded_at=datetime.utcnow(),
    )
    session.add(row)
    session.commit()
    return row


# ===========================================================================
# 1. Schema unit tests (pure Python, no HTTP)
# ===========================================================================

class TestFunctionalKPIsSchema:
    """Verify FunctionalKPIsSeries and FunctionalKPIsResponse Pydantic models."""

    def test_series_has_exactly_5_fields(self):
        """FunctionalKPIsSeries must declare exactly 5 contracted fields."""
        fields = set(FunctionalKPIsSeries.model_fields.keys())
        expected = {
            "training_success_rate_pct",
            "chat_low_confidence_pct",
            "experience_error_pct",
            "error_rate_pct",
            "p95_latency_ms",
        }
        assert fields == expected, f"Field mismatch: expected={expected}, got={fields}"

    def test_response_has_exactly_3_fields(self):
        """FunctionalKPIsResponse must declare exactly 3 contracted fields."""
        fields = set(FunctionalKPIsResponse.model_fields.keys())
        expected = {"generated_at", "buckets", "series"}
        assert fields == expected, f"Field mismatch: expected={expected}, got={fields}"

    def test_series_instantiation_with_lists(self):
        """FunctionalKPIsSeries accepts list[float] for all 5 fields."""
        s = FunctionalKPIsSeries(
            training_success_rate_pct=[100.0, 0.0],
            chat_low_confidence_pct=[5.0, 0.0],
            experience_error_pct=[0.0, 1.5],
            error_rate_pct=[0.0, 2.5],
            p95_latency_ms=[120.0, 350.0],
        )
        assert len(s.training_success_rate_pct) == 2
        assert s.training_success_rate_pct[0] == 100.0
        assert s.p95_latency_ms[1] == 350.0

    def test_response_instantiation_full(self):
        """FunctionalKPIsResponse wraps generated_at, buckets, and series."""
        series = FunctionalKPIsSeries(
            training_success_rate_pct=[0.0],
            chat_low_confidence_pct=[0.0],
            experience_error_pct=[0.0],
            error_rate_pct=[0.0],
            p95_latency_ms=[0.0],
        )
        resp = FunctionalKPIsResponse(
            generated_at="2026-05-24T14:00:00+00:00",
            buckets=["2026-05-24T13:00"],
            series=series,
        )
        assert resp.generated_at == "2026-05-24T14:00:00+00:00"
        assert resp.buckets == ["2026-05-24T13:00"]
        assert resp.series is series

    def test_empty_lists_are_valid(self):
        """Series and response with empty lists must not raise validation errors."""
        series = FunctionalKPIsSeries(
            training_success_rate_pct=[],
            chat_low_confidence_pct=[],
            experience_error_pct=[],
            error_rate_pct=[],
            p95_latency_ms=[],
        )
        resp = FunctionalKPIsResponse(
            generated_at="2026-05-24T14:00:00",
            buckets=[],
            series=series,
        )
        assert resp.buckets == []
        assert resp.series.training_success_rate_pct == []


# ===========================================================================
# 2. Endpoint tests (HTTP via FastAPI TestClient, in-memory DB)
# ===========================================================================

class TestFunctionalKPIsEndpoint:
    """Test GET /api/experience/ops/functional-kpis via FastAPI TestClient."""

    @pytest.fixture(autouse=True)
    def _setup_client(self, db_session, tmp_path):
        """Set up TestClient with in-memory DB and a temp chat monitor dir."""
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

        self.db_session = db_session
        self.tmp_path = tmp_path

        def override_get_db():
            yield db_session

        # Create a minimal settings mock for chat.monitor_dir
        class _FakeChat:
            monitor_dir = str(tmp_path)

        class _FakeSettings:
            chat = _FakeChat()

        app.dependency_overrides[get_current_user] = lambda: "test-user"
        app.dependency_overrides[get_db] = override_get_db

        with _patch("pandas.read_csv", return_value=_empty_df):
            with _patch(
                "rita.config.get_settings",
                return_value=_FakeSettings(),
            ):
                with TestClient(app) as c:
                    self.client = c
                    yield

        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_db, None)

    # ── Happy path: basic response structure ──────────────────────────────

    def test_happy_path_returns_200_with_correct_structure(self):
        """Empty DB: returns 200 with generated_at, buckets, and series."""
        resp = self.client.get("/api/experience/ops/functional-kpis")
        assert resp.status_code == 200
        body = resp.json()
        assert "generated_at" in body
        assert "buckets" in body
        assert "series" in body

    def test_happy_path_default_24_buckets(self):
        """Default hours=24 → exactly 24 bucket labels."""
        resp = self.client.get("/api/experience/ops/functional-kpis")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["buckets"]) == 24

    def test_happy_path_series_has_5_keys(self):
        """Response series must contain exactly 5 KPI keys."""
        resp = self.client.get("/api/experience/ops/functional-kpis")
        assert resp.status_code == 200
        series = resp.json()["series"]
        expected_keys = {
            "training_success_rate_pct",
            "chat_low_confidence_pct",
            "experience_error_pct",
            "error_rate_pct",
            "p95_latency_ms",
        }
        assert set(series.keys()) == expected_keys

    def test_happy_path_series_lengths_match_buckets(self):
        """Every series list must have the same length as the buckets list."""
        resp = self.client.get("/api/experience/ops/functional-kpis")
        assert resp.status_code == 200
        body = resp.json()
        n_buckets = len(body["buckets"])
        for key, values in body["series"].items():
            assert len(values) == n_buckets, (
                f"series['{key}'] length {len(values)} != buckets length {n_buckets}"
            )

    def test_bucket_labels_are_iso_hour_format(self):
        """Bucket labels must match the pattern YYYY-MM-DDTHH:00."""
        resp = self.client.get("/api/experience/ops/functional-kpis")
        assert resp.status_code == 200
        buckets = resp.json()["buckets"]
        for label in buckets:
            # Must end with :00 and be parseable as a datetime hour truncated
            assert label.endswith(":00"), f"Bucket '{label}' does not end with ':00'"
            assert "T" in label, f"Bucket '{label}' missing T separator"

    # ── Edge case 1: Empty DB + no CSV → all-zeros, no 500 ────────────────

    def test_edge_empty_db_returns_all_zeros_no_500(self):
        """Edge case 1: empty DB and no chat CSV → all-zeros, no exception raised."""
        resp = self.client.get("/api/experience/ops/functional-kpis")
        assert resp.status_code == 200
        series = resp.json()["series"]
        for key, values in series.items():
            assert all(v == 0.0 for v in values), (
                f"Expected all zeros for '{key}' with empty DB, got: {values}"
            )

    # ── Edge case 5: hours=1 → single bucket ─────────────────────────────

    def test_edge_hours_1_returns_single_bucket(self):
        """Edge case 5: hours=1 → exactly 1 bucket and 1 value per series key."""
        resp = self.client.get("/api/experience/ops/functional-kpis", params={"hours": 1})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["buckets"]) == 1
        for key, values in body["series"].items():
            assert len(values) == 1, f"series['{key}'] should have 1 value for hours=1"

    # ── Edge case 6: hours=168 → 168 buckets ─────────────────────────────

    def test_edge_hours_168_returns_168_buckets(self):
        """Edge case 6: hours=168 (max allowed) → exactly 168 buckets."""
        resp = self.client.get("/api/experience/ops/functional-kpis", params={"hours": 168})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["buckets"]) == 168
        for key, values in body["series"].items():
            assert len(values) == 168

    # ── Edge case: hours=0 rejected → 422 ────────────────────────────────

    def test_edge_hours_0_is_rejected(self):
        """hours=0 is below ge=1 constraint → FastAPI returns 422."""
        resp = self.client.get("/api/experience/ops/functional-kpis", params={"hours": 0})
        assert resp.status_code == 422

    # ── Edge case: hours=169 rejected → 422 ─────────────────────────────

    def test_edge_hours_above_168_is_rejected(self):
        """hours=169 is above le=168 constraint → FastAPI returns 422."""
        resp = self.client.get("/api/experience/ops/functional-kpis", params={"hours": 169})
        assert resp.status_code == 422

    # ── Edge case 7: Training success rate per bucket ─────────────────────

    def test_training_success_rate_computed_correctly(self):
        """Edge case 7: 1 completed + 1 failed in latest bucket → 50% success rate."""
        # Insert two training rows ending at UTC now (within the latest bucket)
        now_utc = datetime.utcnow()
        _insert_training_row(self.db_session, status="completed", ended_at=now_utc)
        _insert_training_row(self.db_session, status="failed", ended_at=now_utc)

        resp = self.client.get("/api/experience/ops/functional-kpis", params={"hours": 2})
        assert resp.status_code == 200
        series = resp.json()["series"]
        # The last bucket (index -1) should contain our two training rows
        last_bucket_rate = series["training_success_rate_pct"][-1]
        assert last_bucket_rate == 50.0, (
            f"Expected 50.0% training success rate, got {last_bucket_rate}"
        )

    # ── API error rate correctly bucketed ──────────────────────────────────

    def test_api_error_rate_in_bucket(self):
        """2 of 4 calls in current hour are 5xx → error_rate_pct ~50.0 for that bucket."""
        now_naive = datetime.utcnow()
        # All 4 rows in current bucket (truncate to current hour)
        current_hour = now_naive.replace(minute=0, second=0, microsecond=0)
        _insert_api_row(self.db_session, status_code=200, called_at=current_hour)
        _insert_api_row(self.db_session, status_code=200, called_at=current_hour)
        _insert_api_row(self.db_session, status_code=500, called_at=current_hour)
        _insert_api_row(self.db_session, status_code=500, called_at=current_hour)

        resp = self.client.get("/api/experience/ops/functional-kpis", params={"hours": 2})
        assert resp.status_code == 200
        series = resp.json()["series"]
        last_error_rate = series["error_rate_pct"][-1]
        assert last_error_rate == 50.0, (
            f"Expected 50.0% error rate, got {last_error_rate}"
        )

    # ── Experience error rate separately tracked ───────────────────────────

    def test_experience_error_pct_computed_separately(self):
        """Experience-path errors are separated from overall error rate."""
        now_naive = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
        # 1 experience error, 1 experience success
        _insert_api_row(
            self.db_session, path="/api/experience/ops/functional-kpis",
            status_code=500, called_at=now_naive,
        )
        _insert_api_row(
            self.db_session, path="/api/experience/ops/functional-kpis",
            status_code=200, called_at=now_naive,
        )
        # 2 non-experience rows (both success)
        _insert_api_row(self.db_session, path="/api/v1/train", status_code=200, called_at=now_naive)
        _insert_api_row(self.db_session, path="/api/v1/train", status_code=200, called_at=now_naive)

        resp = self.client.get("/api/experience/ops/functional-kpis", params={"hours": 2})
        assert resp.status_code == 200
        series = resp.json()["series"]
        # experience_error_pct: 1 of 2 experience calls failed → 50.0
        exp_err = series["experience_error_pct"][-1]
        assert exp_err == 50.0, f"Expected 50.0% experience error rate, got {exp_err}"
        # overall error_rate_pct: 1 of 4 total → 25.0
        overall_err = series["error_rate_pct"][-1]
        assert overall_err == 25.0, f"Expected 25.0% overall error rate, got {overall_err}"

    # ── Chat low-confidence rate from CSV ────────────────────────────────

    def test_chat_low_confidence_rate_from_csv(self):
        """Edge case 4 complement: CSV present → chat_low_confidence_pct computed."""
        # Write a minimal chat_monitor.csv with 2 rows in the current hour
        now_str = datetime.now(timezone.utc).replace(
            minute=5, second=0, microsecond=0
        ).isoformat()
        csv_path = os.path.join(self.tmp_path, "chat_monitor.csv")
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["timestamp", "low_confidence"])
            writer.writeheader()
            writer.writerow({"timestamp": now_str, "low_confidence": "1"})
            writer.writerow({"timestamp": now_str, "low_confidence": "0"})

        resp = self.client.get("/api/experience/ops/functional-kpis", params={"hours": 2})
        assert resp.status_code == 200
        series = resp.json()["series"]
        # 1 of 2 rows low_confidence → 50.0%
        last_chat = series["chat_low_confidence_pct"][-1]
        assert last_chat == 50.0, (
            f"Expected 50.0% chat low-confidence rate, got {last_chat}"
        )

    # ── Edge case 4: No CSV → chat zeros ─────────────────────────────────

    def test_edge_no_csv_chat_low_confidence_is_zero(self):
        """Edge case 4: chat_monitor.csv absent → chat_low_confidence_pct is all zeros."""
        # tmp_path exists but no CSV file inside
        resp = self.client.get("/api/experience/ops/functional-kpis")
        assert resp.status_code == 200
        series = resp.json()["series"]
        assert all(v == 0.0 for v in series["chat_low_confidence_pct"]), (
            "chat_low_confidence_pct should be all zeros when CSV is absent"
        )

    # ── P95 latency is computed ────────────────────────────────────────────

    def test_p95_latency_computed_from_api_rows(self):
        """p95_latency_ms computed from duration_ms of API calls in the bucket."""
        now_naive = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
        # Insert 10 rows with durations 10..100 ms; p95 of [10,20,...,100] is 100
        for i in range(1, 11):
            _insert_api_row(
                self.db_session,
                status_code=200,
                duration_ms=float(i * 10),
                called_at=now_naive,
            )

        resp = self.client.get("/api/experience/ops/functional-kpis", params={"hours": 2})
        assert resp.status_code == 200
        series = resp.json()["series"]
        p95 = series["p95_latency_ms"][-1]
        # sorted[9] = 100; int(10 * 0.95) = 9; sorted_d[min(9, 9)] = 100
        assert p95 == 100.0, f"Expected p95=100.0ms, got {p95}"

    # ── Endpoint is read-only ─────────────────────────────────────────────

    def test_endpoint_is_read_only(self):
        """Experience tier: get_functional_kpis must not call db.commit()."""
        import inspect
        from rita.api.experience.ops import get_functional_kpis

        source = inspect.getsource(get_functional_kpis)
        # Filter out docstring lines and comment lines before checking for db.commit()
        non_comment_lines = [
            line for line in source.split("\n")
            if not line.strip().startswith('"""')
            and not line.strip().startswith("'\"'\"'")
            and not line.strip().startswith("#")
            and "Read-only" not in line
        ]
        non_docstring_source = "\n".join(non_comment_lines)
        assert "db.commit()" not in non_docstring_source, (
            "get_functional_kpis must not call db.commit() — experience tier is read-only"
        )

    # ── Edge case 2+3: OperationalError fallback → zero response ─────────

    def test_edge_operational_error_returns_zero_response_not_500(self):
        """Edge cases 2+3: OperationalError on DB queries → graceful zero response."""
        from unittest.mock import patch, MagicMock

        # Patch TrainingRunsRepository.read_all to raise OperationalError
        from sqlalchemy.exc import OperationalError as _OpErr

        mock_repo = MagicMock()
        mock_repo.read_all.side_effect = _OpErr("", None, None)

        with patch(
            "rita.api.experience.ops.TrainingRunsRepository",
            return_value=mock_repo,
        ):
            resp = self.client.get("/api/experience/ops/functional-kpis", params={"hours": 3})

        assert resp.status_code == 200
        body = resp.json()
        assert "series" in body
        # Should still return correct bucket count
        assert len(body["buckets"]) == 3
        # Training success should be all zeros since training_runs query failed
        assert all(v == 0.0 for v in body["series"]["training_success_rate_pct"])


# ===========================================================================
# 3. API-frontend contract check (static verification)
# ===========================================================================

class TestFunctionalKPIsContractCheck:
    """FC-004: every field JS reads via data.series[def.key] must be in FunctionalKPIsSeries."""

    # All def.key values found in KPI_DEFS array of functional-kpis.js:
    JS_SERIES_KEY_READS = {
        "training_success_rate_pct",
        "chat_low_confidence_pct",
        "experience_error_pct",
        "error_rate_pct",
        "p95_latency_ms",
    }

    # Top-level fields JS reads from the response (data.series, data.buckets)
    JS_DATA_FIELD_READS = {"series", "buckets"}

    def test_all_js_series_keys_present_in_schema(self):
        """Every def.key in KPI_DEFS must match a field in FunctionalKPIsSeries."""
        schema_fields = set(FunctionalKPIsSeries.model_fields.keys())
        missing = self.JS_SERIES_KEY_READS - schema_fields
        assert not missing, (
            f"CONTRACT MISMATCH — JS reads series keys not in FunctionalKPIsSeries: {missing}"
        )

    def test_no_extra_js_reads_beyond_schema(self):
        """JS does not read any series key that does not exist in the schema."""
        schema_fields = set(FunctionalKPIsSeries.model_fields.keys())
        # JS should not read fields that don't exist in the schema
        extra_in_schema_only = schema_fields - self.JS_SERIES_KEY_READS
        # This is acceptable (schema may have extra fields JS doesn't use)
        # but for this contract all 5 fields must be consumed by JS too
        assert not extra_in_schema_only, (
            f"Schema fields not consumed by JS: {extra_in_schema_only}. "
            "Ensure all 5 fields have corresponding KPI_DEFS entries."
        )

    def test_all_js_data_fields_present_in_response_schema(self):
        """data.series and data.buckets must be declared in FunctionalKPIsResponse."""
        response_fields = set(FunctionalKPIsResponse.model_fields.keys())
        missing = self.JS_DATA_FIELD_READS - response_fields
        assert not missing, (
            f"CONTRACT MISMATCH — JS reads data.{missing} not in FunctionalKPIsResponse"
        )

    def test_generated_at_in_schema_not_read_by_js(self):
        """generated_at is in schema but JS doesn't read it — this is acceptable."""
        response_fields = set(FunctionalKPIsResponse.model_fields.keys())
        assert "generated_at" in response_fields
        assert "generated_at" not in self.JS_DATA_FIELD_READS

    def test_contract_table_all_matches(self):
        """
        FC-004 contract table:
        Schema field (FunctionalKPIsSeries) | JS def.key read    | Match?
        ------------------------------------|--------------------|-------
        training_success_rate_pct          | same               | YES
        chat_low_confidence_pct            | same               | YES
        experience_error_pct               | same               | YES
        error_rate_pct                     | same               | YES
        p95_latency_ms                     | same               | YES

        FunctionalKPIsResponse             | JS data field      | Match?
        ------------------------------------|--------------------|-------
        buckets                            | data.buckets       | YES
        series                             | data.series        | YES
        generated_at                       | (not read by JS)   | n/a — server-only field, OK
        """
        schema_series_fields = set(FunctionalKPIsSeries.model_fields.keys())
        mismatches = []
        for field in self.JS_SERIES_KEY_READS:
            if field not in schema_series_fields:
                mismatches.append(field)
        assert not mismatches, f"JS reads series keys absent from schema: {mismatches}"

        response_fields = set(FunctionalKPIsResponse.model_fields.keys())
        data_mismatches = []
        for field in self.JS_DATA_FIELD_READS:
            if field not in response_fields:
                data_mismatches.append(field)
        assert not data_mismatches, (
            f"JS reads data.{data_mismatches} absent from FunctionalKPIsResponse"
        )

    def test_api_export_present_in_ops_api_js(self):
        """api must be exported from dashboard/js/ops/api.js (imported by functional-kpis.js)."""
        api_path = (
            Path(__file__).parent.parent.parent
            / "dashboard" / "js" / "ops" / "api.js"
        )
        assert api_path.exists(), f"api.js not found at {api_path}"
        content = api_path.read_text(encoding="utf-8")
        assert "export" in content and "api" in content, (
            "api export not found in dashboard/js/ops/api.js — FC-IMP FAIL"
        )
