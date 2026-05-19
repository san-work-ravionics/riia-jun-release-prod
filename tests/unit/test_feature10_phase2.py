"""
Feature 10 Phase 2 — JS re-export contract verification tests.

Pure JS refactoring: rita/ and ops/ modules are now thin re-export wrappers
pointing to shared/. Tests verify file content (exports, import paths, deleted
files) using file-read assertions — a valid static contract-testing pattern for
this codebase.
"""

import os
from pathlib import Path

import pytest


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def js_root() -> Path:
    """Return the dashboard/js/ directory relative to this test file."""
    # tests/unit/ → tests/ → riia-jun-release/ → dashboard/js/
    return Path(__file__).parent.parent.parent / "dashboard" / "js"


# ── Test 1: rita/api.js re-export contract ────────────────────────────────────

def test_rita_api_js_re_export_contract(js_root):
    """rita/api.js must be a thin re-export wrapper pointing to shared/api.js."""
    content = (js_root / "rita" / "api.js").read_text(encoding="utf-8")

    assert "from '../shared/api.js'" in content, (
        "rita/api.js must re-export from '../shared/api.js'"
    )
    assert "api" in content, (
        "rita/api.js must export 'api'"
    )
    assert "async function api(" not in content, (
        "rita/api.js must NOT contain a local 'async function api(' definition — "
        "it should be a pure re-export wrapper"
    )


# ── Test 2: rita/utils.js re-export contract ──────────────────────────────────

def test_rita_utils_js_re_export_contract(js_root):
    """rita/utils.js must re-export all 6 symbols from shared/utils.js."""
    content = (js_root / "rita" / "utils.js").read_text(encoding="utf-8")

    assert "from '../shared/utils.js'" in content, (
        "rita/utils.js must re-export from '../shared/utils.js'"
    )
    for symbol in ("fmt", "fmtPct", "fmtMs", "setEl", "appendResult", "badge"):
        assert symbol in content, (
            f"rita/utils.js must export '{symbol}'"
        )
    assert "export function setEl(" not in content, (
        "rita/utils.js must NOT contain a local 'export function setEl(' — "
        "it should be a pure re-export wrapper"
    )


# ── Test 3: shared/api.js named export availability (FC-IMP gate) ────────────

def test_shared_api_js_named_exports(js_root):
    """shared/api.js must export api, apiFetch, and apiBase (FC-IMP gate)."""
    content = (js_root / "shared" / "api.js").read_text(encoding="utf-8")

    assert "export" in content and "api" in content, (
        "shared/api.js must export 'api'"
    )
    assert "apiFetch" in content, (
        "shared/api.js must export 'apiFetch'"
    )
    assert "apiBase" in content, (
        "shared/api.js must export 'apiBase'"
    )
    # Confirm they are actual export declarations, not just string occurrences
    assert "export async function api(" in content or "export const api" in content, (
        "shared/api.js must have an exported 'api' declaration"
    )
    assert "export async function apiFetch(" in content or "export const apiFetch" in content, (
        "shared/api.js must have an exported 'apiFetch' declaration"
    )
    assert "export const apiBase" in content or "export function apiBase" in content, (
        "shared/api.js must have an exported 'apiBase' declaration"
    )


# ── Test 4: shared/utils.js named export availability (FC-IMP gate) ──────────

def test_shared_utils_js_named_exports(js_root):
    """shared/utils.js must export all 6 utility symbols (FC-IMP gate)."""
    content = (js_root / "shared" / "utils.js").read_text(encoding="utf-8")

    for symbol in ("fmt", "fmtPct", "fmtMs", "setEl", "appendResult", "badge"):
        assert symbol in content, (
            f"shared/utils.js must export '{symbol}'"
        )
    # Verify they are actual export declarations
    assert "export const fmt" in content or "export function fmt" in content, (
        "shared/utils.js must have an exported 'fmt' declaration"
    )
    assert "export function setEl(" in content, (
        "shared/utils.js must have an exported 'setEl' function"
    )
    assert "export function badge(" in content, (
        "shared/utils.js must have an exported 'badge' function"
    )


# ── Test 5: ops/api.js re-export contract ────────────────────────────────────

def test_ops_api_js_re_export_contract(js_root):
    """ops/api.js must be a thin re-export wrapper exporting all 3 shared symbols."""
    content = (js_root / "ops" / "api.js").read_text(encoding="utf-8")

    assert "from '../shared/api.js'" in content, (
        "ops/api.js must re-export from '../shared/api.js'"
    )
    for symbol in ("apiBase", "api", "apiFetch"):
        assert symbol in content, (
            f"ops/api.js must export '{symbol}'"
        )


# ── Test 6: ops/utils.js merge contract ──────────────────────────────────────

def test_ops_utils_js_merge_contract(js_root):
    """ops/utils.js merged file must export all 10 required symbols."""
    content = (js_root / "ops" / "utils.js").read_text(encoding="utf-8")

    required_symbols = (
        "fmt", "setEl", "badge", "stepName",
        "runGoal", "runMarket", "runStrategy", "runFullPipeline",
        "doReset", "loadUtilities",
    )
    for symbol in required_symbols:
        assert symbol in content, (
            f"ops/utils.js must export '{symbol}' (merge contract)"
        )

    # badge must be a local two-argument definition, NOT re-exported from shared
    assert ("badge(text, cls)" in content or "badge(text,cls)" in content), (
        "ops/utils.js must define badge(text, cls) locally with two arguments "
        "(incompatible with shared single-arg badge)"
    )

    # Must NOT import from the deleted ./utilities.js
    assert "from './utilities.js'" not in content, (
        "ops/utils.js must NOT import from './utilities.js' — "
        "utilities.js has been deleted and its content merged into utils.js"
    )


# ── Test 7: ops/utilities.js deleted ─────────────────────────────────────────

def test_ops_utilities_js_deleted(js_root):
    """ops/utilities.js must not exist — it was deleted after merging into utils.js."""
    utilities_path = js_root / "ops" / "utilities.js"
    assert not utilities_path.exists(), (
        f"ops/utilities.js must be deleted after Phase 2 merge, "
        f"but it still exists at {utilities_path}"
    )


# ── Test 8: ops/main.js import updated ───────────────────────────────────────

def test_ops_main_js_import_updated(js_root):
    """ops/main.js must import from utils.js (not the deleted utilities.js)."""
    content = (js_root / "ops" / "main.js").read_text(encoding="utf-8")

    assert "from './utilities.js'" not in content, (
        "ops/main.js must NOT contain `from './utilities.js'` — "
        "that file has been deleted; import should point to utils.js"
    )
    assert "from './utils.js'" in content, (
        "ops/main.js must import from './utils.js'"
    )


# ── Test 9: rita/main.js inline apiFetch removed (edge case 6) ───────────────

def test_rita_main_js_inline_apiFetch_removed(js_root):
    """rita/main.js must not contain a local apiFetch definition or SESSION_TRACE_ID.

    Edge case 6 from the Architect: the inline apiFetch in main.js was unused
    and must be removed to avoid shadowing the shared module import.
    """
    content = (js_root / "rita" / "main.js").read_text(encoding="utf-8")

    assert "async function apiFetch(" not in content, (
        "rita/main.js must NOT contain 'async function apiFetch(' — "
        "the local inline definition must be removed (Architect edge case 6)"
    )
    assert "SESSION_TRACE_ID" not in content, (
        "rita/main.js must NOT reference SESSION_TRACE_ID — "
        "the inline apiFetch that used it must be removed (Architect edge case 6)"
    )
