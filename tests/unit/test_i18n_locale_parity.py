"""i18n locale parity smoke test — Feature 14 Phase 2 Run A.

Reads en.js, nl.js, and fr.js as plain text, extracts exported key names
via regex, and asserts that all three files carry the identical key set.

This is a frontend artefact test (JS files parsed by Python) — no app
boot, no DB, no HTTP. Safe to run standalone without any fixture.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LOCALES_DIR = (
    Path(__file__).parent.parent.parent
    / "dashboard" / "js" / "locales"
)


def _extract_keys(filepath: Path) -> list[str]:
    """Return all top-level string keys from a JS locale file.

    Matches patterns like  'some.key': 'value'  anywhere in the file.
    Only the key portion (before the colon) is captured.
    """
    content = filepath.read_text(encoding="utf-8")
    return re.findall(r"'([^']+)'\s*:", content)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def en_keys() -> list[str]:
    return _extract_keys(_LOCALES_DIR / "en.js")


@pytest.fixture(scope="module")
def nl_keys() -> list[str]:
    return _extract_keys(_LOCALES_DIR / "nl.js")


@pytest.fixture(scope="module")
def fr_keys() -> list[str]:
    return _extract_keys(_LOCALES_DIR / "fr.js")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestLocaleKeyCount:
    """nl and fr must have the same number of keys as en."""

    def test_nl_key_count_matches_en(self, en_keys, nl_keys):
        assert len(nl_keys) == len(en_keys), (
            f"nl.js has {len(nl_keys)} keys but en.js has {len(en_keys)}. "
            f"Difference: {len(en_keys) - len(nl_keys)} keys missing from nl.js."
        )

    def test_fr_key_count_matches_en(self, en_keys, fr_keys):
        assert len(fr_keys) == len(en_keys), (
            f"fr.js has {len(fr_keys)} keys but en.js has {len(en_keys)}. "
            f"Difference: {len(en_keys) - len(fr_keys)} keys missing from fr.js."
        )


class TestLocaleKeyParity:
    """No key present in en.js may be absent from nl.js or fr.js."""

    def test_no_en_key_missing_from_nl(self, en_keys, nl_keys):
        en_set = set(en_keys)
        nl_set = set(nl_keys)
        missing = sorted(en_set - nl_set)
        assert not missing, (
            f"{len(missing)} key(s) in en.js are missing from nl.js:\n"
            + "\n".join(f"  - {k}" for k in missing)
        )

    def test_no_en_key_missing_from_fr(self, en_keys, fr_keys):
        en_set = set(en_keys)
        fr_set = set(fr_keys)
        missing = sorted(en_set - fr_set)
        assert not missing, (
            f"{len(missing)} key(s) in en.js are missing from fr.js:\n"
            + "\n".join(f"  - {k}" for k in missing)
        )

    def test_nl_has_no_extra_keys_vs_en(self, en_keys, nl_keys):
        """Guard against nl.js accumulating stale or phantom keys."""
        en_set = set(en_keys)
        nl_set = set(nl_keys)
        extra = sorted(nl_set - en_set)
        assert not extra, (
            f"{len(extra)} key(s) in nl.js are not in en.js:\n"
            + "\n".join(f"  - {k}" for k in extra)
        )

    def test_fr_has_no_extra_keys_vs_en(self, en_keys, fr_keys):
        """Guard against fr.js accumulating stale or phantom keys."""
        en_set = set(en_keys)
        fr_set = set(fr_keys)
        extra = sorted(fr_set - en_set)
        assert not extra, (
            f"{len(extra)} key(s) in fr.js are not in en.js:\n"
            + "\n".join(f"  - {k}" for k in extra)
        )


class TestPhase2KeysPresent:
    """Spot-check that Phase 2 Run A namespaces are present in all three locales."""

    _PHASE2_SAMPLE_KEYS = [
        # Agent Panel
        "agent.processing",
        "agent.sim_complete",
        "agent.run_day_btn",
        # AI Compliance
        "compliance.no_data_prompt",
        # Technical Analysis
        "ta.commentary_header",
        "ta.label_rsi14",
        "ta.label_macd",
        # Learnings
        "learnings.no_data",
        "learnings.label_nifty_close",
        # FnO Positions
        "pos.no_paper_positions",
        "pos.mode_live",
        # Margin
        "margin.assumed_ledger",
        "margin.utilization",
        # Greeks
        "greeks.gamma",
        "greeks.theta_day",
        # Hedge
        "hedge.reactive_score",
        "hedge.tier_lottery",
        # Manoeuvre
        "man.pool_title",
        "man.save_snapshot_btn",
        # Payoff
        "payoff.break_even",
        "payoff.nifty_level",
        # Risk-Reward
        "rr.bull_view",
        "rr.rr_summary",
        # Stress
        "stress.flat",
        # Pre-existing status keys (reused by agent-panel advisories)
        "status.running",
        "status.complete",
        "status.failed",
        "status.pending",
        # Pre-existing kpi key (reused by technical-analysis advisory)
        "kpi.signal",
    ]

    @pytest.mark.parametrize("key", _PHASE2_SAMPLE_KEYS)
    def test_key_in_en(self, en_keys, key):
        assert key in en_keys, f"Key '{key}' missing from en.js"

    @pytest.mark.parametrize("key", _PHASE2_SAMPLE_KEYS)
    def test_key_in_nl(self, nl_keys, key):
        assert key in nl_keys, f"Key '{key}' missing from nl.js"

    @pytest.mark.parametrize("key", _PHASE2_SAMPLE_KEYS)
    def test_key_in_fr(self, fr_keys, key):
        assert key in fr_keys, f"Key '{key}' missing from fr.js"
