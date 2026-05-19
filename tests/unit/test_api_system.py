"""API contract tests for System CRUD routers (Day 9).

Tests cover: positions, orders, snapshots, trades, alerts, audit, market_data,
config_overrides.

Strategy
--------
- All repository calls are overridden via FastAPI's app.dependency_overrides
  mechanism so no real CSV files are needed.
- Each test installs its override, runs the request, then cleans up.
- conftest.py ensures rita.config._CONFIG_DIR is correct before any import.
"""

from __future__ import annotations

from datetime import datetime, date, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


_NOW = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
_TODAY = date(2026, 4, 1)


# ---------------------------------------------------------------------------
# Helpers — build minimal schema instances for repository return values
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


def _order():
    from rita.schemas.orders import Order
    return Order(
        order_id="ord-001",
        instrument="NIFTY26APR22700CE",
        underlying="NIFTY",
        product="NRML",
        order_type="BUY",
        quantity=75,
        quantity_filled=75,
        avg_price=100.0,
        status="COMPLETE",
        placed_at=_NOW,
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


def _trade():
    from rita.schemas.trades import Trade
    return Trade(
        trade_id="trd-001",
        instrument="NIFTY26APR22700CE",
        underlying="NIFTY",
        expiry="24-Apr-26",
        option_type="CE",
        strike=22700.0,
        side="Long",
        pnl=500.0,
        notes="test trade",
        closed_date=_TODAY,
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


def _audit_log():
    from rita.schemas.audit import AuditLog
    return AuditLog(
        log_id="log-001",
        timestamp=_NOW,
        source="api",
        method="GET",
        path="/api/v1/system/positions/",
        status_code=200,
        duration_ms=15.0,
        args_summary=None,
        result_summary="1 record",
        recorded_at=_NOW,
    )


def _market_data():
    from rita.schemas.market_data import MarketDataCache
    return MarketDataCache(
        cache_id="mdc-001",
        date=_TODAY,
        underlying="NIFTY",
        open=22500.0,
        high=22700.0,
        low=22400.0,
        close=22650.0,
        shares_traded=1000000,
        turnover_cr=5000.0,
        recorded_at=_NOW,
    )


def _config_override():
    from rita.schemas.config_overrides import ConfigOverride
    return ConfigOverride(
        override_id="cfg-001",
        key="simulation_period",
        value="30",
        stage="active",
        description="test override",
        saved_at=_NOW,
        recorded_at=_NOW,
    )


# ---------------------------------------------------------------------------
# Helper context manager for dependency_overrides
# ---------------------------------------------------------------------------

def _override(app, original_dep, mock_value):
    """Return a callable that, when called, returns mock_value."""
    app.dependency_overrides[original_dep] = lambda: mock_value
    return mock_value


def _clear(app, original_dep):
    app.dependency_overrides.pop(original_dep, None)


# ---------------------------------------------------------------------------
# Positions router
# ---------------------------------------------------------------------------

class TestPositionsRouter:
    def test_list_positions_returns_200(self):
        """GET /api/v1/system/positions/ returns 200 and a JSON list."""
        from rita.main import app
        from rita.api.v1.system.positions import get_repo
        mock_repo = MagicMock()
        mock_repo.read_all.return_value = [_position()]
        try:
            _override(app, get_repo, mock_repo)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/system/positions/")
            assert response.status_code == 200
        finally:
            _clear(app, get_repo)

    def test_list_positions_returns_list_type(self):
        """GET /api/v1/system/positions/ response body is a JSON array."""
        from rita.main import app
        from rita.api.v1.system.positions import get_repo
        mock_repo = MagicMock()
        mock_repo.read_all.return_value = []
        try:
            _override(app, get_repo, mock_repo)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/system/positions/")
            assert isinstance(response.json(), list)
        finally:
            _clear(app, get_repo)

    def test_get_position_by_id_returns_200_for_existing(self):
        """GET /api/v1/system/positions/{id} returns 200 when record exists."""
        from rita.main import app
        from rita.api.v1.system.positions import get_repo
        mock_repo = MagicMock()
        mock_repo.find_by_id.return_value = _position()
        try:
            _override(app, get_repo, mock_repo)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/system/positions/pos-001")
            assert response.status_code == 200
        finally:
            _clear(app, get_repo)

    def test_get_position_by_id_returns_404_for_missing(self):
        """GET /api/v1/system/positions/{id} returns 404 when record missing."""
        from rita.main import app
        from rita.api.v1.system.positions import get_repo
        mock_repo = MagicMock()
        mock_repo.find_by_id.return_value = None
        try:
            _override(app, get_repo, mock_repo)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/system/positions/nonexistent")
            assert response.status_code == 404
        finally:
            _clear(app, get_repo)

    def test_get_position_404_has_detail_and_trace_id(self):
        """404 response body has 'detail' and 'trace_id' keys."""
        from rita.main import app
        from rita.api.v1.system.positions import get_repo
        mock_repo = MagicMock()
        mock_repo.find_by_id.return_value = None
        try:
            _override(app, get_repo, mock_repo)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/system/positions/nonexistent")
            body = response.json()
            assert "detail" in body
            assert "trace_id" in body
        finally:
            _clear(app, get_repo)

    def test_put_position_upsert_returns_200(self):
        """PUT /api/v1/system/positions/{id} with valid body returns 200."""
        from rita.main import app
        from rita.api.v1.system.positions import get_repo
        pos = _position()
        mock_repo = MagicMock()
        mock_repo.upsert.return_value = pos
        try:
            _override(app, get_repo, mock_repo)
            client = TestClient(app, raise_server_exceptions=False)
            payload = pos.model_dump(mode="json")
            response = client.put("/api/v1/system/positions/pos-001", json=payload)
            assert response.status_code == 200
        finally:
            _clear(app, get_repo)

    def test_delete_position_returns_404_when_missing(self):
        """DELETE /api/v1/system/positions/{id} returns 404 when record missing."""
        from rita.main import app
        from rita.api.v1.system.positions import get_repo
        mock_repo = MagicMock()
        mock_repo.delete.return_value = False
        try:
            _override(app, get_repo, mock_repo)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.delete("/api/v1/system/positions/nonexistent")
            assert response.status_code == 404
        finally:
            _clear(app, get_repo)


# ---------------------------------------------------------------------------
# Orders router
# ---------------------------------------------------------------------------

class TestOrdersRouter:
    def test_list_orders_returns_200(self):
        """GET /api/v1/system/orders/ returns 200."""
        from rita.main import app
        from rita.api.v1.system.orders import get_repo
        mock_repo = MagicMock()
        mock_repo.read_all.return_value = [_order()]
        try:
            _override(app, get_repo, mock_repo)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/system/orders/")
            assert response.status_code == 200
        finally:
            _clear(app, get_repo)

    def test_get_order_by_id_returns_200_for_existing(self):
        """GET /api/v1/system/orders/{id} returns 200 when record exists."""
        from rita.main import app
        from rita.api.v1.system.orders import get_repo
        mock_repo = MagicMock()
        mock_repo.find_by_id.return_value = _order()
        try:
            _override(app, get_repo, mock_repo)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/system/orders/ord-001")
            assert response.status_code == 200
        finally:
            _clear(app, get_repo)

    def test_get_order_by_id_returns_404_for_missing(self):
        """GET /api/v1/system/orders/{id} returns 404 when record missing."""
        from rita.main import app
        from rita.api.v1.system.orders import get_repo
        mock_repo = MagicMock()
        mock_repo.find_by_id.return_value = None
        try:
            _override(app, get_repo, mock_repo)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/system/orders/nonexistent")
            assert response.status_code == 404
        finally:
            _clear(app, get_repo)

    def test_delete_order_returns_204_when_found(self):
        """DELETE /api/v1/system/orders/{id} returns 204 when record deleted."""
        from rita.main import app
        from rita.api.v1.system.orders import get_repo
        mock_repo = MagicMock()
        mock_repo.delete.return_value = True
        try:
            _override(app, get_repo, mock_repo)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.delete("/api/v1/system/orders/ord-001")
            assert response.status_code == 204
        finally:
            _clear(app, get_repo)


# ---------------------------------------------------------------------------
# Snapshots router
# ---------------------------------------------------------------------------

class TestSnapshotsRouter:
    def test_list_snapshots_returns_200(self):
        """GET /api/v1/system/snapshots/ returns 200."""
        from rita.main import app
        from rita.api.v1.system.snapshots import get_repo
        mock_repo = MagicMock()
        mock_repo.read_all.return_value = []
        try:
            _override(app, get_repo, mock_repo)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/system/snapshots/")
            assert response.status_code == 200
        finally:
            _clear(app, get_repo)

    def test_get_snapshot_returns_404_for_missing(self):
        """GET /api/v1/system/snapshots/{id} returns 404 when record missing."""
        from rita.main import app
        from rita.api.v1.system.snapshots import get_repo
        mock_repo = MagicMock()
        mock_repo.find_by_id.return_value = None
        try:
            _override(app, get_repo, mock_repo)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/system/snapshots/nonexistent")
            assert response.status_code == 404
        finally:
            _clear(app, get_repo)

    def test_get_snapshot_returns_200_for_existing(self):
        """GET /api/v1/system/snapshots/{id} returns 200 when record exists."""
        from rita.main import app
        from rita.api.v1.system.snapshots import get_repo
        mock_repo = MagicMock()
        mock_repo.find_by_id.return_value = _snapshot()
        try:
            _override(app, get_repo, mock_repo)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/system/snapshots/snap-001")
            assert response.status_code == 200
        finally:
            _clear(app, get_repo)


# ---------------------------------------------------------------------------
# Trades router
# ---------------------------------------------------------------------------

class TestTradesRouter:
    def test_list_trades_returns_200(self):
        """GET /api/v1/system/trades/ returns 200."""
        from rita.main import app
        from rita.api.v1.system.trades import get_repo
        mock_repo = MagicMock()
        mock_repo.read_all.return_value = []
        try:
            _override(app, get_repo, mock_repo)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/system/trades/")
            assert response.status_code == 200
        finally:
            _clear(app, get_repo)

    def test_get_trade_returns_404_for_missing(self):
        """GET /api/v1/system/trades/{id} returns 404 when record missing."""
        from rita.main import app
        from rita.api.v1.system.trades import get_repo
        mock_repo = MagicMock()
        mock_repo.find_by_id.return_value = None
        try:
            _override(app, get_repo, mock_repo)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/system/trades/nonexistent")
            assert response.status_code == 404
        finally:
            _clear(app, get_repo)

    def test_get_trade_returns_200_for_existing(self):
        """GET /api/v1/system/trades/{id} returns 200 when record exists."""
        from rita.main import app
        from rita.api.v1.system.trades import get_repo
        mock_repo = MagicMock()
        mock_repo.find_by_id.return_value = _trade()
        try:
            _override(app, get_repo, mock_repo)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/system/trades/trd-001")
            assert response.status_code == 200
        finally:
            _clear(app, get_repo)


# ---------------------------------------------------------------------------
# Alerts router
# ---------------------------------------------------------------------------

class TestAlertsRouter:
    def test_list_alerts_returns_200(self):
        """GET /api/v1/system/alerts/ returns 200."""
        from rita.main import app
        from rita.api.v1.system.alerts import get_repo
        mock_repo = MagicMock()
        mock_repo.read_all.return_value = []
        try:
            _override(app, get_repo, mock_repo)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/system/alerts/")
            assert response.status_code == 200
        finally:
            _clear(app, get_repo)

    def test_get_alert_returns_404_for_missing(self):
        """GET /api/v1/system/alerts/{id} returns 404 when record missing."""
        from rita.main import app
        from rita.api.v1.system.alerts import get_repo
        mock_repo = MagicMock()
        mock_repo.find_by_id.return_value = None
        try:
            _override(app, get_repo, mock_repo)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/system/alerts/nonexistent")
            assert response.status_code == 404
        finally:
            _clear(app, get_repo)

    def test_get_alert_returns_200_for_existing(self):
        """GET /api/v1/system/alerts/{id} returns 200 when record exists."""
        from rita.main import app
        from rita.api.v1.system.alerts import get_repo
        mock_repo = MagicMock()
        mock_repo.find_by_id.return_value = _alert()
        try:
            _override(app, get_repo, mock_repo)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/system/alerts/alt-001")
            assert response.status_code == 200
        finally:
            _clear(app, get_repo)


# ---------------------------------------------------------------------------
# Audit router
# ---------------------------------------------------------------------------

class TestAuditRouter:
    def test_list_audit_returns_200(self):
        """GET /api/v1/system/audit/ returns 200."""
        from rita.main import app
        from rita.api.v1.system.audit import get_repo
        mock_repo = MagicMock()
        mock_repo.read_all.return_value = []
        try:
            _override(app, get_repo, mock_repo)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/system/audit/")
            assert response.status_code == 200
        finally:
            _clear(app, get_repo)

    def test_get_audit_returns_404_for_missing(self):
        """GET /api/v1/system/audit/{id} returns 404 when record missing."""
        from rita.main import app
        from rita.api.v1.system.audit import get_repo
        mock_repo = MagicMock()
        mock_repo.find_by_id.return_value = None
        try:
            _override(app, get_repo, mock_repo)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/system/audit/nonexistent")
            assert response.status_code == 404
        finally:
            _clear(app, get_repo)

    def test_get_audit_returns_200_for_existing(self):
        """GET /api/v1/system/audit/{id} returns 200 when record exists."""
        from rita.main import app
        from rita.api.v1.system.audit import get_repo
        mock_repo = MagicMock()
        mock_repo.find_by_id.return_value = _audit_log()
        try:
            _override(app, get_repo, mock_repo)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/system/audit/log-001")
            assert response.status_code == 200
        finally:
            _clear(app, get_repo)


# ---------------------------------------------------------------------------
# Market Data router
# ---------------------------------------------------------------------------

class TestMarketDataRouter:
    def test_list_market_data_returns_200(self):
        """GET /api/v1/system/market_data/ returns 200."""
        from rita.main import app
        from rita.api.v1.system.market_data import get_repo
        mock_repo = MagicMock()
        mock_repo.read_all.return_value = []
        try:
            _override(app, get_repo, mock_repo)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/system/market_data/")
            assert response.status_code == 200
        finally:
            _clear(app, get_repo)

    def test_get_market_data_returns_404_for_missing(self):
        """GET /api/v1/system/market_data/{id} returns 404 when record missing."""
        from rita.main import app
        from rita.api.v1.system.market_data import get_repo
        mock_repo = MagicMock()
        mock_repo.find_by_id.return_value = None
        try:
            _override(app, get_repo, mock_repo)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/system/market_data/nonexistent")
            assert response.status_code == 404
        finally:
            _clear(app, get_repo)

    def test_get_market_data_returns_200_for_existing(self):
        """GET /api/v1/system/market_data/{id} returns 200 when record exists."""
        from rita.main import app
        from rita.api.v1.system.market_data import get_repo
        mock_repo = MagicMock()
        mock_repo.find_by_id.return_value = _market_data()
        try:
            _override(app, get_repo, mock_repo)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/system/market_data/mdc-001")
            assert response.status_code == 200
        finally:
            _clear(app, get_repo)


# ---------------------------------------------------------------------------
# Config Overrides router
# ---------------------------------------------------------------------------

class TestConfigOverridesRouter:
    def test_list_config_overrides_returns_200(self):
        """GET /api/v1/system/config_overrides/ returns 200."""
        from rita.main import app
        from rita.api.v1.system.config_overrides import get_repo
        mock_repo = MagicMock()
        mock_repo.read_all.return_value = []
        try:
            _override(app, get_repo, mock_repo)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/system/config_overrides/")
            assert response.status_code == 200
        finally:
            _clear(app, get_repo)

    def test_get_config_override_returns_404_for_missing(self):
        """GET /api/v1/system/config_overrides/{id} returns 404 when record missing."""
        from rita.main import app
        from rita.api.v1.system.config_overrides import get_repo
        mock_repo = MagicMock()
        mock_repo.find_by_id.return_value = None
        try:
            _override(app, get_repo, mock_repo)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/system/config_overrides/nonexistent")
            assert response.status_code == 404
        finally:
            _clear(app, get_repo)

    def test_get_config_override_returns_200_for_existing(self):
        """GET /api/v1/system/config_overrides/{id} returns 200 when record exists."""
        from rita.main import app
        from rita.api.v1.system.config_overrides import get_repo
        mock_repo = MagicMock()
        mock_repo.find_by_id.return_value = _config_override()
        try:
            _override(app, get_repo, mock_repo)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/system/config_overrides/cfg-001")
            assert response.status_code == 200
        finally:
            _clear(app, get_repo)

    def test_put_config_override_upsert_returns_200(self):
        """PUT /api/v1/system/config_overrides/{id} with valid body returns 200."""
        from rita.main import app
        from rita.api.v1.system.config_overrides import get_repo
        co = _config_override()
        mock_repo = MagicMock()
        mock_repo.upsert.return_value = co
        try:
            _override(app, get_repo, mock_repo)
            client = TestClient(app, raise_server_exceptions=False)
            payload = co.model_dump(mode="json")
            response = client.put("/api/v1/system/config_overrides/cfg-001", json=payload)
            assert response.status_code == 200
        finally:
            _clear(app, get_repo)
