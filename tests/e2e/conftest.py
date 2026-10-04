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
import sqlite3
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
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
        json={"username": "rita-dev", "password": "rita-dev"},
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




# ---------------------------------------------------------------------------
# F40 — isolated server on a temp, seeded SQLite DB (never touches rita_output/rita.db)
# ---------------------------------------------------------------------------
_ISO_PORT = 8766
_ISO_URL = f"http://{_HOST}:{_ISO_PORT}"
_REAL_DB = _RELEASE_ROOT / "rita_output" / "rita.db"

# Seeded deterministic data (asserted by the F40 legs)
ISO_USER = "rita-dev"
ISO_KEY = "e2e-key-1"
ISO_SHARES = {"ASML": 10, "RELIANCE": 7}
ISO_LAST_CLOSE = {"ASML": 700.0, "RELIANCE": 2500.0}


def _seed_isolated_db(db_path: Path) -> None:
    """Seed users row, portfolio key, portfolio (ASML EUR + RELIANCE INR), ~14 months of closes."""
    import json

    con = sqlite3.connect(db_path)
    try:
        con.execute("INSERT OR IGNORE INTO users (id, can_access_ops, can_create_portfolio) VALUES (?, 1, 1)", (ISO_USER,))
        con.execute("INSERT INTO user_portfolio_keys (key_id, user_id) VALUES (?, ?)", (ISO_KEY, ISO_USER))
        holdings = [
            {"instrument_id": "ASML", "allocation_pct": 60.0, "shares": ISO_SHARES["ASML"], "cash_eur": 5.0},
            {"instrument_id": "RELIANCE", "allocation_pct": 40.0, "shares": ISO_SHARES["RELIANCE"], "cash_eur": 3.0},
        ]
        con.execute(
            "INSERT INTO user_portfolios (portfolio_id, key_id, name, holdings, total_value_eur, is_active, created_at, updated_at) "
            "VALUES ('e2e-p1', ?, 'e2e', ?, 20000.0, 1, datetime('now'), datetime('now'))", (ISO_KEY, json.dumps(holdings)),
        )
        # Server startup seeds market_data_cache from CSVs; replace those two instruments with
        # deterministic closes so position_value assertions are exact.
        con.execute("DELETE FROM market_data_cache WHERE underlying IN ('ASML', 'RELIANCE')")
        start = date(2025, 8, 1)
        n = 430  # ~14 months of calendar days
        for name, last in ISO_LAST_CLOSE.items():
            for i in range(n):
                d = start + timedelta(days=i)
                close = last if i == n - 1 else last * (1 + 0.01 * ((i % 7) - 3) / 3)
                con.execute(
                    "INSERT INTO market_data_cache (cache_id, date, underlying, open, high, low, close, recorded_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (f"{name}-{i}", d.isoformat(), name, close, close, close, close, datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')),
                )
        con.commit()
    finally:
        con.close()


@pytest.fixture(scope="session")
def isolated_server(tmp_path_factory):
    """uvicorn on port 8766 against a TEMP SQLite DB (DATABASE_URL override).

    Startup guard: (1) alembic upgrade head runs on the temp DB first; (2) after boot the
    server must serve the seeded holdings (proves it reads the temp DB, i.e. the env override
    beat any YAML default); (3) rita_output/rita.db mtime must be unchanged at boot and teardown.
    """
    tmp = tmp_path_factory.mktemp("f40_e2e")
    db_path = tmp / "f40_e2e.db"
    db_url = f"sqlite:///{db_path}"
    real_mtime = _REAL_DB.stat().st_mtime if _REAL_DB.exists() else None

    env = os.environ.copy()
    env["PYTHONPATH"] = f"{_SRC}{os.pathsep}{env['PYTHONPATH']}" if env.get("PYTHONPATH") else str(_SRC)
    env["RITA_ENV"] = "development"
    env["DATABASE_URL"] = db_url

    mig = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        env=env, cwd=str(_RELEASE_ROOT), capture_output=True, text=True, timeout=300,
    )
    assert mig.returncode == 0, f"alembic upgrade head failed on temp DB:\n{mig.stderr[-2000:]}"
    assert db_path.exists(), "alembic did not create the temp DB — DATABASE_URL override not honoured"

    out = open(tmp / "server.out", "wb")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "rita.main:app", "--host", _HOST, "--port", str(_ISO_PORT)],
        env=env, cwd=str(_RELEASE_ROOT), stdout=out, stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.monotonic() + 60
        ready = False
        while time.monotonic() < deadline and proc.poll() is None:
            try:
                if requests.get(f"{_ISO_URL}/health", timeout=2).status_code == 200:
                    ready = True
                    break
            except requests.RequestException:
                pass
            time.sleep(_POLL_INTERVAL_S)
        if not ready:
            raise RuntimeError("isolated uvicorn not ready:\n" + (tmp / "server.out").read_text(errors="replace")[-3000:])

        _seed_isolated_db(db_path)

        # Startup guard: server must see the seeded rows that exist ONLY in the temp DB.
        tok = requests.post(f"{_ISO_URL}/auth/token", json={"username": "rita-dev", "password": "rita-dev"}, timeout=10)
        assert tok.status_code == 200, tok.text
        probe = requests.get(
            f"{_ISO_URL}/api/v1/experience/user-portfolio",
            headers={"Authorization": f"Bearer {tok.json()['access_token']}"}, timeout=10,
        )
        ids = sorted(h["instrument_id"] for h in (probe.json() or {}).get("holdings", [])) if probe.status_code == 200 and probe.json() else []
        assert ids == ["ASML", "RELIANCE"], (
            f"ISOLATION GUARD FAILED: server does not see the seeded temp DB (status {probe.status_code}, holdings {ids}); "
            "DATABASE_URL override is not taking effect — aborting before any write."
        )
        if real_mtime is not None:
            assert _REAL_DB.stat().st_mtime == real_mtime, "ISOLATION GUARD FAILED: rita_output/rita.db was modified"
        yield {"url": _ISO_URL, "db_path": db_path}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        out.close()
        keep = os.environ.get("F40_E2E_SERVER_LOG")  # optional: keep the isolated server's log for diagnosis
        if keep:
            shutil.copyfile(tmp / "server.out", keep)
        if real_mtime is not None:
            assert _REAL_DB.stat().st_mtime == real_mtime, "ISOLATION GUARD FAILED at teardown: rita_output/rita.db modified"
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture(scope="session")
def iso_base_url(isolated_server) -> str:
    return isolated_server["url"]


@pytest.fixture(scope="session")
def iso_headers(iso_base_url) -> dict:
    r = requests.post(f"{iso_base_url}/auth/token", json={"username": "rita-dev", "password": "rita-dev"}, timeout=10)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
