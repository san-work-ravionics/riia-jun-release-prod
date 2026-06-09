"""Unit tests for F29 Phase 0 — duration param removal from portfolio-hedge endpoint.

Changes under test
------------------
- `portfolio_hedge.py`: `duration` Query param removed; `t_months` hardcoded to 12.0.
- The response field `duration` is always `"1y"` regardless of any query param supplied.
- FastAPI ignores unknown query params by default (no `extra='forbid'` on the model).

Test strategy
-------------
- HTTP tests use the ``client`` fixture from conftest.py (in-memory SQLite, TestClient
  with get_db override).
- Authentication is bypassed via ``dependency_overrides[get_current_user]``.
- The three repository calls (UserPortfolioKeyRepo, UserPortfolioRepo,
  MarketDataCacheRepository) are patched so the tests have no dependency on seeded data.
- Response JSON is asserted for shape and the hardcoded ``duration: "1y"`` contract.

Contract being verified
-----------------------
  Backend field               | Expected         | JS reads from apiHedge
  ----------------------------|------------------|----------------------------
  PortfolioHedgeResponse.duration  | "1y" always  | not read (removed in F29 P0)
  PortfolioHedgeResponse.coverage  | echoed int    | _state.coverage
  PortfolioHedgeResponse.holdings  | list[HedgeHolding] | _state.apiHedge.holdings
  PortfolioHedgeResponse.aggregate | HedgeAggregate| rendered in hedge table
  HedgeHolding.duration            | "1y" always   | not sent as query param
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers — build lightweight mock objects that satisfy the handler's duck
# typing without requiring real ORM instances.
# ---------------------------------------------------------------------------

def _make_key(key_id: str = "key-001"):
    key = MagicMock()
    key.key_id = key_id
    return key


def _make_portfolio(holdings=None, total_value_eur=None):
    portfolio = MagicMock()
    portfolio.holdings = holdings or [
        {"instrument_id": "RELIANCE", "allocation_pct": 60.0},
        {"instrument_id": "TCS", "allocation_pct": 40.0},
    ]
    portfolio.total_value_eur = total_value_eur
    return portfolio


def _make_user(user_id: str = "user-001"):
    user = MagicMock()
    user.id = user_id
    return user


# ---------------------------------------------------------------------------
# Patch helpers — three repositories need to return sensible mock data.
# MarketDataCacheRepository.read_all returns an empty list so the handler
# falls back to the default vol of 25.0 (< 20 closes path).
# ---------------------------------------------------------------------------

_PATCH_KEY_REPO  = "rita.api.experience.portfolio_hedge.UserPortfolioKeyRepo"
_PATCH_PORT_REPO = "rita.api.experience.portfolio_hedge.UserPortfolioRepo"
_PATCH_MKT_REPO  = "rita.api.experience.portfolio_hedge.MarketDataCacheRepository"
_PATCH_AUTH      = "rita.auth.get_current_user"


# ---------------------------------------------------------------------------
# Test Class 1 — Happy path: endpoint returns 200 and duration is always "1y"
# ---------------------------------------------------------------------------

class TestPortfolioHedgeDurationHardcoded:
    """GET /api/v1/experience/fno/portfolio-hedge must always return duration='1y'.

    F29 Phase 0 removes the duration Query param and hardcodes t_months=12.0.
    The response must always carry duration='1y' at both the top-level
    PortfolioHedgeResponse and within every HedgeHolding.
    """

    @pytest.fixture(autouse=True)
    def _setup(self, client, db_session):
        """Override auth dependency for all tests in this class."""
        from rita.auth import get_current_user
        from rita.main import app

        app.dependency_overrides[get_current_user] = lambda: _make_user()
        yield
        app.dependency_overrides.pop(get_current_user, None)

    # ── Test 1a — Happy path: 200 response with duration='1y' ──────────────

    def test_happy_path_returns_200_with_duration_1y(self, client):
        """Happy path: no query params → 200, top-level duration is '1y'."""
        with (
            patch(_PATCH_KEY_REPO) as mock_key_cls,
            patch(_PATCH_PORT_REPO) as mock_port_cls,
            patch(_PATCH_MKT_REPO) as mock_mkt_cls,
        ):
            mock_key_cls.return_value.find_by_user_id.return_value = _make_key()
            mock_port_cls.return_value.find_active_by_key_id.return_value = _make_portfolio()
            mock_mkt_cls.return_value.read_all.return_value = []

            resp = client.get("/api/v1/experience/fno/portfolio-hedge?coverage=50")

        assert resp.status_code == 200, (
            f"Expected HTTP 200 but got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        assert body["duration"] == "1y", (
            f"Top-level response duration must be '1y' but got '{body['duration']}'"
        )

    # ── Test 1b — Happy path: each HedgeHolding also has duration='1y' ─────

    def test_happy_path_each_holding_has_duration_1y(self, client):
        """Happy path: every holding in the response has duration='1y'."""
        with (
            patch(_PATCH_KEY_REPO) as mock_key_cls,
            patch(_PATCH_PORT_REPO) as mock_port_cls,
            patch(_PATCH_MKT_REPO) as mock_mkt_cls,
        ):
            mock_key_cls.return_value.find_by_user_id.return_value = _make_key()
            mock_port_cls.return_value.find_active_by_key_id.return_value = _make_portfolio()
            mock_mkt_cls.return_value.read_all.return_value = []

            resp = client.get("/api/v1/experience/fno/portfolio-hedge?coverage=50")

        assert resp.status_code == 200
        body = resp.json()
        holdings = body.get("holdings", [])
        assert len(holdings) > 0, "Response must contain at least one holding"
        for h in holdings:
            assert h["duration"] == "1y", (
                f"Holding '{h.get('instrument_id')}' has duration='{h['duration']}', "
                "expected '1y'"
            )

    # ── Test 1c — Happy path: response contains all required schema fields ──

    def test_happy_path_response_shape_matches_schema(self, client):
        """Response JSON must contain all PortfolioHedgeResponse fields."""
        with (
            patch(_PATCH_KEY_REPO) as mock_key_cls,
            patch(_PATCH_PORT_REPO) as mock_port_cls,
            patch(_PATCH_MKT_REPO) as mock_mkt_cls,
        ):
            mock_key_cls.return_value.find_by_user_id.return_value = _make_key()
            mock_port_cls.return_value.find_active_by_key_id.return_value = _make_portfolio()
            mock_mkt_cls.return_value.read_all.return_value = []

            resp = client.get("/api/v1/experience/fno/portfolio-hedge?coverage=50")

        assert resp.status_code == 200
        body = resp.json()
        # Top-level fields
        assert "holdings" in body,   "PortfolioHedgeResponse missing 'holdings'"
        assert "aggregate" in body,  "PortfolioHedgeResponse missing 'aggregate'"
        assert "coverage" in body,   "PortfolioHedgeResponse missing 'coverage'"
        assert "duration" in body,   "PortfolioHedgeResponse missing 'duration'"
        # Aggregate sub-fields
        agg = body["aggregate"]
        assert "max_dd_protected_pct"  in agg
        assert "max_dd_unhedged_pct"   in agg
        assert "monthly_cost_pct"      in agg
        # Coverage echoed
        assert body["coverage"] == 50


# ---------------------------------------------------------------------------
# Test Class 2 — Edge cases: unknown duration query params are silently ignored
# ---------------------------------------------------------------------------

class TestPortfolioHedgeLegacyDurationParamIgnored:
    """FastAPI must silently ignore a legacy ?duration=... query param.

    After F29 Phase 0 the backend no longer declares a `duration` Query param.
    Any caller still passing ?duration=1m or ?duration=3m must receive HTTP 200
    (FastAPI ignores undeclared query params by default) and the response must
    still return duration='1y'.

    This validates Architect edge case #3: "Backend receives legacy duration query
    param from old cached frontend — FastAPI ignores unknown query params by
    default; safe."
    """

    @pytest.fixture(autouse=True)
    def _setup(self, client, db_session):
        from rita.auth import get_current_user
        from rita.main import app

        app.dependency_overrides[get_current_user] = lambda: _make_user()
        yield
        app.dependency_overrides.pop(get_current_user, None)

    def _call_with_duration(self, client, duration_value: str):
        """Helper: call endpoint with a legacy duration param and return response."""
        with (
            patch(_PATCH_KEY_REPO) as mock_key_cls,
            patch(_PATCH_PORT_REPO) as mock_port_cls,
            patch(_PATCH_MKT_REPO) as mock_mkt_cls,
        ):
            mock_key_cls.return_value.find_by_user_id.return_value = _make_key()
            mock_port_cls.return_value.find_active_by_key_id.return_value = _make_portfolio()
            mock_mkt_cls.return_value.read_all.return_value = []

            resp = client.get(
                "/api/v1/experience/fno/portfolio-hedge",
                params={"coverage": 50, "duration": duration_value},
            )
        return resp

    # ── Test 2a — ?duration=1m is ignored, response has duration='1y' ──────

    def test_legacy_duration_1m_ignored_returns_200(self, client):
        """?duration=1m must be ignored — 200 returned, duration still '1y'."""
        resp = self._call_with_duration(client, "1m")
        assert resp.status_code == 200, (
            f"Expected 200 with legacy ?duration=1m but got {resp.status_code}"
        )
        body = resp.json()
        assert body["duration"] == "1y", (
            f"duration must be '1y' even when ?duration=1m passed; got '{body['duration']}'"
        )

    # ── Test 2b — ?duration=3m is ignored, response has duration='1y' ──────

    def test_legacy_duration_3m_ignored_returns_200(self, client):
        """?duration=3m must be ignored — 200 returned, duration still '1y'."""
        resp = self._call_with_duration(client, "3m")
        assert resp.status_code == 200, (
            f"Expected 200 with legacy ?duration=3m but got {resp.status_code}"
        )
        body = resp.json()
        assert body["duration"] == "1y", (
            f"duration must be '1y' even when ?duration=3m passed; got '{body['duration']}'"
        )

    # ── Test 2c — ?duration=1y explicitly passed also works fine ────────────

    def test_legacy_duration_1y_ignored_still_returns_200(self, client):
        """?duration=1y passed explicitly must also be silently ignored — returns 200."""
        resp = self._call_with_duration(client, "1y")
        assert resp.status_code == 200
        body = resp.json()
        assert body["duration"] == "1y"


# ---------------------------------------------------------------------------
# Test Class 3 — Error paths: missing portfolio returns 404 (not 422/500)
# ---------------------------------------------------------------------------

class TestPortfolioHedge404Paths:
    """Endpoint must return 404 (not 422 or 500) when portfolio is missing.

    These guard the error handling that was not changed by F29 Phase 0
    but must remain functioning after the duration param removal.
    """

    @pytest.fixture(autouse=True)
    def _setup(self, client, db_session):
        from rita.auth import get_current_user
        from rita.main import app

        app.dependency_overrides[get_current_user] = lambda: _make_user()
        yield
        app.dependency_overrides.pop(get_current_user, None)

    def test_no_portfolio_key_returns_404(self, client):
        """When no portfolio key exists for the user → HTTP 404."""
        with (
            patch(_PATCH_KEY_REPO) as mock_key_cls,
            patch(_PATCH_PORT_REPO) as mock_port_cls,
            patch(_PATCH_MKT_REPO) as mock_mkt_cls,
        ):
            mock_key_cls.return_value.find_by_user_id.return_value = None
            mock_port_cls.return_value.find_active_by_key_id.return_value = _make_portfolio()
            mock_mkt_cls.return_value.read_all.return_value = []

            resp = client.get("/api/v1/experience/fno/portfolio-hedge?coverage=50")

        assert resp.status_code == 404, (
            f"Expected 404 when no portfolio key exists, got {resp.status_code}"
        )

    def test_no_active_portfolio_returns_404(self, client):
        """When portfolio key exists but no active portfolio → HTTP 404."""
        with (
            patch(_PATCH_KEY_REPO) as mock_key_cls,
            patch(_PATCH_PORT_REPO) as mock_port_cls,
            patch(_PATCH_MKT_REPO) as mock_mkt_cls,
        ):
            mock_key_cls.return_value.find_by_user_id.return_value = _make_key()
            mock_port_cls.return_value.find_active_by_key_id.return_value = None
            mock_mkt_cls.return_value.read_all.return_value = []

            resp = client.get("/api/v1/experience/fno/portfolio-hedge?coverage=50")

        assert resp.status_code == 404, (
            f"Expected 404 when no active portfolio exists, got {resp.status_code}"
        )
