"""Naive API timestamps (UTC, no Z) must be parsed as UTC by the FnO dashboard, not as browser-local time."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

_FNO = Path(__file__).resolve().parents[2] / "dashboard" / "js" / "fno"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def _helper() -> str:
    m = re.search(r"^function _utcIso\(.*$", (_FNO / "my-portfolio.js").read_text(), re.M)
    assert m, "_utcIso helper missing"
    return m.group(0)


def _run(expr: str) -> str:
    out = subprocess.run(["node", "-e", f"{_helper()}\nconsole.log({expr})"], capture_output=True, text=True,
                         env={"TZ": "Europe/Amsterdam", "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"}, check=True)
    return out.stdout.strip()


def test_naive_timestamp_is_utc():
    assert _run("new Date(_utcIso('2026-10-04T11:50:00')).toISOString()") == "2026-10-04T11:50:00.000Z"


@pytest.mark.parametrize("ts", ["2026-10-04T11:50:00Z", "2026-10-04T13:50:00+02:00"])
def test_tz_aware_timestamp_unchanged(ts):
    assert _run(f"_utcIso('{ts}')") == ts


def test_non_string_passthrough():
    assert _run("_utcIso(null)") == "null"


def test_save_step_formatter_uses_same_rule():
    src = (_FNO / "hedge-workflow-save.js").read_text()
    assert "iso + 'Z'" in src and "(Z|[+-]" in src
