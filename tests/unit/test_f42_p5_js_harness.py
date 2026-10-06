"""F42 P5 - behavioural check of dashboard/js/fno/trade-import.js under Node (no DOM library).
Skipped when node is not installed."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HARNESS = Path(__file__).with_name("f42_p5_js_smoke.mjs")

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


@pytest.fixture(scope="module")
def out() -> dict:
    r = subprocess.run(["node", str(HARNESS), str(ROOT)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_offer_state_shows_card_and_cta_only(out):
    o = out["offer"]
    assert o["card"] and not o["btnDisabled"] and o["cta"] and o["banner"] == "none"


def test_loaded_state_banner_escaped_and_uploads_disabled(out):
    o = out["loaded"]
    assert o["banner"] and "&lt;b&gt;2026-09-18" in o["text"] and "<b>" not in o["text"]
    assert o["fileDisabled"] and o["uploadDisabled"] and o["cta"] == "none"
    assert "Remove the sample data to import your own files." in o["chosen"]


def test_legacy_payload_without_sample_is_null_safe(out):
    assert out["legacy"] == {"banner": "none", "card": "none", "fileDisabled": False}


def test_unavailable_state_disables_button_with_message(out):
    assert out["unavailable"] == {"note": "Sample data is not available on this server.", "btnDisabled": True}


def test_load_posts_then_refreshes_status(out):
    assert out["load"][0].startswith("GET") and "import-status" in out["load"][0]
    assert any(c == "POST /api/v1/workflow/fno/console-import/sample" for c in out["load"])
    assert out["load"][-1].startswith("GET") and "import-status" in out["load"][-1]


def test_refusal_text_survives_a_late_status_render(out):
    assert "Sample &lt;b&gt;failed" in out["refusal"]["note"]
    assert out["refusal"]["banner"] == "Sample <b>failed"        # textContent: shown verbatim, not parsed


def test_remove_deletes_and_clears_the_note(out):
    assert out["removed"] is True
    assert out["deleteCall"] == ["DELETE /api/v1/workflow/fno/console-import?confirm=true"]
    assert out["noteAfterRemove"] == ""
