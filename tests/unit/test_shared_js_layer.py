"""
Feature 10 Phase 1 — Shared JS Layer Contract Verification
===========================================================
These tests verify the file-system contracts for the 4 new shared JS modules
and the re-export shim in rita/charts.js. Since the deliverables are pure JS
files (not Python), tests use plain file-read assertions: path existence,
expected export names, correct import paths, and edge-case guards from the
Architect's DoD.

No mocking needed — all checks are static string searches.
"""
import os
import pathlib
import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_WORKTREE = pathlib.Path(__file__).parents[2]  # riia-jun-release root
_SHARED = _WORKTREE / "dashboard" / "js" / "shared"
_RITA_JS = _WORKTREE / "dashboard" / "js" / "rita"

API_JS      = _SHARED / "api.js"
UTILS_JS    = _SHARED / "utils.js"
CHARTS_JS   = _SHARED / "charts.js"
NAV_JS      = _SHARED / "nav-base.js"
RITA_CHARTS = _RITA_JS / "charts.js"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ===========================================================================
# 1. File Existence
# ===========================================================================

class TestFilesExist:
    def test_shared_api_js_exists(self):
        assert API_JS.exists(), f"Missing: {API_JS}"

    def test_shared_utils_js_exists(self):
        assert UTILS_JS.exists(), f"Missing: {UTILS_JS}"

    def test_shared_charts_js_exists(self):
        assert CHARTS_JS.exists(), f"Missing: {CHARTS_JS}"

    def test_shared_nav_base_js_exists(self):
        assert NAV_JS.exists(), f"Missing: {NAV_JS}"

    def test_rita_charts_shim_exists(self):
        assert RITA_CHARTS.exists(), f"Missing: {RITA_CHARTS}"


# ===========================================================================
# 2. shared/api.js — Exports Contract
# ===========================================================================

class TestSharedApiExports:
    """Architect contract: apiBase (const), api (async function), apiFetch (async function)."""

    def test_export_apiBase(self):
        src = _read(API_JS)
        assert "export const apiBase" in src, "shared/api.js missing: export const apiBase"

    def test_export_api_async_function(self):
        src = _read(API_JS)
        assert "export async function api(" in src, "shared/api.js missing: export async function api"

    def test_export_apiFetch_async_function(self):
        src = _read(API_JS)
        assert "export async function apiFetch(" in src, "shared/api.js missing: export async function apiFetch"

    # EC-1: apiFetch url is prepended with apiBase() — not a full URL
    def test_ec1_apiFetch_prepends_apiBase(self):
        src = _read(API_JS)
        assert "apiBase() + url" in src, "EC-1: apiFetch must prepend apiBase() to url"

    # EC-3: SESSION_TRACE_ID read at call time (inside function body), not at import time
    def test_ec3_trace_id_read_at_call_time(self):
        src = _read(API_JS)
        # SESSION_TRACE_ID must appear inside apiFetch body, after the function declaration
        func_start = src.index("export async function apiFetch(")
        assert "SESSION_TRACE_ID" in src[func_start:], \
            "EC-3: SESSION_TRACE_ID must be read at call time (inside apiFetch body)"

    def test_api_throws_on_non_2xx(self):
        src = _read(API_JS)
        assert "throw new Error" in src, "api() must throw on non-2xx response"

    def test_apiFetch_returns_null_on_error(self):
        src = _read(API_JS)
        assert "return null" in src, "apiFetch() must return null on error"

    def test_x_request_id_header_present(self):
        src = _read(API_JS)
        assert "X-Request-ID" in src, "apiFetch() must add X-Request-ID header"


# ===========================================================================
# 3. shared/utils.js — Exports Contract
# ===========================================================================

class TestSharedUtilsExports:
    """Architect contract: fmt, fmtPct, fmtMs (const), setEl, appendResult, badge (function)."""

    def test_export_fmt(self):
        src = _read(UTILS_JS)
        assert "export const fmt" in src, "shared/utils.js missing: export const fmt"

    def test_export_fmtPct(self):
        src = _read(UTILS_JS)
        assert "export const fmtPct" in src, "shared/utils.js missing: export const fmtPct"

    def test_export_fmtMs(self):
        src = _read(UTILS_JS)
        assert "export const fmtMs" in src, "shared/utils.js missing: export const fmtMs"

    def test_export_setEl_function(self):
        src = _read(UTILS_JS)
        assert "export function setEl(" in src, "shared/utils.js missing: export function setEl"

    def test_export_appendResult_function(self):
        src = _read(UTILS_JS)
        assert "export function appendResult(" in src, "shared/utils.js missing: export function appendResult"

    def test_export_badge_function(self):
        src = _read(UTILS_JS)
        assert "export function badge(" in src, "shared/utils.js missing: export function badge"

    # EC-5: badge() must coerce status with String(status || '') before .toLowerCase()
    def test_ec5_badge_string_coercion(self):
        src = _read(UTILS_JS)
        assert "String(status" in src, \
            "EC-5: badge() must use String(status ...) coercion"

    def test_ec5_badge_uses_toLowerCase(self):
        src = _read(UTILS_JS)
        assert ".toLowerCase()" in src, "badge() must call .toLowerCase() after coercion"

    def test_fmt_returns_dash_on_null(self):
        src = _read(UTILS_JS)
        # fmt arrow function returns '—' for null/undefined/empty
        assert "'—'" in src or '"—"' in src, "fmt() must return '—' sentinel on null/undefined/empty"


# ===========================================================================
# 4. shared/charts.js — Exports Contract + Import Path
# ===========================================================================

class TestSharedChartsExports:
    """Architect contract: destroyChart, mkChart, chartOpts (functions), C (const)."""

    def test_export_destroyChart(self):
        src = _read(CHARTS_JS)
        assert "export function destroyChart(" in src, \
            "shared/charts.js missing: export function destroyChart"

    def test_export_mkChart(self):
        src = _read(CHARTS_JS)
        assert "export function mkChart(" in src, \
            "shared/charts.js missing: export function mkChart"

    def test_export_chartOpts(self):
        src = _read(CHARTS_JS)
        assert "export function chartOpts(" in src, \
            "shared/charts.js missing: export function chartOpts"

    def test_export_C_color_palette(self):
        src = _read(CHARTS_JS)
        assert "export const C" in src, \
            "shared/charts.js missing: export const C (color palette)"

    def test_import_path_is_updated_to_rita(self):
        """Import must reference '../rita/chart-modal.js', not './chart-modal.js'."""
        src = _read(CHARTS_JS)
        assert "../rita/chart-modal.js" in src, \
            "shared/charts.js must import from '../rita/chart-modal.js'"

    def test_old_import_path_not_present(self):
        """The old './chart-modal.js' relative path must not remain."""
        src = _read(CHARTS_JS)
        assert "./chart-modal.js" not in src, \
            "shared/charts.js must NOT contain old import path './chart-modal.js'"


# ===========================================================================
# 5. shared/nav-base.js — Exports Contract
# ===========================================================================

class TestSharedNavBaseExports:
    """Architect contract: createNavRegistry() factory function."""

    def test_export_createNavRegistry(self):
        src = _read(NAV_JS)
        assert "export function createNavRegistry(" in src, \
            "shared/nav-base.js missing: export function createNavRegistry"

    def test_register_method_present(self):
        src = _read(NAV_JS)
        assert "register(" in src, "createNavRegistry must expose register(key, fn)"

    def test_load_method_present(self):
        src = _read(NAV_JS)
        assert "load(" in src, "createNavRegistry must expose load(key)"

    def test_reset_method_present(self):
        src = _read(NAV_JS)
        assert "reset(" in src, "createNavRegistry must expose reset(key)"

    def test_loaders_property_exposed(self):
        src = _read(NAV_JS)
        assert "loaders" in src, "createNavRegistry must expose loaders property"

    # EC-6: load() must silently no-op for unregistered keys
    def test_ec6_load_guards_unregistered_keys(self):
        src = _read(NAV_JS)
        # Guard: load() checks loaders[key] before calling — either via 'loaders[key]' in condition
        # or equivalent falsy check
        assert "loaders[key]" in src, \
            "EC-6: load() must guard against unregistered keys via loaders[key] check"


# ===========================================================================
# 6. rita/charts.js — Re-export Shim
# ===========================================================================

class TestRitaChartsShim:
    def test_shim_contains_reexport_from_shared(self):
        src = _read(RITA_CHARTS)
        assert "export * from '../shared/charts.js'" in src, \
            "rita/charts.js must contain: export * from '../shared/charts.js'"

    def test_shim_is_single_line(self):
        """Shim file should contain only the re-export line (plus optional trailing newline)."""
        src = _read(RITA_CHARTS)
        stripped = src.strip()
        assert stripped == "export * from '../shared/charts.js';", \
            f"rita/charts.js shim must be exactly one line, got: {stripped!r}"

    def test_shim_path_depth_correct(self):
        """
        rita/charts.js lives at dashboard/js/rita/charts.js.
        Shared module is at dashboard/js/shared/charts.js.
        Relative path from rita/ to shared/ is '../shared/charts.js'.
        """
        src = _read(RITA_CHARTS)
        assert "'../shared/charts.js'" in src, \
            "rita/charts.js shim path must be '../shared/charts.js' (one level up)"


# ===========================================================================
# 7. Cross-module: no stale local copies
# ===========================================================================

class TestNoCrossContamination:
    def test_shared_api_js_has_no_window_bindings(self):
        """Architect: no new window bindings in shared modules."""
        src = _read(API_JS)
        assert "window." not in src.replace("window.RITA_API_BASE", "").replace("window.SESSION_TRACE_ID", "").replace("window.location.href", ""), \
            "shared/api.js must only access window.RITA_API_BASE, window.SESSION_TRACE_ID, and window.location.href (OAuth redirect)"

    def test_shared_utils_js_no_fetch_calls(self):
        """utils.js is DOM helpers only — must not call fetch()."""
        src = _read(UTILS_JS)
        assert "fetch(" not in src, "shared/utils.js must not contain fetch() calls"

    def test_shared_nav_base_no_fetch_calls(self):
        """nav-base.js is a registry factory — must not call fetch()."""
        src = _read(NAV_JS)
        assert "fetch(" not in src, "shared/nav-base.js must not contain fetch() calls"
