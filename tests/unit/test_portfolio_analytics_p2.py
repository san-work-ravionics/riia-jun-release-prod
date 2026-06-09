"""Unit tests — F30 Phase 2: portfolio-analytics API-frontend contract.

Phase 2 is a pure JS frontend refactor + HTML toggle addition — no new Python
backend code was written.  These tests verify the Python backend contract that
Phase 2 relies on (the Phase 1 endpoint must still honour exactly the fields
the Phase 2 JS reads from `data.*`).

Endpoints under test
--------------------
GET /api/v1/experience/fno/portfolio-analytics?mode=mock   (no auth, no DB)
GET /api/v1/experience/fno/portfolio-analytics?mode=real   (JWT required)

API-Frontend contract (Phase 2 JS reads — from app-init.js lines 100–112)
--------------------------------------------------------------------------
  data.portfolio_meta    → state.portfolioMeta
  data.market            → state.marketData
  data.positions         → state.positions
  data.greeks            → state.greeksData
  data.net_greeks        → state.netGreeks
  data.net_delta         → state.portDelta
  data.scenario_levels   → state.scenarioLevels
  data.payoff            → state.payoffData
  data.stress            → state.stressData
  data.hedge_quality     → state.hedgeQuality
  data.closed_positions  → state.closedPositions
  data.realized_pnl      → state.realizedPnl
  data.margin            → state.marginData

  Also accessed: data.portfolio_meta?.updated_at (sidebar as-of timestamp).

  NOTE: `mode` is an envelope field present in PortfolioAnalyticsResponse
  but is NOT read from `data.` in the state-mapping block; it is set via
  `state.analyticsMode = mode` from the query param at the top of initApp.

Toggle edge-cases from Architect design section
------------------------------------------------
- mode=real + 401 → JS calls initApp('mock') fallback (backend must return 401)
- mode=real + 404 → JS calls initApp('mock') fallback (backend must return 404)
- mode=mock needs no JWT (backend must not require auth for mock)
- Toggle disables / re-enables #analytics-mode-chk DOM element during fetch
- state.analyticsMode default is 'mock'
- fetchPositions() shim delegates to initApp(state.analyticsMode)

State.js Phase 2 fields added
------------------------------
- portfolioMeta: null  (was missing before Phase 2)
- analyticsMode: 'mock'  (was missing before Phase 2)
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Patch paths (same as Phase 1 tests — handler module unchanged in Phase 2)
# ---------------------------------------------------------------------------

_MODULE = "rita.api.experience.portfolio_analytics"
_PATCH_KEY_REPO    = f"{_MODULE}.UserPortfolioKeyRepo"
_PATCH_PORT_REPO   = f"{_MODULE}.UserPortfolioRepo"
_PATCH_HEDGE_REPO  = f"{_MODULE}.UserHedgePlanRepo"
_PATCH_MARKET_REPO = f"{_MODULE}.MarketDataCacheRepository"

_URL = "/api/v1/experience/fno/portfolio-analytics"

# The 13 fields that Phase 2 app-init.js reads from `data.*` (state-mapping block)
_STATE_MAPPED_FIELDS = {
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

# All 14 top-level fields including the envelope `mode` field
_ALL_TOP_LEVEL_FIELDS = _STATE_MAPPED_FIELDS | {"mode"}

_NOW = datetime(2026, 6, 4, 10, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Mock-data helpers (mirror Phase 1 test helpers for consistency)
# ---------------------------------------------------------------------------

def _make_user(user_id: str = "user-p2-001"):
    user = MagicMock()
    user.id = user_id
    return user


def _make_key(key_id: str = "key-p2-abc"):
    key = MagicMock()
    key.key_id = key_id
    return key


def _make_portfolio(
    key_id: str = "key-p2-abc",
    name: str = "Phase2 Test Portfolio",
    total_value_eur: float = 75000.0,
    holdings: list | None = None,
    updated_at: datetime | None = None,
) -> MagicMock:
    port = MagicMock()
    port.key_id = key_id
    port.name = name
    port.total_value_eur = total_value_eur
    port.updated_at = updated_at or _NOW
    if holdings is None:
        holdings = [
            {"instrument_id": "NIFTY", "allocation_pct": 70.0},
            {"instrument_id": "ASML",  "allocation_pct": 30.0},
        ]
    port.holdings = holdings
    return port


def _make_hedge_plan(key_id: str = "key-p2-abc") -> MagicMock:
    plan = MagicMock()
    plan.key_id = key_id
    plan.hedged_ids = ["NIFTY"]
    plan.coverage = 60
    return plan


def _make_client() -> tuple:
    """Return (client, app, get_db) with get_db overridden to a MagicMock."""
    from rita.main import app
    from rita.database import get_db

    app.dependency_overrides[get_db] = lambda: MagicMock()
    client = TestClient(app, raise_server_exceptions=False)
    return client, app, get_db


def _cleanup(app, *deps):
    for dep in deps:
        app.dependency_overrides.pop(dep, None)


# ---------------------------------------------------------------------------
# Test Class 1 — API-Frontend Contract: all 13 state-mapped fields present
# ---------------------------------------------------------------------------

class TestApiFrontendContract:
    """Verify the endpoint response contains every field that Phase 2 JS reads.

    These tests are the primary Phase 2 QA gate: if the backend removes or
    renames any of the 13 `data.*` fields, the JS toggle will silently map
    `undefined` to state, breaking all dashboard sections.
    """

    # ── Test 1: mode=mock response has all 13 state-mapped fields ─────────────

    def test_mock_has_all_13_state_mapped_fields(self):
        """mode=mock response contains all 13 fields that app-init.js reads."""
        client, app, get_db = _make_client()
        try:
            resp = client.get(_URL, params={"mode": "mock"})
        finally:
            _cleanup(app, get_db)

        assert resp.status_code == 200, (
            f"Expected 200 for mode=mock; got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        missing = _STATE_MAPPED_FIELDS - set(body.keys())
        assert not missing, (
            f"Backend response missing state-mapped fields consumed by Phase 2 JS: {missing}"
        )

    # ── Test 2: mode=mock has all 14 top-level fields including envelope ───────

    def test_mock_has_all_14_top_level_fields_including_mode_envelope(self):
        """mode=mock response contains all 14 PortfolioAnalyticsResponse fields."""
        client, app, get_db = _make_client()
        try:
            resp = client.get(_URL, params={"mode": "mock"})
        finally:
            _cleanup(app, get_db)

        assert resp.status_code == 200
        body = resp.json()
        missing = _ALL_TOP_LEVEL_FIELDS - set(body.keys())
        assert not missing, (
            f"PortfolioAnalyticsResponse missing top-level fields: {missing}"
        )

    # ── Test 3: portfolio_meta has updated_at (sidebar as-of timestamp) ────────

    def test_mock_portfolio_meta_has_updated_at(self):
        """portfolio_meta.updated_at must be present — Phase 2 JS uses it for the sidebar."""
        client, app, get_db = _make_client()
        try:
            resp = client.get(_URL, params={"mode": "mock"})
        finally:
            _cleanup(app, get_db)

        assert resp.status_code == 200
        meta = resp.json().get("portfolio_meta", {})
        assert "updated_at" in meta, (
            "portfolio_meta.updated_at missing — Phase 2 JS sidebar timestamp will break"
        )

    # ── Test 4: mode field in response equals query param value ───────────────

    def test_mode_envelope_field_reflects_query_param(self):
        """The `mode` envelope field in the response matches the requested mode."""
        client, app, get_db = _make_client()
        try:
            resp = client.get(_URL, params={"mode": "mock"})
        finally:
            _cleanup(app, get_db)

        assert resp.status_code == 200
        assert resp.json()["mode"] == "mock", (
            f"Expected mode='mock' in response; got {resp.json()['mode']!r}"
        )

    # ── Test 5: payoff has correct nested structure (Phase 2 renderPayoffChart) ─

    def test_mock_payoff_nested_structure_for_render_payoff_chart(self):
        """payoff.portfolio and payoff.hedged each have labels + data arrays of equal length."""
        client, app, get_db = _make_client()
        try:
            resp = client.get(_URL, params={"mode": "mock"})
        finally:
            _cleanup(app, get_db)

        assert resp.status_code == 200
        payoff = resp.json()["payoff"]
        for curve in ("portfolio", "hedged"):
            assert curve in payoff, f"payoff.{curve} missing"
            assert "labels" in payoff[curve], f"payoff.{curve}.labels missing"
            assert "data" in payoff[curve], f"payoff.{curve}.data missing"
            assert len(payoff[curve]["labels"]) == len(payoff[curve]["data"]), (
                f"payoff.{curve}: labels/data length mismatch"
            )

    # ── Test 6: net_greeks has delta, theta, vega (renderGreeksCards) ──────────

    def test_mock_net_greeks_has_delta_theta_vega(self):
        """net_greeks has delta, theta, vega — required by renderGreeksCards."""
        client, app, get_db = _make_client()
        try:
            resp = client.get(_URL, params={"mode": "mock"})
        finally:
            _cleanup(app, get_db)

        assert resp.status_code == 200
        net_greeks = resp.json()["net_greeks"]
        for field in ("delta", "theta", "vega"):
            assert field in net_greeks, (
                f"net_greeks.{field} missing — renderGreeksCards will break"
            )

    # ── Test 7: hedge_quality has positions array (renderHedgeRadar) ───────────

    def test_mock_hedge_quality_positions_array_present(self):
        """hedge_quality.positions array present — required by renderHedgeRadar."""
        client, app, get_db = _make_client()
        try:
            resp = client.get(_URL, params={"mode": "mock"})
        finally:
            _cleanup(app, get_db)

        assert resp.status_code == 200
        hq = resp.json()["hedge_quality"]
        assert "positions" in hq, "hedge_quality.positions missing"
        assert isinstance(hq["positions"], list), (
            "hedge_quality.positions must be a list"
        )

    # ── Test 8: stress is a list (renderStressScenarios) ──────────────────────

    def test_mock_stress_is_list(self):
        """stress must be a list — renderStressScenarios iterates it."""
        client, app, get_db = _make_client()
        try:
            resp = client.get(_URL, params={"mode": "mock"})
        finally:
            _cleanup(app, get_db)

        assert resp.status_code == 200
        assert isinstance(resp.json()["stress"], list), (
            "stress must be a list — renderStressScenarios will break"
        )

    # ── Test 9: positions is a list (renderPositionsTable) ────────────────────

    def test_mock_positions_is_list(self):
        """positions must be a list — renderPositionsTable iterates it."""
        client, app, get_db = _make_client()
        try:
            resp = client.get(_URL, params={"mode": "mock"})
        finally:
            _cleanup(app, get_db)

        assert resp.status_code == 200
        assert isinstance(resp.json()["positions"], list), (
            "positions must be a list — renderPositionsTable will break"
        )

    # ── Test 10: greeks is a list (renderGreeksTable) ─────────────────────────

    def test_mock_greeks_is_list(self):
        """greeks must be a list — renderGreeksTable iterates it."""
        client, app, get_db = _make_client()
        try:
            resp = client.get(_URL, params={"mode": "mock"})
        finally:
            _cleanup(app, get_db)

        assert resp.status_code == 200
        assert isinstance(resp.json()["greeks"], list), (
            "greeks must be a list — renderGreeksTable will break"
        )

    # ── Test 11: closed_positions is a list (renderClosedPositions) ───────────

    def test_mock_closed_positions_is_list(self):
        """closed_positions must be a list — renderClosedPositions iterates it."""
        client, app, get_db = _make_client()
        try:
            resp = client.get(_URL, params={"mode": "mock"})
        finally:
            _cleanup(app, get_db)

        assert resp.status_code == 200
        assert isinstance(resp.json()["closed_positions"], list), (
            "closed_positions must be a list"
        )

    # ── Test 12: realized_pnl is a number (renderClosedPositions summary) ──────

    def test_mock_realized_pnl_is_numeric(self):
        """realized_pnl must be a number — renderClosedPositions displays it."""
        client, app, get_db = _make_client()
        try:
            resp = client.get(_URL, params={"mode": "mock"})
        finally:
            _cleanup(app, get_db)

        assert resp.status_code == 200
        realized = resp.json()["realized_pnl"]
        assert isinstance(realized, (int, float)), (
            f"realized_pnl must be numeric; got {type(realized)}"
        )

    # ── Test 13: margin is a dict (renderMarginKpis) ──────────────────────────

    def test_mock_margin_is_dict(self):
        """margin must be a dict — renderMarginKpis reads keys from it."""
        client, app, get_db = _make_client()
        try:
            resp = client.get(_URL, params={"mode": "mock"})
        finally:
            _cleanup(app, get_db)

        assert resp.status_code == 200
        assert isinstance(resp.json()["margin"], dict), (
            "margin must be a dict — renderMarginKpis will break"
        )


# ---------------------------------------------------------------------------
# Test Class 2 — Toggle Auth Edge Cases (Phase 2 Architect design)
# ---------------------------------------------------------------------------

class TestToggleAuthEdgeCases:
    """Verify backend returns the HTTP statuses that Phase 2 toggle logic depends on.

    Phase 2 app-init.js discriminates 401 and 404 to fall back to mock mode.
    If the backend changes these status codes, the fallback logic silently breaks.
    """

    # ── Test 14: mode=mock returns 200 with no auth header ────────────────────

    def test_mock_mode_returns_200_no_auth(self):
        """mode=mock returns 200 without any Authorization header (toggle edge case)."""
        client, app, get_db = _make_client()
        try:
            resp = client.get(_URL, params={"mode": "mock"})
        finally:
            _cleanup(app, get_db)

        assert resp.status_code == 200, (
            f"mode=mock must return 200 with no auth — toggle fallback depends on this; "
            f"got {resp.status_code}: {resp.text}"
        )

    # ── Test 15: mode=real without JWT returns 401 ────────────────────────────

    def test_real_mode_no_jwt_returns_401(self):
        """mode=real without JWT returns 401 — Phase 2 JS detects this and falls back to mock."""
        client, app, get_db = _make_client()
        try:
            resp = client.get(_URL, params={"mode": "real"})
        finally:
            _cleanup(app, get_db)

        assert resp.status_code == 401, (
            f"mode=real without JWT must return 401 for Phase 2 fallback logic; "
            f"got {resp.status_code}: {resp.text}"
        )

    # ── Test 16: mode=real with malformed JWT returns 401 ────────────────────

    def test_real_mode_invalid_jwt_returns_401(self):
        """mode=real with malformed JWT returns 401 — Phase 2 JS detects this and falls back."""
        client, app, get_db = _make_client()
        try:
            resp = client.get(
                _URL,
                params={"mode": "real"},
                headers={"Authorization": "Bearer not.a.valid.token"},
            )
        finally:
            _cleanup(app, get_db)

        assert resp.status_code == 401, (
            f"mode=real with invalid JWT must return 401; got {resp.status_code}: {resp.text}"
        )

    # ── Test 17: mode=real, valid JWT, no portfolio key → 404 ────────────────

    def test_real_mode_no_portfolio_key_returns_404(self):
        """mode=real with valid JWT but no portfolio key returns 404 — triggers JS fallback."""
        from rita.main import app
        from rita.database import get_db
        from rita.auth import get_optional_user

        app.dependency_overrides[get_db] = lambda: MagicMock()
        app.dependency_overrides[get_optional_user] = lambda: _make_user()
        client = TestClient(app, raise_server_exceptions=False)
        try:
            with patch(_PATCH_KEY_REPO) as mock_key_cls:
                mock_key_cls.return_value.find_by_user_id.return_value = None
                resp = client.get(_URL, params={"mode": "real"})
        finally:
            _cleanup(app, get_db, get_optional_user)

        assert resp.status_code == 404, (
            f"mode=real with no portfolio key must return 404 for Phase 2 fallback; "
            f"got {resp.status_code}: {resp.text}"
        )

    # ── Test 18: mode=real, valid JWT, no active portfolio → 404 ─────────────

    def test_real_mode_no_active_portfolio_returns_404(self):
        """mode=real with valid JWT and key but no active portfolio returns 404."""
        from rita.main import app
        from rita.database import get_db
        from rita.auth import get_optional_user

        app.dependency_overrides[get_db] = lambda: MagicMock()
        app.dependency_overrides[get_optional_user] = lambda: _make_user()
        client = TestClient(app, raise_server_exceptions=False)
        try:
            with (
                patch(_PATCH_KEY_REPO) as mock_key_cls,
                patch(_PATCH_PORT_REPO) as mock_port_cls,
            ):
                mock_key_cls.return_value.find_by_user_id.return_value = _make_key()
                mock_port_cls.return_value.find_active_by_key_id.return_value = None
                resp = client.get(_URL, params={"mode": "real"})
        finally:
            _cleanup(app, get_db, get_optional_user)

        assert resp.status_code == 404, (
            f"mode=real with no active portfolio must return 404; "
            f"got {resp.status_code}: {resp.text}"
        )

    # ── Test 19: mode=real with valid JWT + portfolio → 200 ──────────────────

    def test_real_mode_valid_jwt_and_portfolio_returns_200(self):
        """mode=real with valid JWT and a configured portfolio returns 200 with all fields."""
        from rita.main import app
        from rita.database import get_db
        from rita.auth import get_optional_user

        app.dependency_overrides[get_db] = lambda: MagicMock()
        app.dependency_overrides[get_optional_user] = lambda: _make_user()
        client = TestClient(app, raise_server_exceptions=False)
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
            _cleanup(app, get_db, get_optional_user)

        assert resp.status_code == 200, (
            f"mode=real with valid JWT + portfolio must return 200; "
            f"got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        missing = _STATE_MAPPED_FIELDS - set(body.keys())
        assert not missing, (
            f"mode=real response missing state-mapped fields: {missing}"
        )
        assert body["mode"] == "real"


# ---------------------------------------------------------------------------
# Test Class 3 — state.js Phase 2 fields contract
# ---------------------------------------------------------------------------

class TestStateJsContract:
    """Verify that the Phase 2 state.js additions are present.

    These tests are structural: they parse the state.js file content directly
    to ensure `portfolioMeta` and `analyticsMode` were added as required by
    the Phase 2 Architect DoD checklist items 1 and 3.
    """

    _STATE_JS_PATH = (
        "dashboard/js/fno/state.js"
    )

    def _read_state_js(self) -> str:
        import os
        worktree = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        full_path = os.path.join(worktree, self._STATE_JS_PATH)
        with open(full_path) as f:
            return f.read()

    # ── Test 20: state.js has portfolioMeta field ─────────────────────────────

    def test_state_js_has_portfolio_meta_field(self):
        """state.js must declare portfolioMeta (added in Phase 2 — DoD item 1)."""
        content = self._read_state_js()
        assert "portfolioMeta" in content, (
            "state.js is missing portfolioMeta field — Phase 2 DoD item 1 not satisfied"
        )

    # ── Test 21: state.js has analyticsMode field ─────────────────────────────

    def test_state_js_has_analytics_mode_field(self):
        """state.js must declare analyticsMode (added in Phase 2 — DoD item 1)."""
        content = self._read_state_js()
        assert "analyticsMode" in content, (
            "state.js is missing analyticsMode field — Phase 2 DoD item 1 not satisfied"
        )

    # ── Test 22: analyticsMode default is 'mock' ──────────────────────────────

    def test_state_js_analytics_mode_default_is_mock(self):
        """state.analyticsMode must default to 'mock' (safe default per Phase 2 design)."""
        content = self._read_state_js()
        assert "analyticsMode: 'mock'" in content, (
            "state.analyticsMode default must be 'mock' — safe default per Phase 2 design"
        )


# ---------------------------------------------------------------------------
# Test Class 4 — app-init.js Phase 2 contract assertions
# ---------------------------------------------------------------------------

class TestAppInitJsContract:
    """Structural checks on app-init.js to verify Phase 2 implementation."""

    _APP_INIT_JS_PATH = "dashboard/js/fno/app-init.js"

    def _read_app_init_js(self) -> str:
        import os
        worktree = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        full_path = os.path.join(worktree, self._APP_INIT_JS_PATH)
        with open(full_path) as f:
            return f.read()

    # ── Test 23: initApp has mode='mock' default parameter ────────────────────

    def test_app_init_has_mode_mock_default(self):
        """initApp must have mode='mock' default — Phase 2 DoD item 2."""
        content = self._read_app_init_js()
        assert "initApp(mode = 'mock')" in content or "initApp(mode='mock')" in content, (
            "app-init.js initApp signature must have mode='mock' default — Phase 2 DoD item 2"
        )

    # ── Test 24: single fetch to portfolio-analytics endpoint ─────────────────

    def test_app_init_calls_portfolio_analytics_endpoint(self):
        """app-init.js must call the portfolio-analytics endpoint (Phase 2 DoD item 2)."""
        content = self._read_app_init_js()
        assert "portfolio-analytics" in content, (
            "app-init.js must call /api/v1/experience/fno/portfolio-analytics"
        )

    # ── Test 25: all 13 data.field reads present ──────────────────────────────

    def test_app_init_reads_all_13_state_fields_from_data(self):
        """app-init.js must read all 13 state-mapped fields from data.* (Phase 2 DoD item 3)."""
        content = self._read_app_init_js()
        expected_reads = [
            "data.portfolio_meta",
            "data.market",
            "data.positions",
            "data.greeks",
            "data.net_greeks",
            "data.net_delta",
            "data.scenario_levels",
            "data.payoff",
            "data.stress",
            "data.hedge_quality",
            "data.closed_positions",
            "data.realized_pnl",
            "data.margin",
        ]
        missing = [f for f in expected_reads if f not in content]
        assert not missing, (
            f"app-init.js missing data.field reads: {missing} — Phase 2 DoD item 3"
        )

    # ── Test 26: fetchPositions shim is exported ──────────────────────────────

    def test_app_init_exports_fetch_positions_shim(self):
        """fetchPositions shim must be exported — Phase 2 DoD item 4."""
        content = self._read_app_init_js()
        assert "export async function fetchPositions" in content, (
            "app-init.js must export fetchPositions shim — Phase 2 DoD item 4"
        )

    # ── Test 27: fetchPositions delegates to initApp ──────────────────────────

    def test_fetch_positions_shim_delegates_to_init_app(self):
        """fetchPositions must delegate to initApp — preserves single-fetch architecture."""
        content = self._read_app_init_js()
        assert "return initApp(state.analyticsMode)" in content, (
            "fetchPositions must delegate to initApp(state.analyticsMode)"
        )

    # ── Test 28: auth_token key used (not rita_token or jwt_token) ─────────────

    def test_app_init_uses_correct_auth_token_key(self):
        """app-init.js must use 'auth_token' as the sessionStorage key (FC-AUTH-KEY)."""
        content = self._read_app_init_js()
        assert "sessionStorage.getItem('auth_token')" in content, (
            "app-init.js must use auth_token key — FC-AUTH-KEY rule"
        )

    # ── Test 29: 401 error path falls back ────────────────────────────────────

    def test_app_init_handles_401_response(self):
        """app-init.js must handle status === 401 response (Phase 2 toggle edge case)."""
        content = self._read_app_init_js()
        assert "401" in content, (
            "app-init.js must handle 401 response for toggle fallback logic"
        )

    # ── Test 30: 404 error path falls back ────────────────────────────────────

    def test_app_init_handles_404_response(self):
        """app-init.js must handle status === 404 response (Phase 2 toggle edge case)."""
        content = self._read_app_init_js()
        assert "404" in content, (
            "app-init.js must handle 404 response for toggle fallback logic"
        )


# ---------------------------------------------------------------------------
# Test Class 5 — main.js Phase 2 window bindings
# ---------------------------------------------------------------------------

class TestMainJsContract:
    """Structural checks on main.js for Phase 2 window binding."""

    _MAIN_JS_PATH = "dashboard/js/fno/main.js"

    def _read_main_js(self) -> str:
        import os
        worktree = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        full_path = os.path.join(worktree, self._MAIN_JS_PATH)
        with open(full_path) as f:
            return f.read()

    # ── Test 31: window.toggleAnalyticsMode bound ─────────────────────────────

    def test_main_js_binds_toggle_analytics_mode(self):
        """main.js must bind window.toggleAnalyticsMode — Phase 2 DoD item 5."""
        content = self._read_main_js()
        assert "window.toggleAnalyticsMode" in content, (
            "main.js must bind window.toggleAnalyticsMode — Phase 2 DoD item 5"
        )

    # ── Test 32: toggleAnalyticsMode calls initApp ────────────────────────────

    def test_main_js_toggle_calls_init_app(self):
        """window.toggleAnalyticsMode must call initApp — Phase 2 single-fetch architecture."""
        content = self._read_main_js()
        assert "initApp(state.analyticsMode)" in content, (
            "window.toggleAnalyticsMode must call initApp(state.analyticsMode)"
        )

    # ── Test 33: analytics-mode-error element cleared on toggle ───────────────

    def test_main_js_toggle_clears_error_element(self):
        """toggleAnalyticsMode must clear analytics-mode-error on each toggle."""
        content = self._read_main_js()
        assert "analytics-mode-error" in content, (
            "toggleAnalyticsMode must reference analytics-mode-error to clear it"
        )
