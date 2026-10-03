"""Unit tests — F39 Phase 2 addendum: kite_middleware_client.fetch_kite_quote.

Verifies the two distinct failure modes both resolve through the same silent-
fallback path (return None), plus the success path, per Design Review's
highest-priority behavioral requirement (addendum §6 edge case #6):

  (a) connection failure / timeout  — fno-margin-fetch not running at all
  (b) non-2xx / error response      — fno-margin-fetch running but e.g. the
                                       Kite access token has expired
  (c) a successful 200 response     — proves the branching logic parses a
                                       real payload correctly

These are mocked-HTTP tests, NOT live integration tests against a real running
fno-margin-fetch with valid/expired Kite tokens — that is a manual follow-up
outside this session's reach (no real fno-margin-fetch instance is available
in this sandbox).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx

from rita.services.kite_middleware_client import fetch_kite_quote

_PATCH_TARGET = "rita.services.kite_middleware_client.httpx.get"


def test_fetch_kite_quote_connection_refused_returns_none() -> None:
    """(a) fno-margin-fetch not running — connection refused → None, never raises."""
    with patch(_PATCH_TARGET, side_effect=httpx.ConnectError("refused")):
        result = fetch_kite_quote("NIFTY")
    assert result is None


def test_fetch_kite_quote_timeout_returns_none() -> None:
    """(a) fno-margin-fetch not responding within the short timeout → None."""
    with patch(_PATCH_TARGET, side_effect=httpx.TimeoutException("timed out")):
        result = fetch_kite_quote("NIFTY")
    assert result is None


def test_fetch_kite_quote_non_2xx_returns_none() -> None:
    """(b) fno-margin-fetch running but Kite token expired (401) → None, not an exception."""
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    with patch(_PATCH_TARGET, return_value=mock_resp):
        result = fetch_kite_quote("NIFTY")
    assert result is None


def test_fetch_kite_quote_server_error_returns_none() -> None:
    """(b) non-2xx also covers 5xx — distinct status, same fallback path."""
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    with patch(_PATCH_TARGET, return_value=mock_resp):
        result = fetch_kite_quote("NIFTY")
    assert result is None


def test_fetch_kite_quote_success_returns_parsed_json() -> None:
    """(c) a successful 200 response is parsed and returned as-is."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"lot_size": 75, "ltp": 24100.5, "bid": 24100.0, "ask": 24101.0}
    with patch(_PATCH_TARGET, return_value=mock_resp) as mock_get:
        result = fetch_kite_quote("NIFTY", strike=24000, option_type="CE")

    assert result == {"lot_size": 75, "ltp": 24100.5, "bid": 24100.0, "ask": 24101.0}
    # Confirm optional params were forwarded, None-valued ones dropped.
    _, kwargs = mock_get.call_args
    assert kwargs["params"]["instrument_id"] == "NIFTY"
    assert kwargs["params"]["strike"] == 24000
    assert kwargs["params"]["option_type"] == "CE"
    assert "quantity" not in kwargs["params"]


def test_fetch_kite_quote_bad_json_returns_none() -> None:
    """A 200 with an unparseable body is still treated as unavailable, not a crash."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.side_effect = ValueError("not json")
    with patch(_PATCH_TARGET, return_value=mock_resp):
        result = fetch_kite_quote("NIFTY")
    assert result is None
