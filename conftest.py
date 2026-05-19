"""Root conftest.py — shared setup for all tests.

Problem
-------
rita.config has a module-level assignment:

    _CONFIG_DIR: Path = Path(__file__).parent.parent.parent.parent / "config"

In the worktree layout (.claude/worktrees/agent-a579fe8f/riia-jun-release/src/rita/config.py)
the 4-level ascent lands at .claude/worktrees/agent-a579fe8f/ — not inside
riia-jun-release/ — so config/base.yaml is not found.

Fix
---
We monkeypatch the built-in `pathlib.Path.__truediv__` at conftest load
time? No — too invasive.

The cleanest working fix: subclass `pathlib.Path` to intercept the specific
parent chain... also invasive.

Real fix: the simplest working approach is to load the config module with
the correct `__file__` by temporarily patching `builtins.__file__` during
import — not possible.

ACTUALLY SIMPLEST: use `os.chdir` to the riia-jun-release directory so that
`Path(__file__).parent.parent.parent.parent` resolves correctly?  No —
__file__ is absolute.

THE REAL FIX: read config.py source, replace the _CONFIG_DIR line with one
pointing to the correct directory, then exec it.  This is safe because we
only change one constant.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# sys.path
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).parent          # riia-jun-release/
_SRC = _REPO_ROOT / "src"
_CONFIG_DIR = _REPO_ROOT / "config"

if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def _load_rita_config_with_correct_path():
    """
    Load rita.config with _CONFIG_DIR pointing at riia-jun-release/config/.

    We rewrite the single line that computes _CONFIG_DIR in the source
    before executing the module.  All other code remains unchanged.
    """
    if "rita.config" in sys.modules:
        cfg = sys.modules["rita.config"]
        # Already loaded — just re-point and reset
        cfg._CONFIG_DIR = _CONFIG_DIR
        cfg.get_settings.cache_clear()
        cfg.settings = cfg.Settings()
        return

    config_source_path = _SRC / "rita" / "config.py"
    source = config_source_path.read_text(encoding="utf-8")

    # Replace the _CONFIG_DIR computation line with the correct literal path.
    # Use raw string with forward slashes to be platform-safe inside the exec.
    correct_dir = str(_CONFIG_DIR).replace("\\", "/")
    original_line = (
        "_CONFIG_DIR: Path = Path(__file__).parent.parent.parent.parent / \"config\""
    )
    replacement_line = f'_CONFIG_DIR: Path = Path(r"{correct_dir}")'
    patched_source = source.replace(original_line, replacement_line, 1)

    if patched_source == source:
        # The sentinel line was not found — fall back to normal import and patch after
        import importlib.util
        spec = importlib.util.spec_from_file_location("rita.config", config_source_path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["rita.config"] = mod
        spec.loader.exec_module(mod)
        mod._CONFIG_DIR = _CONFIG_DIR
        mod.get_settings.cache_clear()
        return

    # Ensure rita package exists in sys.modules
    if "rita" not in sys.modules:
        rita_pkg = types.ModuleType("rita")
        rita_pkg.__path__ = [str(_SRC / "rita")]
        rita_pkg.__package__ = "rita"
        rita_pkg.__spec__ = None
        sys.modules["rita"] = rita_pkg

    import importlib.util
    mod = types.ModuleType("rita.config")
    mod.__file__ = str(config_source_path)
    mod.__package__ = "rita"
    mod.__loader__ = None

    sys.modules["rita.config"] = mod  # register early to avoid circular imports

    code = compile(patched_source, str(config_source_path), "exec")
    exec(code, mod.__dict__)


# Run before collection
_load_rita_config_with_correct_path()


@pytest.fixture(autouse=True, scope="session")
def _ensure_config_dir_patched():
    """Ensure _CONFIG_DIR stays patched for the entire test session."""
    import rita.config as cfg_module
    cfg_module._CONFIG_DIR = _CONFIG_DIR
    yield


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    """Move a completed JUnit XML from test-execution/ into test-results/.

    pytest writes the XML to test-execution/<stem>.xml during the run.
    After the session ends we move it to test-results/<type>/<timestamp>-<name>.xml
    so the display folder only ever contains finished, uniquely-named results.

    Stem → destination mapping:
      e2e-rita  →  test-results/e2e/rita/<ts>-rita.xml
      e2e-fno   →  test-results/e2e/fno/<ts>-fno.xml
      e2e-ops   →  test-results/e2e/ops/<ts>-ops.xml
      unit      →  test-results/unit/<ts>-unit.xml
      integration → test-results/integration/<ts>-integration.xml
    """
    import shutil
    from datetime import datetime

    xmlpath = getattr(session.config.option, "xmlpath", None)
    if not xmlpath:
        return
    xml_file = Path(xmlpath).resolve()
    if not xml_file.exists():
        return

    exec_dir = _REPO_ROOT / "test-execution"
    try:
        xml_file.relative_to(exec_dir)
    except ValueError:
        return  # not in test-execution/ — nothing to do

    stem = xml_file.stem  # e.g. "e2e-rita", "unit", "integration"
    ts = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")

    if stem.startswith("e2e-"):
        suite_name = stem[4:]  # "rita", "fno", "ops"
        dest_dir = _REPO_ROOT / "test-results" / "e2e" / suite_name
        dest_name = f"{ts}-{suite_name}.xml"
    else:
        dest_dir = _REPO_ROOT / "test-results" / stem
        dest_name = f"{ts}-{stem}.xml"

    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(xml_file), dest_dir / dest_name)
