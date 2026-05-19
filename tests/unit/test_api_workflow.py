"""API contract tests for Workflow routers (Day 10).

Tests cover: train, backtest, evaluate.

Strategy
--------
- Services (WorkflowService, BacktestService) are overridden via FastAPI's
  app.dependency_overrides mechanism.
- All workflow POST endpoints must return 202 with status=pending (Sprint 2).
"""

from __future__ import annotations

from datetime import datetime, date, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


_NOW = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
_TODAY = date(2026, 4, 1)


def _training_run():
    from rita.schemas.training import TrainingRun
    return TrainingRun(
        run_id="run-001",
        model_version="v1.0",
        algorithm="DoubleDQN",
        timesteps=200000,
        learning_rate=1e-4,
        buffer_size=50000,
        net_arch="[128, 128]",
        exploration_pct=0.1,
        notes=None,
        status="pending",
        started_at=None,
        ended_at=None,
        backtest_sharpe=None,
        backtest_mdd=None,
        backtest_return=None,
        model_path=None,
        recorded_at=_NOW,
    )


def _backtest_run(triggered_by: str = "api"):
    from rita.schemas.backtest import BacktestRun
    return BacktestRun(
        run_id="bt-001",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 3, 31),
        model_version="v1.0",
        strategy_params=None,
        triggered_by=triggered_by,
        status="pending",
        started_at=None,
        ended_at=None,
        recorded_at=_NOW,
    )


_VALID_TRAINING_PAYLOAD = {
    "model_version": "v1.0",
    "algorithm": "DoubleDQN",
    "timesteps": 200000,
    "learning_rate": 0.0001,
    "buffer_size": 50000,
    "net_arch": "[128, 128]",
    "exploration_pct": 0.1,
    "notes": None,
}

_VALID_BACKTEST_PAYLOAD = {
    "start_date": "2026-01-01",
    "end_date": "2026-03-31",
    "model_version": "v1.0",
    "strategy_params": None,
    "triggered_by": "api",
}


def _override(app, dep, mock_value):
    from rita.auth import get_current_user
    app.dependency_overrides[dep] = lambda: mock_value
    # Bypass JWT auth so workflow tests don't need real tokens
    app.dependency_overrides[get_current_user] = lambda: "test-user"


def _clear(app, dep):
    from rita.auth import get_current_user
    app.dependency_overrides.pop(dep, None)
    app.dependency_overrides.pop(get_current_user, None)


# ---------------------------------------------------------------------------
# Train router
# ---------------------------------------------------------------------------

class TestTrainRouter:
    def test_post_train_returns_202_with_pending_status(self):
        """POST /api/v1/workflow/train/ returns 202 and status=pending."""
        from rita.main import app
        from rita.api.v1.workflow.train import get_service
        mock_svc = MagicMock()
        mock_svc.start_training.return_value = _training_run()
        try:
            _override(app, get_service, mock_svc)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post("/api/v1/workflow/train/", json=_VALID_TRAINING_PAYLOAD)
            assert response.status_code == 202
        finally:
            _clear(app, get_service)

    def test_post_train_response_has_pending_status(self):
        """POST /api/v1/workflow/train/ response body has status=pending."""
        from rita.main import app
        from rita.api.v1.workflow.train import get_service
        mock_svc = MagicMock()
        mock_svc.start_training.return_value = _training_run()
        try:
            _override(app, get_service, mock_svc)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post("/api/v1/workflow/train/", json=_VALID_TRAINING_PAYLOAD)
            assert response.json()["status"] == "pending"
        finally:
            _clear(app, get_service)

    def test_post_train_invalid_payload_returns_422(self):
        """POST /api/v1/workflow/train/ with invalid payload returns 422."""
        from rita.main import app
        from rita.api.v1.workflow.train import get_service
        mock_svc = MagicMock()
        try:
            _override(app, get_service, mock_svc)
            client = TestClient(app, raise_server_exceptions=False)
            # Missing required fields
            response = client.post("/api/v1/workflow/train/", json={"model_version": "v1.0"})
            assert response.status_code == 422
        finally:
            _clear(app, get_service)

    def test_list_train_runs_returns_200(self):
        """GET /api/v1/workflow/train/ returns 200 with a list."""
        from rita.main import app
        from rita.api.v1.workflow.train import get_service
        mock_svc = MagicMock()
        mock_svc.list_runs.return_value = [_training_run()]
        try:
            _override(app, get_service, mock_svc)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/workflow/train/")
            assert response.status_code == 200
        finally:
            _clear(app, get_service)

    def test_get_train_run_by_id_returns_200_for_existing(self):
        """GET /api/v1/workflow/train/{run_id} returns 200 when run exists."""
        from rita.main import app
        from rita.api.v1.workflow.train import get_service
        mock_svc = MagicMock()
        mock_svc.get_run.return_value = _training_run()
        try:
            _override(app, get_service, mock_svc)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/workflow/train/run-001")
            assert response.status_code == 200
        finally:
            _clear(app, get_service)

    def test_get_train_run_by_id_returns_404_for_missing(self):
        """GET /api/v1/workflow/train/{run_id} returns 404 when run missing."""
        from rita.main import app
        from rita.api.v1.workflow.train import get_service
        mock_svc = MagicMock()
        mock_svc.get_run.return_value = None
        try:
            _override(app, get_service, mock_svc)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/workflow/train/nonexistent")
            assert response.status_code == 404
        finally:
            _clear(app, get_service)

    def test_get_train_metrics_returns_404_for_missing_run(self):
        """GET /api/v1/workflow/train/{run_id}/metrics returns 404 when run missing."""
        from rita.main import app
        from rita.api.v1.workflow.train import get_service
        mock_svc = MagicMock()
        mock_svc.get_run.return_value = None
        try:
            _override(app, get_service, mock_svc)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/workflow/train/nonexistent/metrics")
            assert response.status_code == 404
        finally:
            _clear(app, get_service)


# ---------------------------------------------------------------------------
# Backtest router
# ---------------------------------------------------------------------------

class TestBacktestRouter:
    def test_post_backtest_returns_202(self):
        """POST /api/v1/workflow/backtest/ returns 202."""
        from rita.main import app
        from rita.api.v1.workflow.backtest import get_service
        mock_svc = MagicMock()
        mock_svc.start_backtest.return_value = _backtest_run()
        try:
            _override(app, get_service, mock_svc)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post("/api/v1/workflow/backtest/", json=_VALID_BACKTEST_PAYLOAD)
            assert response.status_code == 202
        finally:
            _clear(app, get_service)

    def test_post_backtest_response_has_pending_status(self):
        """POST /api/v1/workflow/backtest/ response body has status=pending."""
        from rita.main import app
        from rita.api.v1.workflow.backtest import get_service
        mock_svc = MagicMock()
        mock_svc.start_backtest.return_value = _backtest_run()
        try:
            _override(app, get_service, mock_svc)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post("/api/v1/workflow/backtest/", json=_VALID_BACKTEST_PAYLOAD)
            assert response.json()["status"] == "pending"
        finally:
            _clear(app, get_service)

    def test_post_backtest_invalid_payload_returns_422(self):
        """POST /api/v1/workflow/backtest/ with invalid payload returns 422."""
        from rita.main import app
        from rita.api.v1.workflow.backtest import get_service
        mock_svc = MagicMock()
        try:
            _override(app, get_service, mock_svc)
            client = TestClient(app, raise_server_exceptions=False)
            # Missing required fields (start_date, end_date, model_version)
            response = client.post("/api/v1/workflow/backtest/", json={"triggered_by": "api"})
            assert response.status_code == 422
        finally:
            _clear(app, get_service)

    def test_list_backtest_runs_returns_200(self):
        """GET /api/v1/workflow/backtest/ returns 200 with a list."""
        from rita.main import app
        from rita.api.v1.workflow.backtest import get_service
        mock_svc = MagicMock()
        mock_svc.list_runs.return_value = []
        try:
            _override(app, get_service, mock_svc)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/workflow/backtest/")
            assert response.status_code == 200
        finally:
            _clear(app, get_service)

    def test_get_backtest_run_returns_404_for_missing(self):
        """GET /api/v1/workflow/backtest/{run_id} returns 404 when run missing."""
        from rita.main import app
        from rita.api.v1.workflow.backtest import get_service
        mock_svc = MagicMock()
        mock_svc.get_run.return_value = None
        try:
            _override(app, get_service, mock_svc)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/workflow/backtest/nonexistent")
            assert response.status_code == 404
        finally:
            _clear(app, get_service)


# ---------------------------------------------------------------------------
# Evaluate router
# ---------------------------------------------------------------------------

class TestEvaluateRouter:
    def test_post_evaluate_returns_202(self):
        """POST /api/v1/workflow/evaluate/ returns 202."""
        from rita.main import app
        from rita.api.v1.workflow.evaluate import get_service
        mock_svc = MagicMock()
        mock_svc.start_evaluation.return_value = _backtest_run(triggered_by="evaluate")
        try:
            _override(app, get_service, mock_svc)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post("/api/v1/workflow/evaluate/", json=_VALID_BACKTEST_PAYLOAD)
            assert response.status_code == 202
        finally:
            _clear(app, get_service)

    def test_post_evaluate_response_has_pending_status(self):
        """POST /api/v1/workflow/evaluate/ response body has status=pending."""
        from rita.main import app
        from rita.api.v1.workflow.evaluate import get_service
        mock_svc = MagicMock()
        mock_svc.start_evaluation.return_value = _backtest_run(triggered_by="evaluate")
        try:
            _override(app, get_service, mock_svc)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post("/api/v1/workflow/evaluate/", json=_VALID_BACKTEST_PAYLOAD)
            assert response.json()["status"] == "pending"
        finally:
            _clear(app, get_service)

    def test_post_evaluate_invalid_payload_returns_422(self):
        """POST /api/v1/workflow/evaluate/ with invalid payload returns 422."""
        from rita.main import app
        from rita.api.v1.workflow.evaluate import get_service
        mock_svc = MagicMock()
        try:
            _override(app, get_service, mock_svc)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post("/api/v1/workflow/evaluate/", json={"triggered_by": "evaluate"})
            assert response.status_code == 422
        finally:
            _clear(app, get_service)

    def test_list_evaluations_returns_200(self):
        """GET /api/v1/workflow/evaluate/ returns 200 with a list."""
        from rita.main import app
        from rita.api.v1.workflow.evaluate import get_service
        mock_svc = MagicMock()
        mock_svc.list_evaluations.return_value = []
        try:
            _override(app, get_service, mock_svc)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/workflow/evaluate/")
            assert response.status_code == 200
        finally:
            _clear(app, get_service)

    def test_get_evaluation_run_returns_404_for_missing(self):
        """GET /api/v1/workflow/evaluate/{run_id} returns 404 when run missing."""
        from rita.main import app
        from rita.api.v1.workflow.evaluate import get_service
        mock_svc = MagicMock()
        mock_svc.get_run.return_value = None
        try:
            _override(app, get_service, mock_svc)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/workflow/evaluate/nonexistent")
            assert response.status_code == 404
        finally:
            _clear(app, get_service)

    def test_evaluate_triggered_by_is_evaluate(self):
        """POST /api/v1/workflow/evaluate/ response sets triggered_by=evaluate."""
        from rita.main import app
        from rita.api.v1.workflow.evaluate import get_service
        run = _backtest_run(triggered_by="evaluate")
        mock_svc = MagicMock()
        mock_svc.start_evaluation.return_value = run
        try:
            _override(app, get_service, mock_svc)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post("/api/v1/workflow/evaluate/", json=_VALID_BACKTEST_PAYLOAD)
            assert response.json()["triggered_by"] == "evaluate"
        finally:
            _clear(app, get_service)
