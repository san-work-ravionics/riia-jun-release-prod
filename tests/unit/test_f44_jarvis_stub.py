"""F44 — Jarvis home-page tile + stub page (user 2026-10-26: tile in the protected zone now; module in P4)."""
from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_DASH = _ROOT / "dashboard"


class _Tiles(HTMLParser):
    """Collects the direct <a> children of each div.tiles grid, per zone."""

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[tuple[str, dict]] = []
        self.grids: list[dict] = []  # {"zone": str, "tiles": [attrs, ...]}
        self._zone = ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class") or ""
        if tag == "div" and "zone" in cls.split():
            self._zone = cls
        if self.stack and self.stack[-1][0] == "div" and "tiles" in (self.stack[-1][1].get("class") or "").split() and tag == "a":
            self.grids[-1]["tiles"].append(a)
        if tag == "div" and "tiles" in cls.split():
            self.grids.append({"zone": self._zone, "tiles": [], "style": a.get("style") or ""})
        if tag not in ("img", "br", "input", "meta", "link", "path", "circle", "line", "polyline"):
            self.stack.append((tag, a))

    def handle_endtag(self, tag):
        if tag not in [t for t, _ in self.stack]:  # void / self-closing (<path/>) was never pushed
            return
        while self.stack:
            t, _ = self.stack.pop()
            if t == tag:
                break


def test_jarvis_tile_follows_review_portfolio_in_the_protected_zone():
    p = _Tiles()
    p.feed((_DASH / "index.html").read_text(encoding="utf-8"))
    protected = [g for g in p.grids if "sso-protected" in g["zone"]]
    assert len(protected) == 1
    tiles = protected[0]["tiles"]
    assert [t["href"] for t in tiles] == ["fno.html#positions", "jarvis.html", "ds.html", "ops.html"]
    assert all("protected-route" in t["class"] for t in tiles)
    assert "repeat(4, 1fr)" in protected[0]["style"]
    # Open-access zone: same two tiles
    open_zone = [g for g in p.grids if "open-access" in g["zone"]]
    assert [t["href"] for t in open_zone[0]["tiles"]] == ["investgame-app.html", "rita.html"]
    html = (_DASH / "index.html").read_text(encoding="utf-8")
    # user 2026-10-26: open-access tiles 25% smaller in total (15% then 10% more: zone flex 2 -> 1.5, min-width 440 -> 330)
    assert 'class="zone open-access" style="flex:1.5; min-width:330px;' in html


def test_jarvis_page_has_the_login_gate_before_render():
    html = (_DASH / "jarvis.html").read_text(encoding="utf-8")
    gate = "window.location.href = '/auth/google/login';"
    assert gate in html and "sessionStorage.setItem('post_login_redirect', window.location.href);" in html
    assert html.index(gate) < html.index("<title>")
    assert html.index(gate) < html.index('src="./js/jarvis/main.js')


def test_jarvis_js_uses_the_shared_auth_pattern():
    js = (_DASH / "js" / "jarvis" / "main.js").read_text(encoding="utf-8")
    assert "from '../shared/api.js'" in js and "from '../shared/dev-auth.js'" in js
    assert "await ensureDevToken();" in js
    assert "fetch(" not in js  # every call through api()
    assert "innerHTML" not in js  # server values via textContent only
