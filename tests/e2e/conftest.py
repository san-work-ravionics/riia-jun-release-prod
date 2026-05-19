"""E2E conftest — starts a real uvicorn server before the test session.

The server runs at http://127.0.0.1:8765 so it does not clash with a
dev server on the default port 8000.

Path patching
-------------
We mirror the same sys.path logic used by riia-jun-release/conftest.py so
that ``rita`` can be imported both by the test process (for any helper
imports) and, more importantly, by the subprocess that runs uvicorn.
The subprocess receives ``RITA_ENV=development`` and has ``src/`` on
``PYTHONPATH`` via the environment.

Server readiness
----------------
After spawning the subprocess we poll ``GET /health`` with a 15-second
timeout (0.25 s between polls).  The fixture raises ``RuntimeError`` if the
server does not become ready in time, which causes the entire session to fail
fast with a clear message.
"""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest
import requests

# ---------------------------------------------------------------------------
# Path setup — keep in sync with riia-jun-release/conftest.py
# ---------------------------------------------------------------------------
_E2E_DIR = Path(__file__).parent               # riia-jun-release/tests/e2e/
_TESTS_DIR = _E2E_DIR.parent                   # riia-jun-release/tests/
_RELEASE_ROOT = _TESTS_DIR.parent              # riia-jun-release/
_SRC = _RELEASE_ROOT / "src"
_CONFIG_DIR = _RELEASE_ROOT / "config"

if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_HOST = "127.0.0.1"
_PORT = 8765
_BASE_URL = f"http://{_HOST}:{_PORT}"
_STARTUP_TIMEOUT_S = 15
_POLL_INTERVAL_S = 0.25


# ---------------------------------------------------------------------------
# Session-scoped server fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def base_url(server) -> str:  # noqa: ARG001 — depends on server to ensure ordering
    """Return the root URL of the running test server."""
    return _BASE_URL


@pytest.fixture(scope="session")
def auth_token(base_url: str) -> str:
    """Return a JWT bearer token for authenticated API calls.

    Uses the dev password hard-coded in auth.py (``rita-dev``).
    Session-scoped so the token is requested once per test run.
    """
    r = requests.post(
        f"{base_url}/auth/token",
        json={"username": "test", "password": "rita-dev"},
        timeout=10,
    )
    assert r.status_code == 200, f"Auth token request failed: {r.status_code} — {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def server():
    """Spawn uvicorn in a subprocess and tear it down after the session.

    The subprocess inherits the current environment but with two additions:
    - ``PYTHONPATH`` extended with ``src/`` so uvicorn can find the ``rita``
      package even when the package is not installed in editable mode.
    - ``RITA_ENV=development`` so the app loads the development config.
    """
    env = os.environ.copy()

    # Extend PYTHONPATH so the subprocess can import rita
    existing_pythonpath = env.get("PYTHONPATH", "")
    src_str = str(_SRC)
    env["PYTHONPATH"] = (
        f"{src_str}{os.pathsep}{existing_pythonpath}"
        if existing_pythonpath
        else src_str
    )
    env["RITA_ENV"] = "development"

    cmd = [
        sys.executable,
        "-m", "uvicorn",
        "rita.main:app",
        "--host", _HOST,
        "--port", str(_PORT),
    ]

    proc = subprocess.Popen(
        cmd,
        env=env,
        cwd=str(_RELEASE_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # -----------------------------------------------------------------------
    # Wait for the server to become ready
    # -----------------------------------------------------------------------
    deadline = time.monotonic() + _STARTUP_TIMEOUT_S
    ready = False
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        try:
            resp = requests.get(f"{_BASE_URL}/health", timeout=2)
            if resp.status_code == 200:
                ready = True
                break
        except requests.RequestException as exc:
            last_error = exc
        time.sleep(_POLL_INTERVAL_S)

    if not ready:
        proc.terminate()
        proc.wait(timeout=5)
        stderr_output = b""
        if proc.stderr:
            stderr_output = proc.stderr.read()
        raise RuntimeError(
            f"Uvicorn did not become ready within {_STARTUP_TIMEOUT_S}s. "
            f"Last error: {last_error}. "
            f"Server stderr:\n{stderr_output.decode(errors='replace')}"
        )

    yield proc

    # -----------------------------------------------------------------------
    # Teardown
    # -----------------------------------------------------------------------
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


