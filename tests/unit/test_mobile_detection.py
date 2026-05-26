"""Unit tests for Feature 17 Phase 1 — UA-based mobile detection in root().

Tests
-----
- Happy path: Android UA → 302 /mobile
- Happy path: iPhone UA → 302 /mobile
- Happy path: desktop Chrome/Mac UA → 302 /dashboard
- Edge case: empty User-Agent header → 302 /dashboard (defaults to desktop)
- Edge case: plain Opera UA (not Opera Mini) → 302 /dashboard (no false positive)
- Edge case: lowercase "android" UA → 302 /mobile (re.IGNORECASE)

Strategy
--------
- TestClient is instantiated without a context manager so the FastAPI lifespan
  (which requires rita_output/rita.db to exist) is not triggered.  This is
  the same pattern used by test_api_experience.py in this suite.
- follow_redirects=False captures the 302 before it is followed so the
  Location header can be asserted directly.
- No DB dependency for GET /; no dependency_overrides required.

Contract verification
---------------------
Server root() redirects mobile UA → /mobile.
JS snippet on each HTML file redirects mobile UA → /mobile?from=APPNAME.
Both targets are /mobile — consistent.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from rita.main import app

# ---------------------------------------------------------------------------
# User-Agent constants
# ---------------------------------------------------------------------------

_ANDROID_UA = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/114.0.0.0 Mobile Safari/537.36"
)

_IPHONE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/16.5 Mobile/15E148 Safari/604.1"
)

_DESKTOP_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/114.0.5735.198 Safari/537.36"
)

# Plain Opera desktop — contains "OPR/" but NOT "Opera Mini"
_OPERA_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/114.0.0.0 Safari/537.36 OPR/100.0.0.0"
)

_ANDROID_LOWERCASE_UA = (
    "mozilla/5.0 (linux; android 12; sm-g998b) "
    "applewebkit/537.36 (khtml, like gecko) "
    "chrome/112.0.0.0 mobile safari/537.36"
)


# ---------------------------------------------------------------------------
# Helper — create a fresh TestClient without triggering the lifespan.
# (Same pattern as test_api_experience.py: no `with` block.)
# ---------------------------------------------------------------------------

def _client() -> TestClient:
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------

def test_root_android_ua_redirects_to_mobile():
    """Android User-Agent → 302 /mobile."""
    response = _client().get("/", headers={"user-agent": _ANDROID_UA}, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/mobile"


def test_root_iphone_ua_redirects_to_mobile():
    """iPhone User-Agent → 302 /mobile."""
    response = _client().get("/", headers={"user-agent": _IPHONE_UA}, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/mobile"


def test_root_desktop_ua_redirects_to_dashboard():
    """Desktop Chrome/Mac User-Agent → 302 /dashboard (no regression)."""
    response = _client().get("/", headers={"user-agent": _DESKTOP_UA}, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/dashboard"


# ---------------------------------------------------------------------------
# Edge-case tests
# ---------------------------------------------------------------------------

def test_root_empty_ua_defaults_to_dashboard():
    """Empty User-Agent header → 302 /dashboard (safe default: treat as desktop)."""
    response = _client().get("/", headers={"user-agent": ""}, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/dashboard"


def test_root_plain_opera_ua_does_not_redirect_to_mobile():
    """Plain Opera desktop UA (no 'Opera Mini') → 302 /dashboard.

    The regex includes 'Opera Mini' but must not match plain 'Opera' or
    'OPR/' strings — desktop Opera users must reach /dashboard.
    """
    response = _client().get("/", headers={"user-agent": _OPERA_UA}, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/dashboard"


def test_root_lowercase_android_ua_redirects_to_mobile():
    """All-lowercase 'android' in UA → 302 /mobile (re.IGNORECASE enforced)."""
    response = _client().get("/", headers={"user-agent": _ANDROID_LOWERCASE_UA}, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/mobile"
