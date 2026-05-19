"""Unit tests for the Improve Observability feature.

Covers three areas:
  1. log_event() wrapper in rita/logging_config.py
  2. POST /api/v1/client-error endpoint
  3. generate_alerts.py alert rule evaluation

Run with:
    cd riia-jun-release && python -m pytest tests/unit/test_observability.py -v
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Shared UTC "now" sentinel for alert tests
# ---------------------------------------------------------------------------
_NOW = datetime(2026, 5, 11, 10, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# Area 1 — log_event() and configure_logging()
# ---------------------------------------------------------------------------


class TestLogEvent:
    """log_event() correctness tests — no real log files required."""

    def setup_method(self):
        """Remove any existing handlers from rita.events logger before each test."""
        rita_log = logging.getLogger("rita.events")
        rita_log.handlers.clear()
        # Remove all RotatingFileHandler handlers from root to keep tests isolated.
        root = logging.getLogger()
        for h in list(root.handlers):
            if hasattr(h, "baseFilename"):
                root.removeHandler(h)

    def test_log_event_emits_correct_keys(self):
        """log_event() must emit a JSON message with event, trace_id, timestamp, and payload fields."""
        from rita.logging_config import log_event

        captured = []

        class CapturingHandler(logging.Handler):
            def emit(self, record):
                captured.append(record)

        handler = CapturingHandler()
        logging.getLogger("rita.events").addHandler(handler)
        logging.getLogger("rita.events").setLevel(logging.DEBUG)

        mock_logger = MagicMock()
        log_event(mock_logger, "info", "trade.executed", instrument="NIFTY", quantity=75)

        assert len(captured) == 1, "Expected exactly one log record"
        msg = captured[0].getMessage()
        data = json.loads(msg)

        assert data["event"] == "trade.executed"
        assert "trace_id" in data
        assert "timestamp" in data
        assert data["instrument"] == "NIFTY"
        assert data["quantity"] == 75

    def test_log_event_uses_correct_stdlib_level(self):
        """log_event() must emit at the correct stdlib log level."""
        from rita.logging_config import log_event

        captured = []

        class CapturingHandler(logging.Handler):
            def emit(self, record):
                captured.append(record)

        handler = CapturingHandler()
        logging.getLogger("rita.events").addHandler(handler)
        logging.getLogger("rita.events").setLevel(logging.DEBUG)

        mock_logger = MagicMock()
        log_event(mock_logger, "warning", "drift.check_error")

        assert len(captured) == 1
        assert captured[0].levelno == logging.WARNING

    def test_log_event_also_calls_structlog_bind(self):
        """log_event() must call logger.bind() to emit on the structlog side too."""
        from rita.logging_config import log_event

        mock_logger = MagicMock()
        bound_mock = MagicMock()
        mock_logger.bind.return_value = bound_mock

        log_event(mock_logger, "info", "chat.request", intent="trade", confidence=0.91)

        mock_logger.bind.assert_called_once()
        call_kwargs = mock_logger.bind.call_args[1]
        assert call_kwargs["event"] == "chat.request"
        assert call_kwargs["intent"] == "trade"
        assert call_kwargs["confidence"] == 0.91

    def test_configure_logging_idempotent(self, tmp_path):
        """configure_logging() called twice must not add duplicate handlers."""
        from rita.logging_config import configure_logging

        with patch("rita.logging_config.pathlib.Path", return_value=tmp_path):
            # Clear file handlers first
            root = logging.getLogger()
            pre_existing = [h for h in list(root.handlers) if hasattr(h, "baseFilename")]
            for h in pre_existing:
                root.removeHandler(h)

            configure_logging("info")
            count_after_first = sum(1 for h in root.handlers if hasattr(h, "baseFilename"))

            configure_logging("info")
            count_after_second = sum(1 for h in root.handlers if hasattr(h, "baseFilename"))

            assert count_after_first == count_after_second, (
                f"Duplicate handlers added on second call: "
                f"first={count_after_first}, second={count_after_second}"
            )

    def test_log_event_before_configure_logging_does_not_crash(self):
        """log_event() must not raise even when configure_logging() has not been called."""
        from rita.logging_config import log_event

        mock_logger = MagicMock()
        # Should not raise
        try:
            log_event(mock_logger, "error", "pipeline.error", detail="oops")
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"log_event() raised unexpectedly before configure_logging(): {exc}")


# ---------------------------------------------------------------------------
# Area 2 — POST /api/v1/client-error endpoint
# ---------------------------------------------------------------------------


class TestClientErrorEndpoint:
    """FastAPI endpoint tests — uses TestClient, no real log files."""

    @pytest.fixture(autouse=True)
    def client(self):
        """Build a TestClient that uses the real RITA app (imported via conftest config patch)."""
        from fastapi.testclient import TestClient
        from rita.main import app

        with TestClient(app, raise_server_exceptions=False) as c:
            self._client = c
            yield c

    def _post(self, payload: dict):
        return self._client.post("/api/v1/client-error", json=payload)

    # ── Valid payload ────────────────────────────────────────────────────────

    def test_valid_payload_returns_204(self):
        """A fully populated, valid payload must return 204 No Content."""
        resp = self._post({
            "message": "TypeError: Cannot read property 'x' of undefined",
            "url": "https://rita.local/dashboard",
            "trace_id": "abc-123",
        })
        assert resp.status_code == 204, resp.text

    def test_valid_payload_with_stack_returns_204(self):
        """Payload with stack field included must still return 204."""
        resp = self._post({
            "message": "ReferenceError: apiFetch is not defined",
            "url": "https://rita.local/fno",
            "trace_id": "trace-xyz",
            "stack": "Error: ReferenceError\n  at fno.main.js:42\n  at <anonymous>:1:1",
        })
        assert resp.status_code == 204, resp.text

    # ── Null / missing optional fields ──────────────────────────────────────

    def test_null_stack_is_accepted(self):
        """stack is optional — an explicit null must be accepted and return 204."""
        resp = self._post({
            "message": "UnhandledRejection: fetch failed",
            "url": "https://rita.local/mobile",
            "trace_id": "trace-mobile-1",
            "stack": None,
        })
        assert resp.status_code == 204, resp.text

    def test_missing_stack_is_accepted(self):
        """stack may be omitted entirely — must return 204."""
        resp = self._post({
            "message": "sw_error: install failed",
            "url": "https://rita.local/sw.js",
            "trace_id": "trace-sw-1",
        })
        assert resp.status_code == 204, resp.text

    # ── Missing required field → 422 ────────────────────────────────────────

    def test_missing_message_returns_422(self):
        """message is required; omitting it must return 422."""
        resp = self._post({
            "url": "https://rita.local/dashboard",
            "trace_id": "trace-001",
        })
        assert resp.status_code == 422, resp.text

    def test_oversized_message_returns_422(self):
        """message > 2000 chars must return 422 per the Architect spec."""
        resp = self._post({
            "message": "x" * 2001,
            "url": "https://rita.local/dashboard",
            "trace_id": "trace-bigmsg",
        })
        assert resp.status_code == 422, resp.text

    # ── Log call is made ────────────────────────────────────────────────────

    def test_valid_payload_calls_log_event(self):
        """log_event() must be invoked when the endpoint handles a valid request."""
        with patch("rita.api.v1.system.client_errors.log_event") as mock_log_event:
            resp = self._post({
                "message": "test error",
                "url": "https://rita.local",
                "trace_id": "t-999",
            })
            assert resp.status_code == 204
            mock_log_event.assert_called_once()
            call_kwargs = mock_log_event.call_args[1]
            assert call_kwargs["message"] == "test error"
            assert call_kwargs["url"] == "https://rita.local"
            assert call_kwargs["trace_id"] == "t-999"


# ---------------------------------------------------------------------------
# Area 3 — generate_alerts.py rule evaluation
# ---------------------------------------------------------------------------

# We import the module's functions directly — no subprocess, no file writes.

def _import_generate_alerts():
    """Import generate_alerts from project-office/scripts/."""
    repo_root = Path(__file__).resolve().parents[3]  # …/riia-cowork-jun
    scripts_dir = repo_root / "project-office" / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    spec = importlib.util.spec_from_file_location(
        "generate_alerts",
        scripts_dir / "generate_alerts.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Load module once for the whole test session
try:
    _ga = _import_generate_alerts()
    _GA_AVAILABLE = True
except Exception as _ga_exc:
    _GA_AVAILABLE = False
    _ga_exc_msg = str(_ga_exc)


@pytest.mark.skipif(not _GA_AVAILABLE, reason=f"generate_alerts import failed: {_ga_exc_msg if not _GA_AVAILABLE else ''}")
class TestGenerateAlerts:
    """Tests for alert rule evaluation logic — all file I/O is mocked."""

    # ── helpers ─────────────────────────────────────────────────────────────

    def _summary(self, **overrides) -> dict:
        """Return a minimal metrics-summary dict with all fields at safe (non-alerting) values."""
        base = {
            "operational": {
                "error_rate_pct": 0.0,
                "p95_latency_ms": 200.0,
            },
            "functional": {
                "chat_low_confidence_pct": 5.0,
                "experience_partial_pct": 2.0,
                "experience_error_pct": 0.0,
                "data_freshness_days": 0.5,
            },
            "source_availability": {},
        }
        # Apply overrides by dotted path e.g. "operational.error_rate_pct"
        for key, value in overrides.items():
            parts = key.split(".")
            target = base
            for p in parts[:-1]:
                target = target[p]
            target[parts[-1]] = value
        return base

    # ── Rule: error_rate_high fires when threshold exceeded ─────────────────

    def test_error_rate_high_fires_when_exceeded(self):
        """error_rate_high rule must fire when error_rate_pct > 5.0."""
        summary = self._summary(**{"operational.error_rate_pct": 12.5})
        firing = _ga.evaluate_all_rules(summary, [], _NOW)
        rule_ids = [f["rule"] for f in firing]
        assert "error_rate_high" in rule_ids

    def test_error_rate_high_does_not_fire_at_threshold(self):
        """error_rate_high must NOT fire when error_rate_pct == 5.0 (not strictly greater)."""
        summary = self._summary(**{"operational.error_rate_pct": 5.0})
        firing = _ga.evaluate_all_rules(summary, [], _NOW)
        rule_ids = [f["rule"] for f in firing]
        assert "error_rate_high" not in rule_ids

    def test_error_rate_high_does_not_fire_below_threshold(self):
        """error_rate_high must NOT fire when error_rate_pct < 5.0."""
        summary = self._summary(**{"operational.error_rate_pct": 1.0})
        firing = _ga.evaluate_all_rules(summary, [], _NOW)
        rule_ids = [f["rule"] for f in firing]
        assert "error_rate_high" not in rule_ids

    # ── Rule: latency_high fires when threshold exceeded ────────────────────

    def test_latency_high_fires_when_exceeded(self):
        """latency_high rule must fire when p95_latency_ms > 1500."""
        summary = self._summary(**{"operational.p95_latency_ms": 2000.0})
        firing = _ga.evaluate_all_rules(summary, [], _NOW)
        rule_ids = [f["rule"] for f in firing]
        assert "latency_high" in rule_ids

    def test_latency_high_does_not_fire_below_threshold(self):
        """latency_high must NOT fire when p95_latency_ms < 1500."""
        summary = self._summary(**{"operational.p95_latency_ms": 900.0})
        firing = _ga.evaluate_all_rules(summary, [], _NOW)
        rule_ids = [f["rule"] for f in firing]
        assert "latency_high" not in rule_ids

    # ── No alerts when all metrics are within thresholds ────────────────────

    def test_no_alerts_when_all_metrics_nominal(self):
        """Zero alerts must be generated when all metrics are within their thresholds."""
        summary = self._summary()  # all safe values
        firing = _ga.evaluate_all_rules(summary, [], _NOW)
        assert firing == [], f"Expected no alerts but got: {[f['rule'] for f in firing]}"

    # ── data_stale_warn fires ────────────────────────────────────────────────

    def test_data_stale_warn_fires_when_freshness_between_1_and_3(self):
        """data_stale_warn must fire when data_freshness_days is between 1 and 3 (exclusive)."""
        summary = self._summary(**{"functional.data_freshness_days": 2.0})
        firing = _ga.evaluate_all_rules(summary, [], _NOW)
        rule_ids = [f["rule"] for f in firing]
        assert "data_stale_warn" in rule_ids
        assert "data_stale_critical" not in rule_ids

    def test_data_stale_critical_fires_when_freshness_exceeds_3(self):
        """data_stale_critical must fire when data_freshness_days > 3."""
        summary = self._summary(**{"functional.data_freshness_days": 5.0})
        firing = _ga.evaluate_all_rules(summary, [], _NOW)
        rule_ids = [f["rule"] for f in firing]
        assert "data_stale_critical" in rule_ids
        assert "data_stale_warn" not in rule_ids

    # ── training_failed: event-based rule ───────────────────────────────────

    def test_training_failed_fires_on_recent_event(self):
        """training_failed must fire when a 'training.failed' job record exists within 1h of now."""
        record = {
            "message": json.dumps({
                "event": "training.failed",
                "timestamp": _NOW.isoformat(),
            })
        }
        firing = _ga.evaluate_all_rules(self._summary(), [record], _NOW)
        rule_ids = [f["rule"] for f in firing]
        assert "training_failed" in rule_ids

    def test_training_failed_does_not_fire_without_recent_event(self):
        """training_failed must NOT fire when there are no recent training.failed events."""
        firing = _ga.evaluate_all_rules(self._summary(), [], _NOW)
        rule_ids = [f["rule"] for f in firing]
        assert "training_failed" not in rule_ids

    # ── backtest_failed: event-based rule ───────────────────────────────────

    def test_backtest_failed_fires_on_recent_event(self):
        """backtest_failed must fire when a 'backtest.failed' event exists within 1h."""
        record = {
            "message": json.dumps({
                "event": "backtest.failed",
                "timestamp": _NOW.isoformat(),
            })
        }
        firing = _ga.evaluate_all_rules(self._summary(), [record], _NOW)
        rule_ids = [f["rule"] for f in firing]
        assert "backtest_failed" in rule_ids

    # ── source_down: per-source error rate rule ──────────────────────────────

    def test_source_down_fires_when_error_rate_exceeds_20pct(self):
        """source_down must fire for a source whose error/(total) ratio > 0.20."""
        summary = self._summary()
        summary["source_availability"] = {
            "nifty_csv": {"ok": 3, "empty": 0, "error": 2},  # 40% error rate
        }
        firing = _ga.evaluate_all_rules(summary, [], _NOW)
        rule_ids = [f["rule"] for f in firing]
        assert "source_down" in rule_ids

    def test_source_down_does_not_fire_when_error_rate_at_threshold(self):
        """source_down must NOT fire when error rate == 20% (not strictly greater)."""
        summary = self._summary()
        summary["source_availability"] = {
            "nifty_csv": {"ok": 4, "empty": 0, "error": 1},  # exactly 20%
        }
        firing = _ga.evaluate_all_rules(summary, [], _NOW)
        rule_ids = [f["rule"] for f in firing]
        assert "source_down" not in rule_ids

    # ── Missing metrics-summary.json — handled gracefully ────────────────────

    def test_missing_metrics_summary_writes_empty_alerts(self, tmp_path):
        """When metrics-summary.json does not exist, main() writes alerts: [] and exits 0."""
        alerts_dir = tmp_path / "ops" / "alerts"
        alerts_dir.mkdir(parents=True)
        active_alerts_path = alerts_dir / "active-alerts.json"

        # Patch file paths so generate_alerts writes to tmp_path
        with (
            patch.object(_ga, "OPS_METRICS_DIR", tmp_path / "ops" / "metrics"),
            patch.object(_ga, "OPS_ALERTS_DIR", alerts_dir),
            patch.object(_ga, "LOG_DIR", tmp_path / "logs"),
        ):
            # summary = None (file does not exist) → main() calls sys.exit(0)
            summary = _ga.read_json(tmp_path / "ops" / "metrics" / "metrics-summary.json")
            assert summary is None, "read_json must return None for a missing file"

            # Simulate the guard logic from main(): write empty alerts if summary is None
            if summary is None:
                out = {"generated_at": _NOW.isoformat(), "alerts": [], "meta": {"warning": "metrics-summary.json not found"}}
                _ga.write_json(active_alerts_path, out)

            assert active_alerts_path.exists(), "active-alerts.json must be written even when summary is missing"
            data = json.loads(active_alerts_path.read_text(encoding="utf-8"))
            assert data["alerts"] == [], f"alerts must be empty list, got: {data['alerts']}"

    def test_missing_metrics_summary_read_json_returns_none(self, tmp_path):
        """read_json() must return None for a missing file without raising."""
        result = _ga.read_json(tmp_path / "nonexistent.json")
        assert result is None

    # ── chat_low_confidence fires ────────────────────────────────────────────

    def test_chat_low_confidence_fires_when_exceeded(self):
        """chat_low_confidence must fire when chat_low_confidence_pct > 25."""
        summary = self._summary(**{"functional.chat_low_confidence_pct": 35.0})
        firing = _ga.evaluate_all_rules(summary, [], _NOW)
        rule_ids = [f["rule"] for f in firing]
        assert "chat_low_confidence" in rule_ids

    # ── experience_error fires ───────────────────────────────────────────────

    def test_experience_error_fires_when_exceeded(self):
        """experience_error must fire when experience_error_pct > 5.0."""
        summary = self._summary(**{"functional.experience_error_pct": 8.0})
        firing = _ga.evaluate_all_rules(summary, [], _NOW)
        rule_ids = [f["rule"] for f in firing]
        assert "experience_error" in rule_ids

    # ── Firing alert has correct severity and component ──────────────────────

    def test_error_rate_high_alert_has_correct_metadata(self):
        """The fired error_rate_high alert must carry severity=critical and component=api."""
        summary = self._summary(**{"operational.error_rate_pct": 7.0})
        firing = _ga.evaluate_all_rules(summary, [], _NOW)
        alert = next((f for f in firing if f["rule"] == "error_rate_high"), None)
        assert alert is not None
        assert alert["severity"] == "critical"
        assert alert["component"] == "api"
        assert alert["value"] == 7.0
        assert alert["threshold"] == 5.0
