"""API contract tests for Experience Layer routers (Day 11-12).

Tests cover: dashboard, fno, ops.

Strategy
--------
- Repository and service dependencies are overridden via FastAPI's
  app.dependency_overrides mechanism.
- Experience routers are read-only (GET only) and return composite payloads.
- We verify: status 200, top-level keys in the response body, and that an
  empty dataset still produces a valid payload.
"""

from __future__ import annotations

from datetime import datetime, date, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


_NOW = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
_TODAY = date(2026, 4, 1)


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def _position():
    from rita.schemas.positions import Position
    return Position(
        position_id="pos-001",
        instrument="BANKNIFTY26APR52000CE",
        underlying="BANKNIFTY",
        product="NRML",
        option_type="CE",
        strike=52000.0,
        expiry="26APR",
        quantity=75,
        avg_price=120.5,
        last_traded_price=130.0,
        pnl=712.5,
        pct_change=7.9,
        recorded_at=_NOW,
    )


def _alert():
    from rita.schemas.alerts import Alert
    return Alert(
        alert_id="alt-001",
        timestamp=_NOW,
        query_text="test query",
        intent_name="test_intent",
        handler="test_handler",
        confidence=0.95,
        low_confidence=False,
        latency_ms=50.0,
        response_preview="test response",
        status="success",
        recorded_at=_NOW,
    )


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


def _snapshot():
    from rita.schemas.snapshots import Snapshot
    return Snapshot(
        snapshot_id="snap-001",
        date=_TODAY,
        underlying="NIFTY",
        month="APR",
        group_id="anchor",
        group_name="Monthly Anchor",
        view="bull",
        lot_key="NIFTY26APR22700CE_L1",
        instrument="NIFTY26APR22700CE",
        option_type="CE",
        side="Long",
        lot_size=75,
        avg_price=100.0,
        pnl_now=500.0,
        pnl_sl=-200.0,
        pnl_target=1000.0,
        recorded_at=_NOW,
    )


def _portfolio():
    from rita.schemas.portfolio import Portfolio
    return Portfolio(
        portfolio_id="pf-001",
        date=_TODAY,
        underlying="NIFTY",
        month="APR",
        group_id="anchor",
        group_name="Monthly Anchor",
        view="bull",
        pnl_now=500.0,
        sl_pnl=-200.0,
        target_pnl=1000.0,
        lot_count=2,
        nifty_spot=22700.0,
        banknifty_spot=None,
        dte=25,
        pct_from_sl=None,
        pct_from_target=None,
        recorded_at=_NOW,
    )


def _manoeuvre():
    from rita.schemas.manoeuvres import Manoeuvre
    return Manoeuvre(
        manoeuvre_id="man-001",
        timestamp=_NOW,
        date=_TODAY,
        month="APR",
        action="add",
        lot_key="NIFTY26APR22700CE_L1",
        from_group=None,
        to_group="anchor",
        nifty_spot=22700.0,
        banknifty_spot=None,
        recorded_at=_NOW,
    )


def _backtest_run():
    from rita.schemas.backtest import BacktestRun
    return BacktestRun(
        run_id="bt-001",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 3, 31),
        model_version="v1.0",
        strategy_params=None,
        triggered_by="api",
        status="pending",
        started_at=None,
        ended_at=None,
        recorded_at=_NOW,
    )


def _audit_log():
    from rita.schemas.audit import AuditLog
    return AuditLog(
        log_id="log-001",
        timestamp=_NOW,
        source="api",
        method="GET",
        path="/api/experience/ops/",
        status_code=200,
        duration_ms=10.0,
        args_summary=None,
        result_summary=None,
        recorded_at=_NOW,
    )


def _override(app, dep, mock_value):
    app.dependency_overrides[dep] = lambda: mock_value


def _clear(app, *deps):
    for dep in deps:
        app.dependency_overrides.pop(dep, None)


# ---------------------------------------------------------------------------
# Dashboard router
# ---------------------------------------------------------------------------

class TestDashboardRouter:
    def _setup(self, app, pos_return, alerts_return, runs_return):
        from rita.api.experience.dashboard import (
            get_positions_repo, get_alerts_repo, get_workflow_svc
        )
        mock_pos_repo = MagicMock()
        mock_pos_repo.read_all.return_value = pos_return
        mock_alerts_repo = MagicMock()
        mock_alerts_repo.read_all.return_value = alerts_return
        mock_workflow_svc = MagicMock()
        mock_workflow_svc.list_runs.return_value = runs_return

        _override(app, get_positions_repo, mock_pos_repo)
        _override(app, get_alerts_repo, mock_alerts_repo)
        _override(app, get_workflow_svc, mock_workflow_svc)
        return get_positions_repo, get_alerts_repo, get_workflow_svc

    def test_get_dashboard_returns_200(self):
        """GET /api/experience/dashboard/ returns 200."""
        from rita.main import app
        deps = self._setup(app, [], [], [])
        try:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/experience/dashboard/")
            assert response.status_code == 200
        finally:
            _clear(app, *deps)

    def test_get_dashboard_has_positions_key(self):
        """GET /api/experience/dashboard/ response has 'positions' key."""
        from rita.main import app
        deps = self._setup(app, [_position()], [], [])
        try:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/experience/dashboard/")
            assert "positions" in response.json()
        finally:
            _clear(app, *deps)

    def test_get_dashboard_has_latest_training_run_key(self):
        """GET /api/experience/dashboard/ response has 'latest_training_run' key."""
        from rita.main import app
        deps = self._setup(app, [], [], [_training_run()])
        try:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/experience/dashboard/")
            assert "latest_training_run" in response.json()
        finally:
            _clear(app, *deps)

    def test_get_dashboard_has_recent_alerts_key(self):
        """GET /api/experience/dashboard/ response has 'recent_alerts' key."""
        from rita.main import app
        deps = self._setup(app, [], [_alert()], [])
        try:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/experience/dashboard/")
            assert "recent_alerts" in response.json()
        finally:
            _clear(app, *deps)

    def test_get_dashboard_empty_dataset_returns_valid_payload(self):
        """GET /api/experience/dashboard/ with empty repos returns valid payload."""
        from rita.main import app
        deps = self._setup(app, [], [], [])
        try:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/experience/dashboard/")
            body = response.json()
            assert body["positions"] == []
            assert body["latest_training_run"] is None
            assert body["recent_alerts"] == []
        finally:
            _clear(app, *deps)


# ---------------------------------------------------------------------------
# FnO router
# ---------------------------------------------------------------------------

class TestFnoRouter:
    def _setup(self, app, snaps_return, portfolio_return, man_return):
        from rita.api.experience.fno import (
            get_snapshots_repo, get_portfolio_service, get_manoeuvre_service
        )
        mock_snap_repo = MagicMock()
        mock_snap_repo.read_all.return_value = snaps_return
        mock_portfolio_svc = MagicMock()
        mock_portfolio_svc.list_all.return_value = portfolio_return
        mock_man_svc = MagicMock()
        mock_man_svc.list_recent.return_value = man_return

        _override(app, get_snapshots_repo, mock_snap_repo)
        _override(app, get_portfolio_service, mock_portfolio_svc)
        _override(app, get_manoeuvre_service, mock_man_svc)
        return get_snapshots_repo, get_portfolio_service, get_manoeuvre_service

    def test_get_fno_returns_200(self):
        """GET /api/experience/fno/ returns 200."""
        from rita.main import app
        deps = self._setup(app, [], [], [])
        try:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/experience/fno/")
            assert response.status_code == 200
        finally:
            _clear(app, *deps)

    def test_get_fno_has_snapshots_key(self):
        """GET /api/experience/fno/ response has 'snapshots' key."""
        from rita.main import app
        deps = self._setup(app, [_snapshot()], [], [])
        try:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/experience/fno/")
            assert "snapshots" in response.json()
        finally:
            _clear(app, *deps)

    def test_get_fno_has_portfolio_key(self):
        """GET /api/experience/fno/ response has 'portfolio' key."""
        from rita.main import app
        deps = self._setup(app, [], [_portfolio()], [])
        try:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/experience/fno/")
            assert "portfolio" in response.json()
        finally:
            _clear(app, *deps)

    def test_get_fno_has_recent_manoeuvres_key(self):
        """GET /api/experience/fno/ response has 'recent_manoeuvres' key."""
        from rita.main import app
        deps = self._setup(app, [], [], [_manoeuvre()])
        try:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/experience/fno/")
            assert "recent_manoeuvres" in response.json()
        finally:
            _clear(app, *deps)

    def test_get_fno_empty_dataset_returns_valid_payload(self):
        """GET /api/experience/fno/ with empty repos returns valid payload."""
        from rita.main import app
        deps = self._setup(app, [], [], [])
        try:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/experience/fno/")
            body = response.json()
            assert body["snapshots"] == []
            assert body["portfolio"] == []
            assert body["recent_manoeuvres"] == []
        finally:
            _clear(app, *deps)


# ---------------------------------------------------------------------------
# Ops router
# ---------------------------------------------------------------------------

class TestOpsRouter:
    def _setup(self, app, runs_return, bt_runs_return, audit_return):
        from rita.api.experience.ops import (
            get_workflow_svc, get_backtest_svc, get_audit_repo
        )
        mock_workflow_svc = MagicMock()
        mock_workflow_svc.list_runs.return_value = runs_return
        mock_backtest_svc = MagicMock()
        mock_backtest_svc.list_runs.return_value = bt_runs_return
        mock_audit_repo = MagicMock()
        mock_audit_repo.read_all.return_value = audit_return

        _override(app, get_workflow_svc, mock_workflow_svc)
        _override(app, get_backtest_svc, mock_backtest_svc)
        _override(app, get_audit_repo, mock_audit_repo)
        return get_workflow_svc, get_backtest_svc, get_audit_repo

    def test_get_ops_returns_200(self):
        """GET /api/experience/ops/ returns 200."""
        from rita.main import app
        deps = self._setup(app, [], [], [])
        try:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/experience/ops/")
            assert response.status_code == 200
        finally:
            _clear(app, *deps)

    def test_get_ops_has_training_runs_key(self):
        """GET /api/experience/ops/ response has 'training_runs' key."""
        from rita.main import app
        deps = self._setup(app, [_training_run()], [], [])
        try:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/experience/ops/")
            assert "training_runs" in response.json()
        finally:
            _clear(app, *deps)

    def test_get_ops_has_backtest_runs_key(self):
        """GET /api/experience/ops/ response has 'backtest_runs' key."""
        from rita.main import app
        deps = self._setup(app, [], [_backtest_run()], [])
        try:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/experience/ops/")
            assert "backtest_runs" in response.json()
        finally:
            _clear(app, *deps)

    def test_get_ops_has_recent_audit_key(self):
        """GET /api/experience/ops/ response has 'recent_audit' key."""
        from rita.main import app
        deps = self._setup(app, [], [], [_audit_log()])
        try:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/experience/ops/")
            assert "recent_audit" in response.json()
        finally:
            _clear(app, *deps)

    def test_get_ops_empty_dataset_returns_valid_payload(self):
        """GET /api/experience/ops/ with empty dependencies returns valid payload."""
        from rita.main import app
        deps = self._setup(app, [], [], [])
        try:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/experience/ops/")
            body = response.json()
            assert body["training_runs"] == []
            assert body["backtest_runs"] == []
            assert body["recent_audit"] == []
        finally:
            _clear(app, *deps)
