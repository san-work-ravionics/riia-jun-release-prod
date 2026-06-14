"""Unit tests — F29 Phase 2: contract and edge-case QA for hedge-plan endpoints.

Endpoints under test
--------------------
GET  /api/v1/experience/fno/hedge-plan   — returns saved hedge plan or 404
PUT  /api/v1/experience/fno/hedge-plan   — upserts plan, returns persisted row

Phase 2 contract being verified
--------------------------------
The portfolio-hedge.js Phase 2 consumer reads the following fields from the
GET response and writes the following fields to the PUT request body:

  GET response fields consumed by JS (portfolio-hedge.js lines 437-439):
    plan.coverage      → _state.coverage    (int)
    plan.hedged_ids    → new Set(...)        (list[str])
    plan.scenario_tab  → _scenarioTab        (str)

  PUT request body fields written by JS (portfolio-hedge.js lines 447-451):
    hedged_ids    (list[str])
    coverage      (int)
    scenario_tab  (str)

These match HedgePlanCreate and HedgePlanOut exactly — contract verified.

Tests
-----
  test_get_hedge_plan_restores_coverage         — coverage is an int
  test_get_hedge_plan_restores_hedged_ids        — hedged_ids is a list[str]
  test_put_hedge_plan_accepts_empty_hedged_ids  — PUT with [] succeeds (coverage=0 edge case)
  test_get_hedge_plan_null_when_no_plan          — returns 200 null when no plan saved

Mock patch paths match the exact imports in fno_hedge_plan.py:
  rita.api.experience.fno_hedge_plan.UserPortfolioKeyRepo
  rita.api.experience.fno_hedge_plan.UserHedgePlanRepo
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

_NOW = datetime(2026, 6, 3, 14, 0, 0, tzinfo=timezone.utc)


def _make_user(user_id: str = "user-phase2"):
    user = MagicMock()
    user.id = user_id
    return user


def _make_key(key_id: str = "key-phase2"):
    key = MagicMock()
    key.key_id = key_id
    return key


def _make_plan(
    key_id: str = "key-phase2",
    hedged_ids: list | None = None,
    coverage: int = 60,
    scenario_tab: str = "pp",
    duration: str = "1y",
    updated_at: datetime | None = None,
) -> MagicMock:
    """Return a mock ORM row that satisfies HedgePlanOut.model_validate()."""
    plan = MagicMock()
    plan.key_id      = key_id
    plan.hedged_ids  = hedged_ids if hedged_ids is not None else ["RELIANCE", "TCS"]
    plan.coverage    = coverage
    plan.scenario_tab = scenario_tab
    plan.duration    = duration
    plan.updated_at  = updated_at or _NOW
    return plan


# ---------------------------------------------------------------------------
# Auth override helper
# ---------------------------------------------------------------------------

def _override_auth():
    from rita.auth import get_current_user
    from rita.main import app
    app.dependency_overrides[get_current_user] = lambda: _make_user()


def _clear_auth():
    from rita.auth import get_current_user
    from rita.main import app
    app.dependency_overrides.pop(get_current_user, None)


# ---------------------------------------------------------------------------
# Test 1 — GET restores coverage: field present and is an int
# ---------------------------------------------------------------------------

class TestGetHedgePlanRestoresCoverage:
    """Verify the 'coverage' field in the GET response is present and is an int.

    Phase 2 JS reads plan.coverage and assigns it to _state.coverage (int).
    """

    @pytest.fixture(autouse=True)
    def _auth(self, client):
        _override_auth()
        yield
        _clear_auth()

    def test_get_hedge_plan_restores_coverage(self, client):
        """GET returns plan with 'coverage' field that is an int."""
        with (
            patch(_PATCH_KEY_REPO) as mock_key_cls,
            patch(_PATCH_HEDGE_REPO) as mock_hedge_cls,
        ):
            mock_key_cls.return_value.find_by_user_id.return_value = _make_key()
            mock_hedge_cls.return_value.find_by_key_id.return_value = _make_plan(
                coverage=75
            )

            resp = client.get("/api/v1/experience/fno/hedge-plan")

        assert resp.status_code == 200, (
            f"Expected 200 but got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        assert "coverage" in body, "Response must include 'coverage' field"
        assert isinstance(body["coverage"], int), (
            f"'coverage' must be an int for JS _state.coverage restore; "
            f"got {type(body['coverage']).__name__!r}: {body['coverage']!r}"
        )
        assert body["coverage"] == 75, (
            f"Expected coverage=75, got {body['coverage']}"
        )


# ---------------------------------------------------------------------------
# Test 2 — GET restores hedged_ids: field present and is a list[str]
# ---------------------------------------------------------------------------

class TestGetHedgePlanRestoresHedgedIds:
    """Verify the 'hedged_ids' field in the GET response is a list of strings.

    Phase 2 JS reads plan.hedged_ids and rebuilds _state.hedgeChecked as a
    Set of strings.  If hedged_ids contains non-strings (e.g. ints), the
    round-trip is silently broken (no matching checkbox would be found).
    """

    @pytest.fixture(autouse=True)
    def _auth(self, client):
        _override_auth()
        yield
        _clear_auth()

    def test_get_hedge_plan_restores_hedged_ids(self, client):
        """GET returns plan with 'hedged_ids' that is a list[str]."""
        with (
            patch(_PATCH_KEY_REPO) as mock_key_cls,
            patch(_PATCH_HEDGE_REPO) as mock_hedge_cls,
        ):
            mock_key_cls.return_value.find_by_user_id.return_value = _make_key()
            mock_hedge_cls.return_value.find_by_key_id.return_value = _make_plan(
                hedged_ids=["RELIANCE", "TCS", "INFY"]
            )

            resp = client.get("/api/v1/experience/fno/hedge-plan")

        assert resp.status_code == 200, (
            f"Expected 200 but got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        assert "hedged_ids" in body, "Response must include 'hedged_ids' field"
        assert isinstance(body["hedged_ids"], list), (
            f"'hedged_ids' must be a list; got {type(body['hedged_ids']).__name__!r}"
        )
        for item in body["hedged_ids"]:
            assert isinstance(item, str), (
                f"Every element of 'hedged_ids' must be a str (no parseInt coercion "
                f"in JS); got element {item!r} of type {type(item).__name__!r}"
            )
        assert body["hedged_ids"] == ["RELIANCE", "TCS", "INFY"]


# ---------------------------------------------------------------------------
# Test 3 — PUT accepts empty hedged_ids list (coverage=0 edge case)
# ---------------------------------------------------------------------------

class TestPutHedgePlanAcceptsEmptyHedgedIds:
    """Verify PUT succeeds when hedged_ids=[] and coverage=0.

    Architect design doc edge case 6: 'hedged_ids empty list → valid, PUT
    accepts []'.  Edge case 7: 'coverage=0 → valid, HedgePlanCreate accepts 0'.
    """

    @pytest.fixture(autouse=True)
    def _auth(self, client):
        _override_auth()
        yield
        _clear_auth()

    def test_put_hedge_plan_accepts_empty_hedged_ids(self, client):
        """PUT /hedge-plan with hedged_ids=[] and coverage=0 returns 200."""
        persisted = _make_plan(
            hedged_ids=[],
            coverage=0,
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
                    "hedged_ids": [],
                    "coverage":   0,
                    "scenario_tab": "pp",
                },
            )

        assert resp.status_code == 200, (
            f"PUT with hedged_ids=[] and coverage=0 must succeed (200); "
            f"got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        assert body["hedged_ids"] == [], (
            f"Response hedged_ids must echo [] back; got {body['hedged_ids']!r}"
        )
        assert body["coverage"] == 0, (
            f"Response coverage must be 0; got {body['coverage']!r}"
        )


# ---------------------------------------------------------------------------
# Test 4 — GET 404 detail message: "No hedge plan found" in detail
# ---------------------------------------------------------------------------

class TestGetHedgePlan404DetailMessage:
    """Verify the 404 detail text when no plan exists.

    Phase 2 JS must silently use defaults on 404 — the detail message is
    checked here as a contract guard so the API does not accidentally return
    a different status code (e.g. 200 with null body) which would confuse
    the JS error handler.
    """

    @pytest.fixture(autouse=True)
    def _auth(self, client):
        _override_auth()
        yield
        _clear_auth()

    def test_get_hedge_plan_null_when_no_plan(self, client):
        """GET with existing portfolio key but no plan returns 200 null."""
        with (
            patch(_PATCH_KEY_REPO) as mock_key_cls,
            patch(_PATCH_HEDGE_REPO) as mock_hedge_cls,
        ):
            mock_key_cls.return_value.find_by_user_id.return_value = _make_key()
            mock_hedge_cls.return_value.find_by_key_id.return_value = None

            resp = client.get("/api/v1/experience/fno/hedge-plan")

        assert resp.status_code == 200, (
            f"Expected 200 null when no plan exists, got {resp.status_code}: {resp.text}"
        )
        assert resp.json() is None
