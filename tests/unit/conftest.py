"""Unit-test fixtures for RITA — DB session and TestClient.

Notes
-----
- No autouse fixtures. Existing API tests (test_api_system.py, etc.) create
  their own TestClient and manage DI overrides independently; this conftest
  must not interfere with them.
- The ``db_session`` fixture creates an isolated in-memory SQLite database for
  each test function and drops all tables on teardown.
- The ``client`` fixture wires ``db_session`` into FastAPI's ``get_db``
  dependency so repository tests can hit the full request stack if needed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# ---------------------------------------------------------------------------
# Config-path patch — must happen before any rita import so that
# get_settings() resolves the real config/ directory.
# ---------------------------------------------------------------------------
import rita.config as _rita_config  # noqa: E402

_rita_config._CONFIG_DIR = Path(__file__).parent.parent.parent / "config"
_rita_config.get_settings.cache_clear()

# ---------------------------------------------------------------------------
# Patch pandas.read_csv for agent_panel — worktree has no data CSV files.
# The patch must wrap the import of rita.main to prevent module-level
# _load_april_data() from failing on first import.
# ---------------------------------------------------------------------------
from unittest.mock import patch as _patch  # noqa: E402
import pandas as _pd  # noqa: E402

_empty_df = _pd.DataFrame({
    "date": _pd.Series([], dtype="datetime64[ns]"),
    "close": _pd.Series([], dtype=float),
    "open": _pd.Series([], dtype=float),
    "high": _pd.Series([], dtype=float),
    "low": _pd.Series([], dtype=float),
    "volume": _pd.Series([], dtype=float),
})
with _patch("pandas.read_csv", return_value=_empty_df):
    from rita.database import Base, get_db  # noqa: E402
    import rita.models  # noqa: F401, E402 — registers all ORM models with Base.metadata
    from fastapi.testclient import TestClient  # noqa: E402
    from rita.main import app  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def db_session():
    """In-memory SQLite session.

    Creates all ORM tables before each test and drops them on teardown so
    every test starts with a clean, empty schema.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture(scope="function")
def client(db_session):
    """TestClient whose ``get_db`` dependency returns the in-memory session.

    Cleans up the override after the test so it does not bleed into other
    tests that create their own TestClient.
    """
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_db, None)
