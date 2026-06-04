"""Unit tests — F30 Phase 1: GET /api/v1/experience/fno/portfolio-analytics.

Endpoints under test
--------------------
GET /api/v1/experience/fno/portfolio-analytics?mode=mock   (no auth, no DB)
GET /api/v1/experience/fno/portfolio-analytics?mode=real   (JWT required)
GET /api/v1/experience/fno/portfolio-analytics?mode=paper  (invalid → 422)

Test strategy
-------------
- All tests use TestClient(app, raise_server_exceptions=False) and override
  get_db with a MagicMock session (matching the working pattern in
  test_geography_overview.py, test_api_system.py). The conftest client
  fixture is NOT used because its lifespan tries to connect to the real DB.
- mode=mock tests need no auth override — endpoint returns MOCK_PORTFOLIO
  constant before touching get_optional_user or DB.
- mode=real tests patch get_optional_user via dependency_overrides to inject
  a real UserModel, and patch the four repo classes at their exact import
  paths in the handler module.
- JWT 401 tests use the live endpoint without overriding get_optional_user so
  the real auth path (HTTPBearer(auto_error=False) → None) is exercised.

Patch paths (derived from imports in portfolio_analytics.py)
------------------------------------------------------------
  rita.api.experience.portfolio_analytics.UserPortfolioKeyRepo
  rita.api.experience.portfolio_analytics.UserPortfolioRepo
  rita.api.experience.portfolio_analytics.UserHedgePlanRepo
  rita.api.experience.portfolio_analytics.MarketDataCacheRepository

API-Frontend contract verified (14 schema fields → state assignments)
----------------------------------------------------------------------
  Schema field       → state field (app-init.js replacement)
  portfolio_meta     → state.portfolioMeta
  market             → state.marketData
  positions          → state.positions
  greeks             → state.greeksData
  net_greeks         → state.netGreeks
  net_delta          → state.portDelta
  scenario_levels    → state.scenarioLevels
  payoff             → state.payoffData
  stress             → state.stressData
  hedge_quality      → state.hedgeQuality
  closed_positions   → state.closedPositions
  realized_pnl       → state.realizedPnl
  margin             → state.marginData
  mode               → (envelope field, not a state assignment)
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Exact patch paths — must match imports in the handler module
# ---------------------------------------------------------------------------

_MODULE = "rita.api.experience.portfolio_analytics"
_PATCH_KEY_REPO    = f"{_MODULE}.UserPortfolioKeyRepo"
_PATCH_PORT_REPO   = f"{_MODULE}.UserPortfolioRepo"
_PATCH_HEDGE_REPO  = f"{_MODULE}.UserHedgePlanRepo"
_PATCH_MARKET_REPO = f"{_MODULE}.MarketDataCacheRepository"

# Endpoint URL
_URL = "/api/v1/experience/fno/portfolio-analytics"

# All 14 top-level fields that PortfolioAnalyticsResponse must contain
_TOP_LEVEL_FIELDS = {
    "mode",
    "portfolio_meta",
    "market",
    "positions",
    "greeks",
    "net_greeks",
    "net_delta",
    "scenario_levels",
    "payoff",
    "stress",
    "hedge_quality",
    "closed_positions",
    "realized_pnl",
    "margin",
}

_MOCK_INSTRUMENTS = {"NIFTY", "BANKNIFTY", "ASML", "NVIDIA", "TRU"}

_NOW = datetime(2026, 6, 3, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Mock-data helpers
# ---------------------------------------------------------------------------

def _make_user(user_id: str = "user-001"):
    user = MagicMock()
    user.id = user_id
    return user


def _make_key(key_id: str = "key-abc123"):
    key = MagicMock()
    key.key_id = key_id
    return key


def _make_portfolio(
    key_id: str = "key-abc123",
    name: str = "Test Portfolio",
    total_value_eur: float = 50000.0,
    holdings: list | None = None,
    updated_at: datetime | None = None,
) -> MagicMock:
    """Return a mock ORM portfolio row with NIFTY+ASML holdings by default."""
    port = MagicMock()
    port.key_id = key_id
    port.name = name
    port.total_value_eur = total_value_eur
    port.updated_at = updated_at or _NOW
    if holdings is None:
        holdings = [
            {"instrument_id": "NIFTY",    "allocation_pct": 60.0},
            {"instrument_id": "ASML",     "allocation_pct": 40.0},
        ]
    port.holdings = holdings
    return port


def _make_hedge_plan(
    key_id: str = "key-abc123",
    hedged_ids: list | None = None,
    coverage: int = 50,
) -> MagicMock:
    plan = MagicMock()
    plan.key_id = key_id
    plan.hedged_ids = hedged_ids if hedged_ids is not None else ["NIFTY"]
    plan.coverage = coverage
    return plan


# ---------------------------------------------------------------------------
# TestClient factory following the project pattern
# ---------------------------------------------------------------------------

def _make_client_with_db_mock() -> tuple:
    """Return (TestClient, mock_db, app) with get_db overridden.

    Caller is responsible for cleaning up dependency_overrides after the test.
    """
    from rita.main import app
    from rita.database import get_db

    mock_db = MagicMock()
    app.dependency_overrides[get_db] = lambda: mock_db
    client = TestClient(app, raise_server_exceptions=False)
    return client, mock_db, app


# ---------------------------------------------------------------------------
# Test Class 1 — mode=mock (no auth required, no DB calls)
# ---------------------------------------------------------------------------

class TestMockMode:
    """Tests for mode=mock — endpoint returns MOCK_PORTFOLIO constant."""

    # ── Test 1: status 200 with no auth header ────────────────────────────────

    def test_mock_returns_200_no_auth(self):
        """mode=mock returns 200 without any Authorization header."""
        from rita.main import app
        from rita.database import get_db

        app.dependency_overrides[get_db] = lambda: MagicMock()
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(_URL, params={"mode": "mock"})
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert resp.status_code == 200, (
            f"Expected 200 for mode=mock without auth; got {resp.status_code}: {resp.text}"
        )

    # ── Test 2: all 14 top-level fields present ───────────────────────────────

    def test_mock_has_all_14_top_level_fields(self):
        """mode=mock response contains all 14 top-level PortfolioAnalyticsResponse fields."""
        from rita.main import app
        from rita.database import get_db

        app.dependency_overrides[get_db] = lambda: MagicMock()
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(_URL, params={"mode": "mock"})
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert resp.status_code == 200
        body = resp.json()
        missing = _TOP_LEVEL_FIELDS - set(body.keys())
        assert not missing, (
            f"mode=mock response missing top-level fields: {missing}"
        )

    # ── Test 3: positions array has exactly 5 items ───────────────────────────

    def test_mock_positions_has_5_items(self):
        """mode=mock positions array has exactly 5 items (NIFTY, BANKNIFTY, ASML, NVIDIA, TRU)."""
        from rita.main import app
        from rita.database import get_db

        app.dependency_overrides[get_db] = lambda: MagicMock()
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(_URL, params={"mode": "mock"})
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert resp.status_code == 200
        positions = resp.json()["positions"]
        assert len(positions) == 5, (
            f"Expected 5 positions in mock response; got {len(positions)}"
        )
        instrument_ids = {p["und"] for p in positions}
        assert instrument_ids == _MOCK_INSTRUMENTS, (
            f"Expected instruments {_MOCK_INSTRUMENTS}; got {instrument_ids}"
        )

    # ── Test 4: stress array has exactly 5 items ─────────────────────────────

    def test_mock_stress_has_5_items(self):
        """mode=mock stress array has exactly 5 items."""
        from rita.main import app
        from rita.database import get_db

        app.dependency_overrides[get_db] = lambda: MagicMock()
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(_URL, params={"mode": "mock"})
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert resp.status_code == 200
        stress = resp.json()["stress"]
        assert len(stress) == 5, (
            f"Expected 5 stress events; got {len(stress)}"
        )

    # ── Test 5: payoff has portfolio + hedged with matching length labels/data ─

    def test_mock_payoff_structure(self):
        """mode=mock payoff has 'portfolio' and 'hedged' curves, each with equal-length labels+data."""
        from rita.main import app
        from rita.database import get_db

        app.dependency_overrides[get_db] = lambda: MagicMock()
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(_URL, params={"mode": "mock"})
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert resp.status_code == 200
        payoff = resp.json()["payoff"]
        assert "portfolio" in payoff, "payoff.portfolio missing"
        assert "hedged" in payoff, "payoff.hedged missing"
        for curve_key in ("portfolio", "hedged"):
            curve = payoff[curve_key]
            assert "labels" in curve, f"payoff.{curve_key}.labels missing"
            assert "data" in curve, f"payoff.{curve_key}.data missing"
            assert len(curve["labels"]) == len(curve["data"]), (
                f"payoff.{curve_key}: labels length {len(curve['labels'])} "
                f"!= data length {len(curve['data'])}"
            )

    # ── Test 6: hedge_quality.positions is non-empty ─────────────────────────

    def test_mock_hedge_quality_positions_nonempty(self):
        """mode=mock hedge_quality.positions array is non-empty."""
        from rita.main import app
        from rita.database import get_db

        app.dependency_overrides[get_db] = lambda: MagicMock()
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(_URL, params={"mode": "mock"})
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert resp.status_code == 200
        hq = resp.json()["hedge_quality"]
        assert "positions" in hq, "hedge_quality.positions missing"
        assert len(hq["positions"]) > 0, (
            "mode=mock hedge_quality.positions must be non-empty"
        )


# ---------------------------------------------------------------------------
# Test Class 2 — mode=real, authentication paths
# ---------------------------------------------------------------------------

class TestRealModeAuth:
    """Tests for mode=real auth enforcement (no repo patches needed)."""

    # ── Test 7: mode=real without JWT returns 401 ────────────────────────────

    def test_real_no_jwt_returns_401(self):
        """mode=real without Authorization header returns 401."""
        from rita.main import app
        from rita.database import get_db

        app.dependency_overrides[get_db] = lambda: MagicMock()
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(_URL, params={"mode": "real"})
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert resp.status_code == 401, (
            f"Expected 401 for mode=real without JWT; got {resp.status_code}: {resp.text}"
        )

    # ── Test 8: mode=real with invalid JWT returns 401 ───────────────────────

    def test_real_invalid_jwt_returns_401(self):
        """mode=real with a malformed/invalid JWT token returns 401."""
        from rita.main import app
        from rita.database import get_db

        app.dependency_overrides[get_db] = lambda: MagicMock()
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(
                _URL,
                params={"mode": "real"},
                headers={"Authorization": "Bearer this.is.not.valid"},
            )
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert resp.status_code == 401, (
            f"Expected 401 for invalid JWT; got {resp.status_code}: {resp.text}"
        )


# ---------------------------------------------------------------------------
# Test Class 3 — mode=real, authenticated paths (repos mocked)
# ---------------------------------------------------------------------------

class TestRealModeAuthenticated:
    """Tests for mode=real with injected user and mocked repos."""

    def _client_with_user(self):
        """Create TestClient with get_db mocked and get_optional_user injected."""
        from rita.main import app
        from rita.database import get_db
        from rita.auth import get_optional_user

        app.dependency_overrides[get_db] = lambda: MagicMock()
        app.dependency_overrides[get_optional_user] = lambda: _make_user()
        client = TestClient(app, raise_server_exceptions=False)
        return client, app, get_db, get_optional_user

    def _cleanup(self, app, *deps):
        for dep in deps:
            app.dependency_overrides.pop(dep, None)

    # ── Test 9: valid JWT, no portfolio key → 404 ────────────────────────────

    def test_real_no_portfolio_key_returns_404(self):
        """mode=real with valid JWT but no portfolio key row returns 404."""
        client, app, get_db, get_optional_user = self._client_with_user()
        try:
            with patch(_PATCH_KEY_REPO) as mock_key_cls:
                mock_key_cls.return_value.find_by_user_id.return_value = None
                resp = client.get(_URL, params={"mode": "real"})
        finally:
            self._cleanup(app, get_db, get_optional_user)

        assert resp.status_code == 404, (
            f"Expected 404 when no portfolio key; got {resp.status_code}: {resp.text}"
        )

    # ── Test 10: valid JWT, key exists but no active portfolio → 404 ─────────

    def test_real_no_portfolio_returns_404(self):
        """mode=real with valid JWT and key but no active portfolio returns 404."""
        client, app, get_db, get_optional_user = self._client_with_user()
        try:
            with (
                patch(_PATCH_KEY_REPO) as mock_key_cls,
                patch(_PATCH_PORT_REPO) as mock_port_cls,
            ):
                mock_key_cls.return_value.find_by_user_id.return_value = _make_key()
                mock_port_cls.return_value.find_active_by_key_id.return_value = None
                resp = client.get(_URL, params={"mode": "real"})
        finally:
            self._cleanup(app, get_db, get_optional_user)

        assert resp.status_code == 404, (
            f"Expected 404 when no active portfolio; got {resp.status_code}: {resp.text}"
        )

    # ── Test 11: valid JWT + portfolio → 200 with all 14 top-level fields ────

    def test_real_with_portfolio_returns_200_and_structure(self):
        """mode=real with valid JWT and portfolio returns 200 with all 14 top-level fields."""
        client, app, get_db, get_optional_user = self._client_with_user()
        try:
            with (
                patch(_PATCH_KEY_REPO) as mock_key_cls,
                patch(_PATCH_PORT_REPO) as mock_port_cls,
                patch(_PATCH_HEDGE_REPO) as mock_hedge_cls,
                patch(_PATCH_MARKET_REPO) as mock_market_cls,
            ):
                mock_key_cls.return_value.find_by_user_id.return_value = _make_key()
                mock_port_cls.return_value.find_active_by_key_id.return_value = (
                    _make_portfolio()
                )
                mock_hedge_cls.return_value.find_by_key_id.return_value = (
                    _make_hedge_plan()
                )
                mock_market_cls.return_value.read_all.return_value = []
                resp = client.get(_URL, params={"mode": "real"})
        finally:
            self._cleanup(app, get_db, get_optional_user)

        assert resp.status_code == 200, (
            f"Expected 200 for valid JWT + portfolio; got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        missing = _TOP_LEVEL_FIELDS - set(body.keys())
        assert not missing, (
            f"mode=real response missing top-level fields: {missing}"
        )
        assert body["mode"] == "real"

    # ── Test 12: portfolio exists, no hedge plan → greeks default delta=1.0 ──

    def test_real_no_hedge_plan_greeks_default_delta(self):
        """mode=real, portfolio exists but no hedge plan → every greek has delta=1.0."""
        client, app, get_db, get_optional_user = self._client_with_user()
        try:
            with (
                patch(_PATCH_KEY_REPO) as mock_key_cls,
                patch(_PATCH_PORT_REPO) as mock_port_cls,
                patch(_PATCH_HEDGE_REPO) as mock_hedge_cls,
                patch(_PATCH_MARKET_REPO) as mock_market_cls,
            ):
                mock_key_cls.return_value.find_by_user_id.return_value = _make_key()
                mock_port_cls.return_value.find_active_by_key_id.return_value = (
                    _make_portfolio(
                        holdings=[
                            {"instrument_id": "NIFTY", "allocation_pct": 100.0},
                        ]
                    )
                )
                # No hedge plan stored
                mock_hedge_cls.return_value.find_by_key_id.return_value = None
                mock_market_cls.return_value.read_all.return_value = []
                resp = client.get(_URL, params={"mode": "real"})
        finally:
            self._cleanup(app, get_db, get_optional_user)

        assert resp.status_code == 200, (
            f"Expected 200 even without hedge plan; got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        for greek in body["greeks"]:
            assert greek["delta"] == 1.0, (
                f"Without hedge plan, delta must default to 1.0; "
                f"got delta={greek['delta']} for {greek['und']}"
            )


# ---------------------------------------------------------------------------
# Test Class 4 — Input validation
# ---------------------------------------------------------------------------

class TestInputValidation:
    """Pydantic / FastAPI query-param validation tests."""

    # ── Test 13: invalid mode value returns 422 ───────────────────────────────

    def test_invalid_mode_paper_returns_422(self):
        """mode=paper is not a valid Literal['real','mock'] and returns 422."""
        from rita.main import app
        from rita.database import get_db

        app.dependency_overrides[get_db] = lambda: MagicMock()
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(_URL, params={"mode": "paper"})
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert resp.status_code == 422, (
            f"Expected 422 for mode=paper; got {resp.status_code}: {resp.text}"
        )

    # ── Test 14: default mode (no param) uses real path → 401 without JWT ────

    def test_default_mode_is_real_returns_401_without_auth(self):
        """GET without mode param defaults to mode=real and returns 401 without JWT."""
        from rita.main import app
        from rita.database import get_db

        app.dependency_overrides[get_db] = lambda: MagicMock()
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(_URL)
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert resp.status_code == 401, (
            f"Default mode should be 'real' → 401 without auth; "
            f"got {resp.status_code}: {resp.text}"
        )

    # ── Test 15: mode=mock returns mode field as "mock" ──────────────────────

    def test_mock_mode_field_is_mock(self):
        """mode=mock response envelope has mode='mock'."""
        from rita.main import app
        from rita.database import get_db

        app.dependency_overrides[get_db] = lambda: MagicMock()
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(_URL, params={"mode": "mock"})
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert resp.status_code == 200
        assert resp.json()["mode"] == "mock", (
            f"Expected mode='mock' in response; got {resp.json()['mode']!r}"
        )
