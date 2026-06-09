"""Unit tests for Feature 17 Phase 0 — GET /mobile gateway route.

Changes under test
------------------
- main.py: ``@app.get("/mobile")`` route added before ``/mobileapp`` static mount
- mobileapp/gateway.html: new gateway hub page with 5 app cards

Test strategy
-------------
- HTTP tests use the ``client`` fixture from conftest.py (in-memory SQLite,
  TestClient with get_db override).
- File-content tests read ``gateway.html`` directly from disk — FileResponse
  streams the file and the raw bytes are not reliably decoded in TestClient
  without follow_redirects gymnastics, so direct file reads are the correct
  approach here.
- No mocking is required: the /mobile route is a pure FileResponse with no
  DB or service dependencies.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Path to gateway.html — resolved relative to main.py location so the path
# matches exactly what the route handler computes.
# ---------------------------------------------------------------------------

_GATEWAY_HTML = (
    Path(__file__).parent.parent.parent
    / "mobileapp"
    / "gateway.html"
)


# ---------------------------------------------------------------------------
# Test 1 — Happy path: GET /mobile returns 200 with Content-Type text/html
# ---------------------------------------------------------------------------

class TestMobileRouteHappyPath:
    """GET /mobile must return HTTP 200 and serve an HTML file."""

    def test_returns_200(self, client):
        """Happy path: GET /mobile → 200 OK."""
        response = client.get("/mobile")
        assert response.status_code == 200

    def test_content_type_is_html(self, client):
        """Response Content-Type must be text/html (FileResponse default for .html)."""
        response = client.get("/mobile")
        assert "text/html" in response.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# Test 2 — Edge case: query param ?from=rita is ignored (no JS to handle it)
# ---------------------------------------------------------------------------

class TestMobileRouteQueryParamIgnored:
    """GET /mobile with unknown query params must still return 200.

    Phase 0 specification: query params are ignored by the static gateway page.
    """

    def test_from_param_ignored_returns_200(self, client):
        """?from=rita query param must not cause a 422 or 500 — returns 200."""
        response = client.get("/mobile", params={"from": "rita"})
        assert response.status_code == 200

    def test_arbitrary_params_ignored(self, client):
        """Arbitrary query params must be silently ignored — page still loads."""
        response = client.get("/mobile", params={"source": "fno", "ref": "test"})
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Test 3 — Structure check: gateway.html contains all 6 required element IDs
# ---------------------------------------------------------------------------

class TestGatewayHtmlRequiredIds:
    """gateway.html must contain all 6 element IDs specified in the design."""

    @pytest.fixture(scope="class")
    def html_text(self):
        """Read gateway.html once for the whole class."""
        assert _GATEWAY_HTML.exists(), (
            f"gateway.html not found at expected path: {_GATEWAY_HTML}"
        )
        return _GATEWAY_HTML.read_text(encoding="utf-8")

    @pytest.mark.parametrize("element_id", [
        "card-rita",
        "card-onboarding",
        "card-fno",
        "card-ops",
        "card-ds",
        "footer-desktop-link",
    ])
    def test_required_id_present(self, html_text, element_id):
        """All 6 required element IDs must be present in gateway.html."""
        assert f'id="{element_id}"' in html_text, (
            f"gateway.html is missing required element id=\"{element_id}\""
        )


# ---------------------------------------------------------------------------
# Test 4 — Link check: Desktop Only cards link with ?desktop=1
# ---------------------------------------------------------------------------

class TestGatewayHtmlDesktopLinks:
    """Desktop Only card links (FnO, Ops, Data Science) must include ?desktop=1."""

    @pytest.fixture(scope="class")
    def html_text(self):
        assert _GATEWAY_HTML.exists(), (
            f"gateway.html not found at expected path: {_GATEWAY_HTML}"
        )
        return _GATEWAY_HTML.read_text(encoding="utf-8")

    def test_card_fno_href_contains_desktop_param(self, html_text):
        """card-fno anchor href must contain ?desktop=1 (Desktop Only card)."""
        # Find the card-fno section and check that desktop=1 appears nearby
        assert "?desktop=1" in html_text, (
            "gateway.html does not contain any ?desktop=1 link — "
            "FnO/Ops/DS cards must use ?desktop=1 query param"
        )
        # Verify the specific card-fno block contains a desktop link
        card_fno_idx = html_text.find('id="card-fno"')
        assert card_fno_idx != -1, "card-fno id not found"
        # Grab 500 chars after the card-fno id to check the link is in that card
        card_fno_block = html_text[card_fno_idx: card_fno_idx + 500]
        assert "?desktop=1" in card_fno_block, (
            "card-fno block does not contain ?desktop=1 — "
            "FnO Desktop Only card must link with ?desktop=1"
        )

    def test_card_ops_href_links_to_mobile_app(self, html_text):
        """card-ops anchor href must link to /mobileapp/ops.html (Mobile Ready card)."""
        card_ops_idx = html_text.find('id="card-ops"')
        assert card_ops_idx != -1, "card-ops id not found"
        card_ops_block = html_text[card_ops_idx: card_ops_idx + 600]
        assert "/mobileapp/ops.html" in card_ops_block, (
            "card-ops block does not contain /mobileapp/ops.html — "
            "Ops card is now Mobile Ready and must link to /mobileapp/ops.html"
        )
        assert "tile build" in card_ops_block or "tile research" in card_ops_block, (
            "card-ops must use a mobile-ready tile class (tile build or tile research) — "
            "not the amber tile ops class"
        )

    def test_card_ds_href_contains_desktop_param(self, html_text):
        """card-ds anchor href must contain ?desktop=1 (Desktop Only card)."""
        card_ds_idx = html_text.find('id="card-ds"')
        assert card_ds_idx != -1, "card-ds id not found"
        card_ds_block = html_text[card_ds_idx: card_ds_idx + 500]
        assert "?desktop=1" in card_ds_block, (
            "card-ds block does not contain ?desktop=1 — "
            "Data Science Desktop Only card must link with ?desktop=1"
        )


# ---------------------------------------------------------------------------
# Test 5 — No-script check: gateway.html must NOT contain a <script> tag
# ---------------------------------------------------------------------------

class TestGatewayHtmlNoScript:
    """gateway.html is a static no-JS page — it must not contain any <script> tags.

    Phase 0 design requirement: no script tags anywhere in gateway.html.
    All CSS must be inline; no JavaScript.
    """

    @pytest.fixture(scope="class")
    def html_text(self):
        assert _GATEWAY_HTML.exists(), (
            f"gateway.html not found at expected path: {_GATEWAY_HTML}"
        )
        return _GATEWAY_HTML.read_text(encoding="utf-8")

    def test_no_script_tag(self, html_text):
        """gateway.html must not contain any <script> tag (case-insensitive)."""
        assert "<script" not in html_text.lower(), (
            "gateway.html contains a <script> tag — "
            "Phase 0 design requires zero JavaScript; all CSS must be inline"
        )


# ---------------------------------------------------------------------------
# Test 6 — Root route unchanged: GET / still redirects to /dashboard
# ---------------------------------------------------------------------------

class TestRootRouteUnchanged:
    """GET / must still redirect to /dashboard — not to /mobile.

    Phase 0 explicitly excludes UA detection. The root redirect must remain
    unchanged at /dashboard.
    """

    def test_root_redirects_to_dashboard(self, client):
        """GET / must return 302 with Location: /dashboard."""
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 302, (
            f"GET / returned {response.status_code}, expected 302 redirect"
        )
        location = response.headers.get("location", "")
        assert "/dashboard" in location, (
            f"GET / redirects to '{location}', expected /dashboard — "
            "UA detection is Phase 1, not Phase 0; root must redirect to /dashboard"
        )

    def test_root_does_not_redirect_to_mobile(self, client):
        """GET / must NOT redirect to /mobile — no UA detection in Phase 0."""
        response = client.get("/", follow_redirects=False)
        location = response.headers.get("location", "")
        assert "/mobile" not in location, (
            f"GET / redirects to '{location}' which contains /mobile — "
            "UA detection is Phase 1; Phase 0 must not touch the root redirect"
        )
