"""Unit tests — F29 Phase 1: user_hedge_plans GET and PUT endpoints.

Endpoints under test
--------------------
GET  /api/v1/experience/fno/hedge-plan   — returns saved hedge plan or 404
PUT  /api/v1/experience/fno/hedge-plan   — upserts plan, always stores duration="1y"

Test strategy
-------------
- HTTP tests use the ``client`` fixture from conftest.py (in-memory SQLite,
  TestClient with get_db override).
- Authentication is bypassed via dependency_overrides[get_current_user].
- UserPortfolioKeyRepo and UserHedgePlanRepo are patched at the exact import
  paths used in fno_hedge_plan.py to ensure mocks intercept correctly.
- Pydantic validation (coverage 0–100) is exercised via live FastAPI 422 paths
  — no patching needed for those tests.

Contract being verified (Phase 2 consumer: portfolio-hedge.js)
--------------
  HedgePlanOut field  | Phase 2 JS usage
  --------------------|-------------------------------------------
  hedged_ids          | hedgeChecked Set reconstruction on load
  coverage            | _state.coverage restore on load
  scenario_tab        | _scenarioTab restore on load
  duration            | always "1y" — business rule
  key_id              | identity; not directly read by JS
  updated_at          | not directly read by JS (server timestamp)
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Exact patch paths — derived from imports in fno_hedge_plan.py
# ---------------------------------------------------------------------------

_PATCH_KEY_REPO   = "rita.api.experience.fno_hedge_plan.UserPortfolioKeyRepo"
_PATCH_HEDGE_REPO = "rita.api.experience.fno_hedge_plan.UserHedgePlanRepo"


# ---------------------------------------------------------------------------
# Mock-data helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 6, 3, 12, 0, 0, tzinfo=timezone.utc)


def _make_user(user_id: str = "user-001"):
    user = MagicMock()
    user.id = user_id
    return user


def _make_key(key_id: str = "key-abc123"):
    key = MagicMock()
    key.key_id = key_id
    return key


def _make_plan(
    key_id: str = "key-abc123",
    hedged_ids: list | None = None,
    coverage: int = 70,
    scenario_tab: str = "pp",
    duration: str = "1y",
    updated_at: datetime | None = None,
) -> MagicMock:
    """Return a mock ORM row that satisfies HedgePlanOut.model_validate()."""
    plan = MagicMock()
    plan.key_id = key_id
    plan.hedged_ids = hedged_ids if hedged_ids is not None else ["RELIANCE", "TCS"]
    plan.coverage = coverage
    plan.scenario_tab = scenario_tab
    plan.duration = duration
    plan.updated_at = updated_at or _NOW
    return plan


# ---------------------------------------------------------------------------
# Test Class 1 — GET /api/v1/experience/fno/hedge-plan
# ---------------------------------------------------------------------------

class TestGetHedgePlan:
    """Happy path and 404 paths for GET /hedge-plan."""

    @pytest.fixture(autouse=True)
    def _setup(self, client):
        """Override auth for every test in this class."""
        from rita.auth import get_current_user
        from rita.main import app

        app.dependency_overrides[get_current_user] = lambda: _make_user()
        yield
        app.dependency_overrides.pop(get_current_user, None)

    # ── Test 1a — Happy path: plan exists → 200 + all HedgePlanOut fields ──

    def test_get_hedge_plan_happy_path_returns_200(self, client):
        """GET /hedge-plan returns 200 when portfolio key and plan both exist."""
        with (
            patch(_PATCH_KEY_REPO) as mock_key_cls,
            patch(_PATCH_HEDGE_REPO) as mock_hedge_cls,
        ):
            mock_key_cls.return_value.find_by_user_id.return_value = _make_key()
            mock_hedge_cls.return_value.find_by_key_id.return_value = _make_plan()

            resp = client.get("/api/v1/experience/fno/hedge-plan")

        assert resp.status_code == 200, (
            f"Expected 200 but got {resp.status_code}: {resp.text}"
        )

    def test_get_hedge_plan_happy_path_response_fields(self, client):
        """GET /hedge-plan response contains all 6 HedgePlanOut fields."""
        with (
            patch(_PATCH_KEY_REPO) as mock_key_cls,
            patch(_PATCH_HEDGE_REPO) as mock_hedge_cls,
        ):
            mock_key_cls.return_value.find_by_user_id.return_value = _make_key(
                key_id="key-abc123"
            )
            mock_hedge_cls.return_value.find_by_key_id.return_value = _make_plan(
                key_id="key-abc123",
                hedged_ids=["RELIANCE", "TCS"],
                coverage=70,
                scenario_tab="ps",
                duration="1y",
                updated_at=_NOW,
            )

            resp = client.get("/api/v1/experience/fno/hedge-plan")

        assert resp.status_code == 200
        body = resp.json()

        # All 6 HedgePlanOut fields must be present
        assert body["key_id"] == "key-abc123"
        assert body["hedged_ids"] == ["RELIANCE", "TCS"]
        assert body["coverage"] == 70
        assert body["scenario_tab"] == "ps"
        assert body["duration"] == "1y"
        assert "updated_at" in body

    # ── Test 1b — 404 when no plan found ───────────────────────────────────

    def test_get_hedge_plan_returns_null_when_no_plan(self, client):
        """GET /hedge-plan returns 200 null when portfolio key exists but no plan row."""
        with (
            patch(_PATCH_KEY_REPO) as mock_key_cls,
            patch(_PATCH_HEDGE_REPO) as mock_hedge_cls,
        ):
            mock_key_cls.return_value.find_by_user_id.return_value = _make_key()
            mock_hedge_cls.return_value.find_by_key_id.return_value = None

            resp = client.get("/api/v1/experience/fno/hedge-plan")

        assert resp.status_code == 200, (
            f"Expected 200 null when no plan exists, got {resp.status_code}"
        )
        assert resp.json() is None

    # ── Test 1c — null when user has no portfolio key ───────────────────────

    def test_get_hedge_plan_returns_null_when_no_portfolio_key(self, client):
        """GET /hedge-plan returns 200 null when the user has no portfolio key row."""
        with (
            patch(_PATCH_KEY_REPO) as mock_key_cls,
            patch(_PATCH_HEDGE_REPO) as mock_hedge_cls,
        ):
            mock_key_cls.return_value.find_by_user_id.return_value = None
            mock_hedge_cls.return_value.find_by_key_id.return_value = _make_plan()

            resp = client.get("/api/v1/experience/fno/hedge-plan")

        assert resp.status_code == 200, (
            f"Expected 200 null when no portfolio key, got {resp.status_code}"
        )
        assert resp.json() is None


# ---------------------------------------------------------------------------
# Test Class 2 — PUT /api/v1/experience/fno/hedge-plan
# ---------------------------------------------------------------------------

class TestPutHedgePlan:
    """Happy path, duration override, and Pydantic validation for PUT /hedge-plan."""

    @pytest.fixture(autouse=True)
    def _setup(self, client):
        """Override auth for every test in this class."""
        from rita.auth import get_current_user
        from rita.main import app

        app.dependency_overrides[get_current_user] = lambda: _make_user()
        yield
        app.dependency_overrides.pop(get_current_user, None)

    # ── Test 2a — Happy path: creates plan, returns 200 with duration="1y" ──

    def test_put_hedge_plan_happy_path_returns_200(self, client):
        """PUT /hedge-plan returns 200 and duration is always '1y'."""
        persisted = _make_plan(
            hedged_ids=["RELIANCE", "TCS"],
            coverage=80,
            scenario_tab="pp",
            duration="1y",
        )
        with (
            patch(_PATCH_KEY_REPO) as mock_key_cls,
            patch(_PATCH_HEDGE_REPO) as mock_hedge_cls,
        ):
            mock_key_cls.return_value.find_by_user_id.return_value = _make_key()
            mock_hedge_cls.return_value.upsert.return_value = None
            mock_hedge_cls.return_value.find_by_key_id.return_value = persisted

            resp = client.put(
                "/api/v1/experience/fno/hedge-plan",
                json={
                    "hedged_ids": ["RELIANCE", "TCS"],
                    "coverage": 80,
                    "scenario_tab": "pp",
                },
            )

        assert resp.status_code == 200, (
            f"Expected 200 but got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        assert body["duration"] == "1y", (
            f"duration must always be '1y', got '{body['duration']}'"
        )

    def test_put_hedge_plan_happy_path_response_shape(self, client):
        """PUT /hedge-plan response confirms all HedgePlanOut fields."""
        persisted = _make_plan(
            key_id="key-abc123",
            hedged_ids=["RELIANCE", "TCS"],
            coverage=80,
            scenario_tab="pp",
            duration="1y",
        )
        with (
            patch(_PATCH_KEY_REPO) as mock_key_cls,
            patch(_PATCH_HEDGE_REPO) as mock_hedge_cls,
        ):
            mock_key_cls.return_value.find_by_user_id.return_value = _make_key(
                key_id="key-abc123"
            )
            mock_hedge_cls.return_value.upsert.return_value = None
            mock_hedge_cls.return_value.find_by_key_id.return_value = persisted

            resp = client.put(
                "/api/v1/experience/fno/hedge-plan",
                json={
                    "hedged_ids": ["RELIANCE", "TCS"],
                    "coverage": 80,
                    "scenario_tab": "pp",
                },
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["key_id"] == "key-abc123"
        assert body["hedged_ids"] == ["RELIANCE", "TCS"]
        assert body["coverage"] == 80
        assert body["scenario_tab"] == "pp"
        assert body["duration"] == "1y"
        assert "updated_at" in body

    # ── Test 2b — Duration override: client sends duration="3m", response always "1y" ──

    def test_put_hedge_plan_duration_override_3m(self, client):
        """PUT /hedge-plan: client sends duration='3m' — response always returns duration='1y'."""
        persisted = _make_plan(duration="1y")
        with (
            patch(_PATCH_KEY_REPO) as mock_key_cls,
            patch(_PATCH_HEDGE_REPO) as mock_hedge_cls,
        ):
            mock_key_cls.return_value.find_by_user_id.return_value = _make_key()
            mock_hedge_cls.return_value.upsert.return_value = None
            mock_hedge_cls.return_value.find_by_key_id.return_value = persisted

            resp = client.put(
                "/api/v1/experience/fno/hedge-plan",
                json={
                    "hedged_ids": ["RELIANCE"],
                    "coverage": 50,
                    "scenario_tab": "pp",
                    "duration": "3m",   # client sends a non-"1y" duration
                },
            )

        assert resp.status_code == 200, (
            f"Expected 200 but got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        assert body["duration"] == "1y", (
            f"duration must be overwritten to '1y' regardless of client input; "
            f"got '{body['duration']}'"
        )

    # ── Test 2c — coverage=101 raises 422 (Pydantic validation) ─────────────

    def test_put_hedge_plan_coverage_101_raises_422(self, client):
        """PUT /hedge-plan with coverage=101 must return 422 (value out of range)."""
        with (
            patch(_PATCH_KEY_REPO) as mock_key_cls,
            patch(_PATCH_HEDGE_REPO) as mock_hedge_cls,
        ):
            mock_key_cls.return_value.find_by_user_id.return_value = _make_key()
            mock_hedge_cls.return_value.upsert.return_value = None
            mock_hedge_cls.return_value.find_by_key_id.return_value = _make_plan(
                coverage=101
            )

            resp = client.put(
                "/api/v1/experience/fno/hedge-plan",
                json={
                    "hedged_ids": ["RELIANCE"],
                    "coverage": 101,    # invalid: > 100
                    "scenario_tab": "pp",
                },
            )

        assert resp.status_code == 422, (
            f"Expected 422 for coverage=101 but got {resp.status_code}"
        )

    # ── Test 2d — coverage=-1 raises 422 (Pydantic validation) ──────────────

    def test_put_hedge_plan_coverage_negative_raises_422(self, client):
        """PUT /hedge-plan with coverage=-1 must return 422 (value out of range)."""
        with (
            patch(_PATCH_KEY_REPO) as mock_key_cls,
            patch(_PATCH_HEDGE_REPO) as mock_hedge_cls,
        ):
            mock_key_cls.return_value.find_by_user_id.return_value = _make_key()
            mock_hedge_cls.return_value.upsert.return_value = None
            mock_hedge_cls.return_value.find_by_key_id.return_value = _make_plan()

            resp = client.put(
                "/api/v1/experience/fno/hedge-plan",
                json={
                    "hedged_ids": ["RELIANCE"],
                    "coverage": -1,     # invalid: < 0
                    "scenario_tab": "pp",
                },
            )

        assert resp.status_code == 422, (
            f"Expected 422 for coverage=-1 but got {resp.status_code}"
        )
