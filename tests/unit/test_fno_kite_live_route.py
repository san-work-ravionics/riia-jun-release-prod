"""Unit tests — F39 Phase 2 addendum: GET /api/v1/experience/fno/kite-live ROUTE.

QA gap-fill (task-brief-20261003-1114, [QA] Test Results, Task 1): the
Engineer's `test_kite_middleware_client.py` tests only the HTTP client
function (`fetch_kite_quote`) — none of its 6 tests exercise the FastAPI
route function in `api/experience/fno_kite_live.py`, which has its own
mapping logic:

  raw is None                       -> available=False, source="fallback",
                                        lot_size/quote/margin/fetched_at all None
  raw has lot_size/ltp/bid/ask/etc  -> available=True, source="kite", and
                                        quote/margin are each independently
                                        built only when at least one of their
                                        constituent keys is present in `raw`
                                        (Architect edge case #8 — partial data)

These tests patch `fetch_kite_quote` directly (not httpx) so they isolate
the ROUTE's own mapping logic from the client's HTTP/retry logic, which is
already covered by test_kite_middleware_client.py.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

_PATCH_TARGET = "rita.api.experience.fno_kite_live.fetch_kite_quote"


def _make_user(user_id: str = "user-kite-live"):
    from unittest.mock import MagicMock
    user = MagicMock()
    user.id = user_id
    return user


@pytest.fixture(autouse=True)
def _auth(client):
    from rita.auth import get_current_user
    from rita.main import app

    app.dependency_overrides[get_current_user] = lambda: _make_user()
    yield
    app.dependency_overrides.pop(get_current_user, None)


# ---------------------------------------------------------------------------
# Edge cases #5/#6 at the ROUTE level — client returned None (either failure
# mode funnels into this single None return; the route's own fallback-mapping
# is what's under test here, not the client's dual-failure-mode catching,
# which is already covered in test_kite_middleware_client.py).
# ---------------------------------------------------------------------------

def test_route_maps_none_to_available_false_fallback(client):
    """raw=None (fno-margin-fetch down OR non-2xx) -> full fallback payload."""
    with patch(_PATCH_TARGET, return_value=None):
        resp = client.get(
            "/api/v1/experience/fno/kite-live", params={"instrument_id": "NIFTY"}
        )

    assert resp.status_code == 200, f"Must always be 200, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body == {
        "instrument_id": "NIFTY",
        "available": False,
        "source": "fallback",
        "lot_size": None,
        "quote": None,
        "margin": None,
        "fetched_at": None,
    }


# ---------------------------------------------------------------------------
# Success path — full data present
# ---------------------------------------------------------------------------

def test_route_maps_full_raw_dict_to_available_true_kite(client):
    """raw with lot_size + full quote -> available=True, source='kite', quote populated."""
    with patch(
        _PATCH_TARGET,
        return_value={"lot_size": 75, "ltp": 24100.5, "bid": 24100.0, "ask": 24101.0},
    ):
        resp = client.get(
            "/api/v1/experience/fno/kite-live", params={"instrument_id": "NIFTY"}
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["instrument_id"] == "NIFTY"
    assert body["available"] is True
    assert body["source"] == "kite"
    assert body["lot_size"] == 75
    assert body["quote"] == {"ltp": 24100.5, "bid": 24100.0, "ask": 24101.0}
    assert body["margin"] is None, "no margin keys in raw -> margin must stay None"
    assert body["fetched_at"] is not None


# ---------------------------------------------------------------------------
# Architect edge case #8 — partial data, independently nullable fields.
# Two distinct directions, not assumed covered by one test.
# ---------------------------------------------------------------------------

def test_route_partial_data_lot_size_only_quote_stays_none(client):
    """raw has lot_size but none of ltp/bid/ask -> quote must be None, not an empty object."""
    with patch(_PATCH_TARGET, return_value={"lot_size": 75}):
        resp = client.get(
            "/api/v1/experience/fno/kite-live", params={"instrument_id": "NIFTY"}
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert body["source"] == "kite"
    assert body["lot_size"] == 75
    assert body["quote"] is None, (
        "quote must be None when none of ltp/bid/ask are present in raw, "
        f"got {body['quote']!r}"
    )
    assert body["margin"] is None


def test_route_partial_data_quote_only_lot_size_stays_none(client):
    """raw has ltp but no lot_size key -> lot_size None, quote populated (ask/bid default None)."""
    with patch(_PATCH_TARGET, return_value={"ltp": 24100.5}):
        resp = client.get(
            "/api/v1/experience/fno/kite-live", params={"instrument_id": "NIFTY"}
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert body["source"] == "kite"
    assert body["lot_size"] is None, (
        f"lot_size must be None when absent from raw, got {body['lot_size']!r}"
    )
    assert body["quote"] == {"ltp": 24100.5, "bid": None, "ask": None}
    assert body["margin"] is None


def test_route_margin_populated_when_margin_keys_present(client):
    """raw with required/span/exposure keys -> margin independently populated (Phase 3 leg,
    but the route's branching logic already exists in Phase 2 code and must be correct)."""
    with patch(
        _PATCH_TARGET,
        return_value={"required": 120000.0, "span": 90000.0, "exposure": 30000.0},
    ):
        resp = client.get(
            "/api/v1/experience/fno/kite-live", params={"instrument_id": "NIFTY"}
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert body["quote"] is None, "no quote keys in raw -> quote must stay None"
    assert body["margin"] == {"required": 120000.0, "span": 90000.0, "exposure": 30000.0}


def test_route_requires_instrument_id_query_param(client):
    """Missing required instrument_id -> 422, not a silent fallback (contract guard)."""
    resp = client.get("/api/v1/experience/fno/kite-live")
    assert resp.status_code == 422
